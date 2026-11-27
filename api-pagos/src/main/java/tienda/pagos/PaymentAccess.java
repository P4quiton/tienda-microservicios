package tienda.pagos;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

@Component
class PaymentAccess {
    private final byte[] inboundToken;
    private final String outboundToken;
    private final RestClient pedidos;
    private final NimbusJwtDecoder decoder;

    PaymentAccess(
        @Value("${pagos.pedidos-service-token-in}") String inboundToken,
        @Value("${pagos.pedidos-service-token-out}") String outboundToken,
        @Value("${pagos.pedidos-url}") String pedidosUrl,
        @Value("${pagos.jwt-public-key-path}") String keyPath
    ) {
        if (!inboundToken.isBlank() && inboundToken.equals(outboundToken)) {
            throw new IllegalStateException("Los tokens de servicio de entrada y salida deben ser distintos (uno por par)");
        }
        this.inboundToken = inboundToken.getBytes(StandardCharsets.UTF_8);
        this.outboundToken = outboundToken;
        var factory = new SimpleClientHttpRequestFactory() {
            @Override
            protected void prepareConnection(HttpURLConnection connection, String method) throws IOException {
                super.prepareConnection(connection, method);
                connection.setInstanceFollowRedirects(false);
            }
        };
        factory.setConnectTimeout(Duration.ofSeconds(2));
        factory.setReadTimeout(Duration.ofSeconds(2));
        factory.setProxy(Proxy.NO_PROXY);
        this.pedidos = RestClient.builder().baseUrl(pedidosUrl).requestFactory(factory).build();
        this.decoder = keyPath.isBlank() ? null : decoder(keyPath);
    }

    boolean isPedidos(String token) {
        return token != null && inboundToken.length > 0
            && MessageDigest.isEqual(inboundToken, token.getBytes(StandardCharsets.UTF_8));
    }

    void requirePedidos(String token, String authorization) {
        if (!isPedidos(token)) {
            if (token == null && authorization != null) {
                authenticate(authorization);
                throw new ApiError(403, "Operación reservada a Pedidos");
            }
            throw invalidCredential();
        }
    }

    Identity authenticate(String authorization) {
        if (decoder == null || authorization == null || !authorization.startsWith("Bearer ")) {
            throw invalidCredential();
        }

        try {
            var jwt = decoder.decode(authorization.substring(7));
            var issuedAt = jwt.getIssuedAt();
            var expiresAt = jwt.getExpiresAt();
            var audience = jwt.getAudience();
            if (audience == null || !audience.contains("tienda-microservicios")
                || issuedAt == null || expiresAt == null
                || issuedAt.isAfter(Instant.now()) || !expiresAt.isAfter(Instant.now())
                || !expiresAt.isAfter(issuedAt) || Duration.between(issuedAt, expiresAt).compareTo(Duration.ofHours(1)) > 0) {
                throw invalidCredential();
            }
            var role = jwt.getClaimAsString("role");
            if (!"cliente".equals(role) && !"admin".equals(role)) {
                throw invalidCredential();
            }
            return new Identity(PagoRequest.uuid(jwt.getSubject(), "sub"), role);
        } catch (JwtException | ApiError | IllegalArgumentException exception) {
            throw invalidCredential();
        }
    }

    void requireOwner(UUID pedidoId, Identity identity) {
        if ("admin".equals(identity.role())) {
            return;
        }
        if (outboundToken.isBlank()) {
            throw new ApiError(503, "Pedidos no disponible");
        }

        try {
            JsonNode order = pedidos.get().uri("/api/pedidos/{id}", pedidoId)
                .header("X-Service-Token", outboundToken).retrieve()
                .onStatus(status -> status.is3xxRedirection(), (request, response) -> {
                    throw new ApiError(503, "Respuesta de Pedidos no disponible");
                })
                .body(JsonNode.class);
            if (order == null || !order.path("success").asBoolean()) {
                throw new ApiError(503, "Respuesta de Pedidos no disponible");
            }
            String owner = order.path("data").path("usuario_id").textValue();
            UUID propietario;
            try {
                propietario = PagoRequest.uuid(owner, "usuario_id");
            } catch (ApiError invalidOwner) {
                throw new ApiError(503, "Respuesta de Pedidos no disponible");
            }
            if (!identity.id().equals(propietario)) {
                throw new ApiError(403, "Permiso insuficiente");
            }
        } catch (RestClientResponseException exception) {
            if (exception.getStatusCode().value() == 404) {
                throw new ApiError(404, "Pedido no encontrado");
            }
            throw new ApiError(503, "Pedidos no disponible");
        } catch (RestClientException exception) {
            throw new ApiError(503, "Pedidos no disponible");
        }
    }

    private static ApiError invalidCredential() {
        return new ApiError(401, "Credencial inválida");
    }

    private static NimbusJwtDecoder decoder(String keyPath) {
        try {
            String pem = Files.readString(Path.of(keyPath))
                .replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", "")
                .replaceAll("\\s+", "");
            var key = (RSAPublicKey) KeyFactory.getInstance("RSA")
                .generatePublic(new X509EncodedKeySpec(Base64.getDecoder().decode(pem)));
            var decoder = NimbusJwtDecoder.withPublicKey(key).signatureAlgorithm(SignatureAlgorithm.RS256).build();
            decoder.setJwtValidator(JwtValidators.createDefaultWithIssuer("api-usuarios"));
            return decoder;
        } catch (GeneralSecurityException | IOException | IllegalArgumentException exception) {
            throw new IllegalStateException("No se pudo cargar la clave pública RS256", exception);
        }
    }

    record Identity(UUID id, String role) {}
}
