package tienda.pagos;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.time.Instant;
import java.util.Base64;
import java.util.Date;
import java.util.UUID;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class PaymentAccessTest {
    @TempDir Path directory;
    private PaymentAccess access;
    private KeyPair signer;
    private final UUID customer = UUID.randomUUID();

    @BeforeEach
    void setUp() throws Exception {
        var generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        signer = generator.generateKeyPair();
        var pem = directory.resolve("public.pem");
        Files.writeString(pem, "-----BEGIN PUBLIC KEY-----\n"
            + Base64.getEncoder().encodeToString(signer.getPublic().getEncoded()) + "\n-----END PUBLIC KEY-----\n");
        access = new PaymentAccess("service-token-test", "", "http://localhost:8006", pem.toString());
    }

    @Test
    void verifiesCustomerIdentityAndBlocksPaymentProcessing() throws Exception {
        String bearer = token("tienda-microservicios", Instant.now().minusSeconds(10), "cliente");
        assertEquals(customer, access.authenticate(bearer).id());
        assertEquals(403, assertThrows(ApiError.class, () -> access.requirePedidos(null, bearer)).status);
    }

    @Test
    void rejectsWrongAudienceExpiredTokenAndInvalidRole() throws Exception {
        String wrongAudience = token("otra-api", Instant.now().minusSeconds(10), "cliente");
        String expired = token("tienda-microservicios", Instant.now().minusSeconds(3700), "cliente");
        String wrongRole = token("tienda-microservicios", Instant.now().minusSeconds(10), "operador");
        for (String bearer : new String[]{wrongAudience, expired, wrongRole}) {
            assertEquals(401, assertThrows(ApiError.class, () -> access.authenticate(bearer)).status);
        }
    }

    private String token(String audience, Instant issuedAt, String role) throws Exception {
        var claims = new JWTClaimsSet.Builder().issuer("api-usuarios").audience(audience)
            .subject(customer.toString()).claim("role", role).issueTime(Date.from(issuedAt))
            .expirationTime(Date.from(issuedAt.plusSeconds(3600))).build();
        var jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.RS256), claims);
        jwt.sign(new RSASSASigner((RSAPrivateKey) signer.getPrivate()));
        return "Bearer " + jwt.serialize();
    }
}
