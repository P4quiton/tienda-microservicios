package tienda.pagos.qa;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.UUID;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import static org.junit.jupiter.api.Assertions.*;
import static tienda.pagos.qa.QaBase.*;

/** Contrato 1.1.0: resultado y clave persistidos juntos, unicidad por pedido, 409 por payload incompatible, sin repetir efecto. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class Contrato110Test {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry registry) { QaBase.properties(registry); }
    @BeforeAll static void requireDatabase() { QaBase.requireDb(); }
    @BeforeEach void clean() { jdbc.update("DELETE FROM pagos"); }

    private Resp post(UUID key, String body) {
        return call(port, "POST", "/api/pagos/procesar", pedidosHeaders(key), body);
    }

    @Test void resultAndKeyAreStoredInTheSameRowUniquePerPedido() {
        var pedido = uuid4();
        var key = uuid4();
        assertEquals(201, post(key, payload(pedido, "50.00", "transferencia_simulada")).status());
        var row = jdbc.queryForMap("SELECT idempotency_key, estado, request_hash FROM pagos WHERE pedido_id = ?", pedido);
        assertEquals(key, row.get("idempotency_key"));
        assertEquals("rechazado", row.get("estado"));
        assertNotNull(row.get("request_hash"));
        assertThrows(Exception.class, () -> jdbc.update(
            "INSERT INTO pagos (id, pedido_id, idempotency_key, request_hash, monto, metodo_pago, estado) VALUES (?,?,?,?,1,'tarjeta_simulada','aprobado')",
            uuid4(), pedido, uuid4(), "0".repeat(64)));
    }

    @Test void incompatiblePayloadWithAnotherKeyIs409AndKeepsOriginalResult() {
        var pedido = uuid4();
        var first = post(uuid4(), payload(pedido, "100.00", "tarjeta_simulada"));
        assertEquals(201, first.status());
        for (var other : new String[] {payload(pedido, "100.01", "tarjeta_simulada"), payload(pedido, "100.00", "transferencia_simulada")}) {
            assertEquals(409, post(uuid4(), other).status());
        }
        var row = jdbc.queryForMap("SELECT monto, estado FROM pagos WHERE pedido_id = ?", pedido);
        assertEquals("aprobado", row.get("estado"));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM pagos", Integer.class));
    }

    @Test void clientTimeoutThenRetryWithSameKeyReturnsOriginalWithoutSecondEffect() throws Exception {
        var pedido = uuid4();
        var key = uuid4();
        var body = payload(pedido, "75.00", "tarjeta_simulada");
        // Cliente con timeout minimo: abandona la respuesta (el servidor puede haber confirmado el pago).
        var impatient = HttpClient.newHttpClient();
        var req = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/pagos/procesar"))
            .timeout(Duration.ofMillis(1)).header("X-Service-Token", TOKEN_IN).header("Content-Type", "application/json")
            .header("Idempotency-Key", key.toString()).POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8)).build();
        try { impatient.send(req, java.net.http.HttpResponse.BodyHandlers.ofString()); } catch (Exception expectedTimeout) { }
        Thread.sleep(500);
        var retry1 = post(key, body);
        var retry2 = post(key, body);
        assertEquals(201, retry1.status());
        assertEquals(retry1.body(), retry2.body());
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM pagos WHERE pedido_id = ?", Integer.class, pedido));
        var get = call(port, "GET", "/api/pagos/pedido/" + pedido, pedidosHeaders(null), null);
        assertEquals(200, get.status());
        assertTrue(get.body().contains(retry1.body().replaceAll(".*\"id\":\"([^\"]+)\".*", "$1")));
    }

    @Test void getWithoutPaymentIs404() {
        assertEquals(404, call(port, "GET", "/api/pagos/pedido/" + uuid4(), pedidosHeaders(null), null).status());
    }
}
