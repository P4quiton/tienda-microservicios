package tienda.pagos.qa;

import java.util.UUID;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import static org.junit.jupiter.api.Assertions.*;
import static tienda.pagos.qa.QaBase.*;

/** MAX_JSON_BYTES configurable (aqui 400 bytes): exactamente el maximo se procesa, un byte mas => 413. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class TamanoJsonTest {
    private static final int MAX = 400;
    @LocalServerPort int port;

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry registry) {
        QaBase.properties(registry);
        registry.add("pagos.max-json-bytes", () -> String.valueOf(MAX));
    }

    @BeforeAll static void requireDatabase() { QaBase.requireDb(); }

    private static String padded(int totalBytes) {
        String base = payload(UUID.randomUUID(), "1.00", "tarjeta_simulada");
        String body = base.substring(0, base.length() - 1) + ",\"x\":\"" + "a".repeat(totalBytes - base.length() - 7) + "\"}";
        assertEquals(totalBytes, body.getBytes(java.nio.charset.StandardCharsets.UTF_8).length);
        return body;
    }

    @Test void enElLimiteSeLeeYUnByteMasEs413() {
        // Con el campo extra "x" el contrato rechaza por validacion (422): llega al parser, no al limite.
        assertEquals(422, call(port, "POST", "/api/pagos/procesar", pedidosHeaders(uuid4()), padded(MAX)).status());
        var over = call(port, "POST", "/api/pagos/procesar", pedidosHeaders(uuid4()), padded(MAX + 1));
        assertEquals(413, over.status(), over.body());
        assertTrue(over.body().contains("\"success\":false") && over.body().contains("\"errors\""), over.body());
    }

    @Test void sinCredencialSigueSiendo401() {
        assertEquals(401, call(port, "POST", "/api/pagos/procesar", java.util.Map.of("Content-Type", "application/json"), padded(MAX + 1)).status());
    }
}
