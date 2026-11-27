package tienda.pagos.qa;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.PlainJWT;
import com.nimbusds.jwt.SignedJWT;
import java.time.Instant;
import java.util.Base64;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import static org.junit.jupiter.api.Assertions.*;
import static tienda.pagos.qa.QaBase.*;

/** Ataques de entrada, autenticacion, titularidad e inyeccion SQL contra el servicio real + PostgreSQL. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ApiHostilTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry registry) { QaBase.properties(registry); }

    @BeforeAll
    static void requireDatabase() { QaBase.requireDb(); }

    @BeforeEach
    void clean() { jdbc.update("DELETE FROM pagos"); OWNERS.clear(); pedidosStatus = 200; }

    private Resp post(Map<String, String> headers, String body) { return call(port, "POST", "/api/pagos/procesar", headers, body); }
    private Resp get(String path, Map<String, String> headers) { return call(port, "GET", path, headers, null); }
    private static String ok(UUID pedido) { return payload(pedido, "899.99", "tarjeta_simulada"); }
    private static void assertEnvelope(Resp r, int status) throws Exception {
        assertEquals(status, r.status(), r.body());
        var node = JSON.readTree(r.body());
        assertFalse(node.path("success").asBoolean(true), r.body());
        assertTrue(node.has("message") && node.path("errors").isObject(), "sobre de error del contrato: " + r.body());
        assertFalse(r.body().contains("Exception") || r.body().contains("at tienda."), "sin trazas: " + r.body());
    }
    private long count() { return jdbc.queryForObject("SELECT count(*) FROM pagos", Long.class); }

    // ---------- entrada ----------
    @Test void happyPathMatchesContract() throws Exception {
        var pedido = uuid4();
        var r = post(pedidosHeaders(uuid4()), ok(pedido));
        assertEquals(201, r.status(), r.body());
        var data = JSON.readTree(r.body()).path("data");
        assertEquals("899.99", data.path("monto").asText());
        assertEquals("aprobado", data.path("estado").asText());
        assertEquals(pedido.toString(), data.path("pedido_id").asText());
        assertDoesNotThrow(() -> Instant.parse(data.path("creado_en").asText()));
    }

    @ParameterizedTest @ValueSource(strings = {"{", "{\"pedido_id\":", "no es json", "", "\u0000", "{'a':1}"})
    void malformedJsonIs400(String body) throws Exception {
        assertEnvelope(post(pedidosHeaders(uuid4()), body), 400);
        assertEquals(0, count());
    }

    @Test void duplicateJsonKeysAreRejected() throws Exception {
        var p = uuid4();
        String body = "{\"pedido_id\":\"" + p + "\",\"monto\":\"1.00\",\"monto\":\"999.00\",\"metodo_pago\":\"tarjeta_simulada\"}";
        assertEnvelope(post(pedidosHeaders(uuid4()), body), 400);
        assertEquals(0, count());
    }

    @Test void trailingGarbageAfterJsonIsRejected() throws Exception {
        assertEnvelope(post(pedidosHeaders(uuid4()), ok(uuid4()) + "{\"x\":1}"), 400);
        assertEnvelope(post(pedidosHeaders(uuid4()), ok(uuid4()) + " basura"), 400);
        assertEquals(0, count());
    }

    @ParameterizedTest @ValueSource(strings = {"null", "[]", "[1,2,3]", "\"texto\"", "123", "{}", "true"})
    void wrongShapeIs422(String body) throws Exception {
        assertEnvelope(post(pedidosHeaders(uuid4()), body), 422);
    }

    @Test void extraAndMissingFieldsAre422() throws Exception {
        var p = uuid4();
        assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + p + "\",\"monto\":\"1.00\",\"metodo_pago\":\"tarjeta_simulada\",\"usuario_id\":\"" + p + "\"}"), 422);
        assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + p + "\",\"monto\":\"1.00\"}"), 422);
        assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + p + "\",\"monto\":\"1.00\",\"metodo_pago\":null}"), 422);
        assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + p + "\",\"monto\":\"1.00\",\"x\":\"tarjeta_simulada\"}"), 422);
        assertEquals(0, count());
    }

    @ParameterizedTest @ValueSource(strings = {"10", "10.5", "10.555", "-5.00", "0.00", "00.00", "1e3", "1E+3", " 10.00", "10.00 ", "10.00\\n",
        "12345678901.00", ".50", "10,00", "NaN", "Infinity", "0x10", "\\uFF11\\uFF10.\\uFF10\\uFF10", "+5.00", "1_0.00", "", "null"})
    void invalidAmountsAre422(String monto) throws Exception {
        var p = uuid4();
        // si el valor es numerico JSON (no cadena) tambien debe rechazarse
        String asString = "{\"pedido_id\":\"" + p + "\",\"monto\":\"" + monto + "\",\"metodo_pago\":\"tarjeta_simulada\"}";
        assertEnvelope(post(pedidosHeaders(uuid4()), asString), 422);
        assertEquals(0, count());
    }

    @Test void numericAndNonStringTypesAre422() throws Exception {
        var p = uuid4();
        for (String monto : List.of("12.75", "12", "true", "[\"1.00\"]", "{\"a\":1}", "1e2")) {
            assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + p + "\",\"monto\":" + monto + ",\"metodo_pago\":\"tarjeta_simulada\"}"), 422);
        }
        assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":123,\"monto\":\"1.00\",\"metodo_pago\":\"tarjeta_simulada\"}"), 422);
        assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + p + "\",\"monto\":\"1.00\",\"metodo_pago\":5}"), 422);
        assertEquals(0, count());
    }

    @ParameterizedTest @ValueSource(strings = {"00000000-0000-0000-0000-000000000000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "123e4567-e89b-12d3-a456-426614174000", "123e4567-e89b-42d3-c456-426614174000", "123e4567e89b42d3a456426614174000",
        "{123e4567-e89b-42d3-a456-426614174000}", "123e4567-e89b-42d3-a456-426614174000 ", "g23e4567-e89b-42d3-a456-426614174000", "abc"})
    void nonV4PedidoIdIs422(String id) throws Exception {
        assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + id + "\",\"monto\":\"1.00\",\"metodo_pago\":\"tarjeta_simulada\"}"), 422);
        assertEquals(0, count());
    }

    @ParameterizedTest @ValueSource(strings = {"", "abc", "00000000-0000-0000-0000-000000000000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8", "'; DROP TABLE pagos;--"})
    void badIdempotencyKeyIs422(String key) throws Exception {
        var h = pedidosHeaders(null);
        h.put("Idempotency-Key", key);
        assertEnvelope(post(h, ok(uuid4())), 422);
        assertEnvelope(post(pedidosHeaders(null), ok(uuid4())), 422);
        assertEquals(0, count());
    }

    @Test void invalidMetodoIs422() throws Exception {
        for (String m : List.of("efectivo", "TARJETA_SIMULADA", "tarjeta_simulada ", "", "tarjeta_simulada' OR '1'='1")) {
            assertEnvelope(post(pedidosHeaders(uuid4()), payload(uuid4(), "1.00", m)), 422);
        }
        assertEquals(0, count());
    }

    @Test void hugeBodiesAreRejectedNotProcessed() throws Exception {
        var p = uuid4();
        String padding = "a".repeat(2_000_000);
        String huge = "{\"pedido_id\":\"" + p + "\",\"monto\":\"1.00\",\"metodo_pago\":\"tarjeta_simulada\",\"x\":\"" + padding + "\"}";
        // Cambio (decision del equipo): cuerpo > MAX_JSON_BYTES (262144) => 413 en vez de 400 (limite antes 4096).
        assertEnvelope(post(pedidosHeaders(uuid4()), huge), 413);
        // 100000 bytes ya caben en el limite nuevo: se parsea y la profundidad excesiva sigue siendo 400.
        String deep = "[".repeat(100_000);
        assertEnvelope(post(pedidosHeaders(uuid4()), deep), 400);
        assertEquals(0, count());
    }

    @Test void hugeBodyWithoutCredentialsIs401NotReadOrParsed() throws Exception {
        var r = post(Map.of("Content-Type", "application/json"), "x".repeat(2_000_000));
        assertEnvelope(r, 401);
    }

    @Test void wrongContentTypeAndMethodsUseErrorEnvelope() throws Exception {
        var h = pedidosHeaders(uuid4());
        h.put("Content-Type", "text/plain");
        assertEnvelope(post(h, ok(uuid4())), 400);
        h.remove("Content-Type");
        assertEnvelope(post(h, ok(uuid4())), 400);
        assertEnvelope(call(port, "PUT", "/api/pagos/procesar", pedidosHeaders(uuid4()), ok(uuid4())), 405);
        assertEnvelope(call(port, "DELETE", "/api/pagos/pedido/" + uuid4(), pedidosHeaders(null), null), 405);
        assertEnvelope(call(port, "GET", "/api/pagos/no-existe", pedidosHeaders(null), null), 404);
        assertEnvelope(call(port, "POST", "/health", Map.of(), "{}"), 405);
        assertEquals(0, count());
    }

    @Test void malformedJsonWithoutCredentialsIs401() throws Exception {
        assertEnvelope(post(Map.of("Content-Type", "application/json"), "{malformado"), 401);
        assertEnvelope(post(Map.of("Content-Type", "application/json", "X-Service-Token", "mal"), ""), 401);
    }

    // ---------- token de servicio ----------
    @Test void serviceTokenMissingWrongOrFromOtherPairIs401() throws Exception {
        var body = ok(uuid4());
        for (String token : new String[]{null, "", " ", TOKEN_OUT, TOKEN_IN.toUpperCase(), TOKEN_IN + TOKEN_IN, TOKEN_IN.substring(1)}) {
            var h = pedidosHeaders(uuid4());
            h.remove("X-Service-Token");
            if (token != null) h.put("X-Service-Token", token);
            assertEnvelope(post(h, body), 401);
        }
        var q = call(port, "POST", "/api/pagos/procesar?X-Service-Token=" + TOKEN_IN, Map.of("Content-Type", "application/json", "Idempotency-Key", uuid4().toString()), body);
        assertEnvelope(q, 401);
        assertEquals(0, count());
    }

    @Test void userJwtCannotProcessPayments() throws Exception {
        for (String role : List.of("cliente", "admin")) {
            var h = pedidosHeaders(uuid4());
            h.remove("X-Service-Token");
            h.putAll(bearer(validJwt(uuid4(), role)));
            assertEnvelope(post(h, ok(uuid4())), 403);
        }
        assertEquals(0, count());
    }

    // ---------- JWT ----------
    private Resp receiptWith(String authorization, UUID pedido) {
        return get("/api/pagos/pedido/" + pedido, authorization == null ? Map.of() : Map.of("Authorization", authorization));
    }

    private UUID paidOrderOwnedBy(UUID owner) {
        var pedido = uuid4();
        OWNERS.put(pedido, owner);
        assertEquals(201, post(pedidosHeaders(uuid4()), ok(pedido)).status());
        return pedido;
    }

    @Test void tamperedMalformedAndUnsignedJwtsAre401() throws Exception {
        var user = uuid4();
        var pedido = paidOrderOwnedBy(user);
        String good = validJwt(user, "cliente");
        assertEquals(200, receiptWith("Bearer " + good, pedido).status());

        String[] parts = good.split("\\.");
        String adminPayload = Base64.getUrlEncoder().withoutPadding().encodeToString(
            ("{\"iss\":\"api-usuarios\",\"aud\":\"tienda-microservicios\",\"sub\":\"" + user + "\",\"role\":\"admin\",\"iat\":" + Instant.now().minusSeconds(5).getEpochSecond()
                + ",\"exp\":" + Instant.now().plusSeconds(600).getEpochSecond() + "}").getBytes());
        String tampered = parts[0] + "." + adminPayload + "." + parts[2];
        String noSig = parts[0] + "." + parts[1] + ".";
        String noneHeader = Base64.getUrlEncoder().withoutPadding().encodeToString("{\"alg\":\"none\",\"typ\":\"JWT\"}".getBytes());
        String algNone = noneHeader + "." + parts[1] + ".";
        String plain = new PlainJWT(claims(user, "cliente").build()).serialize();
        // HS256 con la clave publica como secreto (confusion de algoritmo)
        byte[] secret = SIGNER.getPublic().getEncoded();
        var hs = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256), claims(user, "cliente").build());
        hs.sign(new MACSigner(secret));
        for (String bad : new String[]{tampered, noSig, algNone, plain, hs.serialize(), good + "x", parts[0] + "." + parts[1], "a.b.c", "x", "",
            jwt(OTHER_SIGNER, claims(user, "cliente").build()), good.replace('.', '!')}) {
            var r = receiptWith("Bearer " + bad, pedido);
            assertEquals(401, r.status(), bad + " -> " + r.body());
        }
        for (String badHeader : new String[]{null, "", "Bearer", "Bearer ", "Basic abc", good, "Token " + good}) {
            assertEquals(401, receiptWith(badHeader, pedido).status(), String.valueOf(badHeader));
        }
    }

    @Test void claimViolationsAre401() throws Exception {
        var user = uuid4();
        var pedido = paidOrderOwnedBy(user);
        Instant now = Instant.now();
        var cases = new java.util.LinkedHashMap<String, JWTClaimsSet>();
        cases.put("expirado", claims(user, "cliente").expirationTime(Date.from(now.minusSeconds(120))).issueTime(Date.from(now.minusSeconds(3000))).build());
        cases.put("iat futuro", claims(user, "cliente").issueTime(Date.from(now.plusSeconds(600))).expirationTime(Date.from(now.plusSeconds(1200))).build());
        cases.put("nbf futuro", claims(user, "cliente").notBeforeTime(Date.from(now.plusSeconds(600))).build());
        cases.put("vida >1h", claims(user, "cliente").issueTime(Date.from(now.minusSeconds(10))).expirationTime(Date.from(now.plusSeconds(7200))).build());
        cases.put("sin exp", new JWTClaimsSet.Builder().issuer("api-usuarios").audience("tienda-microservicios").subject(user.toString()).claim("role", "cliente").issueTime(Date.from(now)).build());
        cases.put("sin iat", new JWTClaimsSet.Builder().issuer("api-usuarios").audience("tienda-microservicios").subject(user.toString()).claim("role", "cliente").expirationTime(Date.from(now.plusSeconds(100))).build());
        cases.put("aud erronea", claims(user, "cliente").audience("otra").build());
        cases.put("sin aud", new JWTClaimsSet.Builder().issuer("api-usuarios").subject(user.toString()).claim("role", "cliente").issueTime(Date.from(now)).expirationTime(Date.from(now.plusSeconds(100))).build());
        cases.put("iss erroneo", claims(user, "cliente").issuer("evil").build());
        cases.put("sin iss", new JWTClaimsSet.Builder().audience("tienda-microservicios").subject(user.toString()).claim("role", "cliente").issueTime(Date.from(now)).expirationTime(Date.from(now.plusSeconds(100))).build());
        cases.put("sub no uuid", claims(user, "cliente").subject("usuario-1").build());
        cases.put("sub uuid v1", claims(user, "cliente").subject("6ba7b810-9dad-11d1-80b4-00c04fd430c8").build());
        cases.put("sin sub", new JWTClaimsSet.Builder().issuer("api-usuarios").audience("tienda-microservicios").claim("role", "cliente").issueTime(Date.from(now)).expirationTime(Date.from(now.plusSeconds(100))).build());
        cases.put("rol invalido", claims(user, "root").build());
        cases.put("rol ADMIN", claims(user, "ADMIN").build());
        cases.put("sin rol", new JWTClaimsSet.Builder().issuer("api-usuarios").audience("tienda-microservicios").subject(user.toString()).issueTime(Date.from(now)).expirationTime(Date.from(now.plusSeconds(100))).build());
        cases.put("rol no string", claims(user, "cliente").claim("role", List.of("admin")).build());
        cases.forEach((name, c) -> {
            var r = receiptWith("Bearer " + jwt(SIGNER, c), pedido);
            assertEquals(401, r.status(), name + " -> " + r.body());
        });
    }

    // ---------- titularidad ----------
    @Test void ownershipIsEnforced() throws Exception {
        var a = uuid4();
        var b = uuid4();
        var pedidoDeB = paidOrderOwnedBy(b);
        assertEnvelope(receiptWith("Bearer " + validJwt(a, "cliente"), pedidoDeB), 403);
        assertEquals(200, receiptWith("Bearer " + validJwt(b, "cliente"), pedidoDeB).status());
        assertEquals(200, receiptWith("Bearer " + validJwt(a, "admin"), pedidoDeB).status());
        assertEquals(200, get("/api/pagos/pedido/" + pedidoDeB, Map.of("X-Service-Token", TOKEN_IN)).status());
        // el token de salida (Pagos->Pedidos) no es credencial de entrada
        assertEnvelope(get("/api/pagos/pedido/" + pedidoDeB, Map.of("X-Service-Token", TOKEN_OUT)), 401);
        assertEnvelope(get("/api/pagos/pedido/" + pedidoDeB, Map.of()), 401);
        // pedido inexistente para Pedidos: 404; no filtra si el pago existe
        assertEnvelope(receiptWith("Bearer " + validJwt(a, "cliente"), uuid4()), 404);
        // admin y pedido sin pago: 404
        assertEnvelope(receiptWith("Bearer " + validJwt(a, "admin"), uuid4()), 404);
    }

    @Test void ordersServiceOutageOrBadAnswerIs503NeverAllow() throws Exception {
        var a = uuid4();
        var pedido = paidOrderOwnedBy(a);
        for (int code : new int[]{500, 502, 503, 302, 401}) {
            pedidosStatus = code;
            var r = receiptWith("Bearer " + validJwt(a, "cliente"), pedido);
            assertTrue(r.status() == 503, code + " -> " + r.status() + " " + r.body());
        }
    }

    // ---------- inyeccion SQL ----------
    @Test void sqlInjectionAttemptsAreInertAndTableSurvives() throws Exception {
        String[] evil = {"'; DROP TABLE pagos;--", "1' OR '1'='1", "\" OR \"\"=\"", "%27%3B%20DROP%20TABLE%20pagos%3B--", "1; SELECT pg_sleep(5)"};
        for (String e : evil) {
            assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + e.replace("\"", "\\\"") + "\",\"monto\":\"1.00\",\"metodo_pago\":\"tarjeta_simulada\"}"), 422);
            assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + uuid4() + "\",\"monto\":\"" + e.replace("\"", "\\\"") + "\",\"metodo_pago\":\"tarjeta_simulada\"}"), 422);
            assertEnvelope(post(pedidosHeaders(uuid4()), "{\"pedido_id\":\"" + uuid4() + "\",\"monto\":\"1.00\",\"metodo_pago\":\"" + e.replace("\"", "\\\"") + "\"}"), 422);
            var enc = java.net.URLEncoder.encode(e, java.nio.charset.StandardCharsets.UTF_8).replace("+", "%20");
            long t0 = System.nanoTime();
            var r = get("/api/pagos/pedido/" + enc, Map.of("X-Service-Token", TOKEN_IN));
            assertTrue(r.status() == 422 || r.status() == 404 || r.status() == 400, e + " -> " + r.status());
            assertTrue((System.nanoTime() - t0) < 3_000_000_000L);
        }
        assertEquals(0, count());
        assertEquals(1L, jdbc.queryForObject("SELECT count(*) FROM information_schema.tables WHERE table_name='pagos'", Long.class));
    }

    // ---------- idempotencia secuencial ----------
    @Test void idempotencySemantics() throws Exception {
        var pedido = uuid4();
        var key = uuid4();
        var first = post(pedidosHeaders(key), ok(pedido));
        var replay = post(pedidosHeaders(key), ok(pedido));
        assertEquals(201, first.status());
        assertEquals(201, replay.status());
        assertEquals(JSON.readTree(first.body()).path("data"), JSON.readTree(replay.body()).path("data"));
        // misma clave, distinto monto / metodo / pedido: 409
        assertEnvelope(post(pedidosHeaders(key), payload(pedido, "1.00", "tarjeta_simulada")), 409);
        assertEnvelope(post(pedidosHeaders(key), payload(pedido, "899.99", "transferencia_simulada")), 409);
        assertEnvelope(post(pedidosHeaders(key), ok(uuid4())), 409);
        // otra clave para el mismo pedido: 409 (aunque el payload sea identico)
        assertEnvelope(post(pedidosHeaders(uuid4()), ok(pedido)), 409);
        assertEquals(1, count());
        // el rechazo tambien es 201 y se persiste una vez
        var p2 = uuid4();
        var k2 = uuid4();
        var rej = post(pedidosHeaders(k2), payload(p2, "5.00", "transferencia_simulada"));
        assertEquals(201, rej.status());
        assertEquals("rechazado", JSON.readTree(rej.body()).path("data").path("estado").asText());
        assertEquals(JSON.readTree(rej.body()).path("data"), JSON.readTree(post(pedidosHeaders(k2), payload(p2, "5.00", "transferencia_simulada")).body()).path("data"));
        // UUID en mayusculas = mismo pedido, no duplica
        assertEnvelope(post(pedidosHeaders(uuid4()), payload(UUID.fromString(pedido.toString()), "899.99", "tarjeta_simulada").replace(pedido.toString(), pedido.toString().toUpperCase())), 409);
        assertEquals(2, count());
    }

    @Test void constraintsHoldAtDatabaseLevel() {
        var id = uuid4();
        assertThrows(Exception.class, () -> jdbc.update("INSERT INTO pagos(id,pedido_id,idempotency_key,request_hash,monto,metodo_pago,estado) VALUES (?,?,?,?,?,?,?)",
            id, uuid4(), uuid4(), "h".repeat(64), new java.math.BigDecimal("0.00"), "tarjeta_simulada", "aprobado"));
        assertThrows(Exception.class, () -> jdbc.update("INSERT INTO pagos(id,pedido_id,idempotency_key,request_hash,monto,metodo_pago,estado) VALUES (?,?,?,?,?,?,?)",
            id, uuid4(), uuid4(), "h".repeat(64), new java.math.BigDecimal("1.00"), "bitcoin", "aprobado"));
        assertThrows(Exception.class, () -> jdbc.update("INSERT INTO pagos(id,pedido_id,idempotency_key,request_hash,monto,metodo_pago,estado) VALUES (?,?,?,?,?,?,?)",
            id, uuid4(), uuid4(), "h".repeat(64), new java.math.BigDecimal("1.00"), "tarjeta_simulada", "pendiente"));
    }
}
