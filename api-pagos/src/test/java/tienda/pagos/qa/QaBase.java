package tienda.pagos.qa;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import org.junit.jupiter.api.Assumptions;
import org.springframework.test.context.DynamicPropertyRegistry;

/**
 * Utilidades compartidas de la suite QA hostil. Requiere PostgreSQL real:
 * PAGOS_TEST_DB_PASSWORD (obligatoria; si falta, las pruebas se omiten) y
 * opcionalmente PAGOS_TEST_DB_URL / PAGOS_TEST_DB_USER.
 * Todos los datos son ficticios; las claves RSA se generan en memoria por ejecución.
 */
final class QaBase {
    static final String TOKEN_IN = "qa-token-pedidos-a-pagos";
    static final String TOKEN_OUT = "qa-token-pagos-a-pedidos";
    static final String DB_URL = System.getenv().getOrDefault("PAGOS_TEST_DB_URL", "jdbc:postgresql://localhost:55437/postgres");
    static final String DB_USER = System.getenv().getOrDefault("PAGOS_TEST_DB_USER", "postgres");
    static final String DB_PASSWORD = System.getenv().getOrDefault("PAGOS_TEST_DB_PASSWORD", "");

    static final KeyPair SIGNER = rsa();
    static final KeyPair OTHER_SIGNER = rsa();
    /** pedido -> propietario, y estado forzado del stub de Pedidos. */
    static final Map<UUID, UUID> OWNERS = new ConcurrentHashMap<>();
    static volatile int pedidosStatus = 200;
    static final HttpServer PEDIDOS;
    static final Path PEM;
    private static final HttpClient CLIENT = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();

    static {
        try {
            Path dir = Path.of("target", "qa-keys");
            Files.createDirectories(dir);
            PEM = dir.resolve("public.pem");
            Files.writeString(PEM, "-----BEGIN PUBLIC KEY-----\n"
                + Base64.getEncoder().encodeToString(SIGNER.getPublic().getEncoded()) + "\n-----END PUBLIC KEY-----\n");
            PEDIDOS = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            PEDIDOS.createContext("/api/pedidos/", exchange -> {
                String id = exchange.getRequestURI().getPath().substring("/api/pedidos/".length());
                String sent = exchange.getRequestHeaders().getFirst("X-Service-Token");
                int code = pedidosStatus;
                String body;
                UUID owner = null;
                try { owner = OWNERS.get(UUID.fromString(id)); } catch (IllegalArgumentException ignored) { }
                if (!TOKEN_OUT.equals(sent)) { code = 401; body = "{\"success\":false,\"message\":\"x\",\"errors\":{}}"; }
                else if (code == 200 && owner == null) { code = 404; body = "{\"success\":false,\"message\":\"x\",\"errors\":{}}"; }
                else if (code == 200) { body = "{\"success\":true,\"message\":\"OK\",\"data\":{\"id\":\"" + id + "\",\"usuario_id\":\"" + owner + "\"}}"; }
                else { body = "{\"success\":false,\"message\":\"x\",\"errors\":{}}"; }
                byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(code, bytes.length);
                try (var out = exchange.getResponseBody()) { out.write(bytes); }
            });
            PEDIDOS.start();
        } catch (IOException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    private QaBase() { }

    static void requireDb() {
        Assumptions.assumeTrue(!DB_PASSWORD.isBlank(), "PAGOS_TEST_DB_PASSWORD no definida: se omite la suite QA con PostgreSQL");
    }

    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", () -> DB_URL);
        registry.add("spring.datasource.username", () -> DB_USER);
        registry.add("spring.datasource.password", () -> DB_PASSWORD);
        registry.add("pagos.jwt-public-key-path", () -> PEM.toAbsolutePath().toString());
        registry.add("pagos.pedidos-service-token-in", () -> TOKEN_IN);
        registry.add("pagos.pedidos-service-token-out", () -> TOKEN_OUT);
        registry.add("pagos.pedidos-url", () -> "http://127.0.0.1:" + PEDIDOS.getAddress().getPort());
    }

    static KeyPair rsa() {
        try {
            var g = KeyPairGenerator.getInstance("RSA");
            g.initialize(2048);
            return g.generateKeyPair();
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    record Resp(int status, String body, java.net.http.HttpHeaders headers) { }

    static Resp call(int port, String method, String path, Map<String, String> headers, String body) {
        try {
            var b = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path)).timeout(Duration.ofSeconds(15));
            headers.forEach(b::header);
            b.method(method, body == null ? HttpRequest.BodyPublishers.noBody()
                : HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
            var r = CLIENT.send(b.build(), HttpResponse.BodyHandlers.ofString());
            return new Resp(r.statusCode(), r.body(), r.headers());
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    static Map<String, String> pedidosHeaders(UUID key) {
        var h = new LinkedHashMap<String, String>();
        h.put("X-Service-Token", TOKEN_IN);
        h.put("Content-Type", "application/json");
        if (key != null) h.put("Idempotency-Key", key.toString());
        return h;
    }

    static String payload(UUID pedido, String monto, String metodo) {
        return "{\"pedido_id\":\"" + pedido + "\",\"monto\":\"" + monto + "\",\"metodo_pago\":\"" + metodo + "\"}";
    }

    static UUID uuid4() { return UUID.randomUUID(); }

    /** JWT RS256 firmado con la clave indicada; claims ajustables mediante el builder. */
    static String jwt(KeyPair key, JWTClaimsSet claims) {
        try {
            var jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.RS256), claims);
            jwt.sign(new RSASSASigner((RSAPrivateKey) key.getPrivate()));
            return jwt.serialize();
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    static JWTClaimsSet.Builder claims(UUID sub, String role) {
        Instant now = Instant.now();
        return new JWTClaimsSet.Builder().issuer("api-usuarios").audience("tienda-microservicios")
            .subject(sub.toString()).claim("role", role)
            .issueTime(Date.from(now.minusSeconds(10))).expirationTime(Date.from(now.plusSeconds(1800)));
    }

    static String validJwt(UUID sub, String role) { return jwt(SIGNER, claims(sub, role).build()); }

    static Map<String, String> bearer(String token) { return Map.of("Authorization", "Bearer " + token); }
}
