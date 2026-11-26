package tienda.pagos.qa;

import java.util.Map;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;

import static org.junit.jupiter.api.Assertions.*;
import static tienda.pagos.qa.QaBase.*;

/** BD caida desde el arranque: el proceso debe vivir (/health) y /ready debe informar 503. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
    "spring.datasource.url=jdbc:postgresql://127.0.0.1:1/inexistente",
    "spring.datasource.username=u", "spring.datasource.password=p",
    "pagos.pedidos-service-token-in=qa-token-pedidos-a-pagos", "pagos.pedidos-service-token-out=qa-token-pagos-a-pedidos",
    "pagos.pedidos-url=http://127.0.0.1:1"})
class ResilienciaTest {
    @LocalServerPort int port;

    @Test void applicationStartsAndHealthLivesWhileReadyAndPaymentsReport503() {
        var health = call(port, "GET", "/health", Map.of(), null);
        assertEquals(200, health.status());
        assertTrue(health.body().contains("\"status\":\"ok\""));
        var ready = call(port, "GET", "/ready", Map.of(), null);
        assertEquals(503, ready.status());
        assertTrue(ready.body().contains("unavailable"));
        var pay = call(port, "POST", "/api/pagos/procesar", pedidosHeaders(uuid4()), payload(uuid4(), "1.00", "tarjeta_simulada"));
        assertEquals(503, pay.status(), pay.body());
        assertFalse(pay.body().contains("jdbc") || pay.body().contains("Exception"), pay.body());
        var read = call(port, "GET", "/api/pagos/pedido/" + uuid4(), Map.of("X-Service-Token", TOKEN_IN), null);
        assertEquals(503, read.status(), read.body());
    }

    /** Migraciones aplicadas dos veces sobre un esquema vacio: segunda ejecucion es no-op. */
    @Test void migrationsAreIdempotent() {
        QaBase.requireDb();
        var flyway = Flyway.configure().dataSource(DB_URL, DB_USER, DB_PASSWORD).schemas("qa_migracion")
            .locations("classpath:db/migration").cleanDisabled(false).load();
        flyway.clean();
        var first = flyway.migrate();
        var second = Flyway.configure().dataSource(DB_URL, DB_USER, DB_PASSWORD).schemas("qa_migracion")
            .locations("classpath:db/migration").load().migrate();
        assertEquals(1, first.migrationsExecuted);
        assertEquals(0, second.migrationsExecuted);
        assertDoesNotThrow(() -> Flyway.configure().dataSource(DB_URL, DB_USER, DB_PASSWORD).schemas("qa_migracion")
            .locations("classpath:db/migration").load().validate());
        flyway.clean();
    }
}
