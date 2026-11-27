package tienda.pagos.qa;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import static org.junit.jupiter.api.Assertions.*;
import static tienda.pagos.qa.QaBase.*;

/**
 * Rate limiting con limites bajos (consulta 3, mutacion 2, interna 4 por minuto). Cada prueba usa una clave distinta
 * (sub propio) salvo las de servicio e IP, que solo se ejercitan en una prueba cada una; las ventanas son de 60 s.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class RateLimitTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry registry) {
        QaBase.properties(registry);
        registry.add("pagos.rate-limit.consulta-por-min", () -> "3");
        registry.add("pagos.rate-limit.mutacion-por-min", () -> "2");
        registry.add("pagos.rate-limit.interna-por-min", () -> "4");
    }

    @BeforeAll static void requireDatabase() { QaBase.requireDb(); }

    private Resp receipt(Map<String, String> headers) {
        return call(port, "GET", "/api/pagos/pedido/" + uuid4(), headers, null);
    }

    private static void assert429(Resp r) throws Exception {
        assertEquals(429, r.status(), r.body());
        long retry = Long.parseLong(r.headers().firstValue("Retry-After").orElseThrow());
        assertTrue(retry >= 1 && retry <= 60, "Retry-After=" + retry);
        var node = JSON.readTree(r.body());
        assertFalse(node.path("success").asBoolean(true), r.body());
        assertTrue(node.has("message") && node.path("errors").isObject(), "sobre de error del contrato: " + r.body());
    }

    @Test void consultasConJwtSeLimitanPorIdentidad() throws Exception {
        var a = bearer(validJwt(uuid4(), "admin"));
        var b = bearer(validJwt(uuid4(), "admin"));
        for (int i = 0; i < 3; i++) assertEquals(404, receipt(a).status());
        assert429(receipt(a));
        assertEquals(404, receipt(b).status(), "otra identidad no comparte el cupo");
    }

    @Test void mutacionesConJwtSeLimitanAparteDeLasConsultas() throws Exception {
        var sub = uuid4();
        var h = new java.util.LinkedHashMap<>(bearer(validJwt(sub, "cliente")));
        h.put("Content-Type", "application/json");
        h.put("Idempotency-Key", uuid4().toString());
        for (int i = 0; i < 2; i++) assertEquals(403, call(port, "POST", "/api/pagos/procesar", h, "{}").status());
        assert429(call(port, "POST", "/api/pagos/procesar", h, "{}"));
        assertEquals(404, receipt(bearer(validJwt(sub, "admin"))).status(), "consultas tienen su propio cupo");
    }

    @Test void operacionesInternasComparteCupoPorServicioYNoAfectaAUsuarios() throws Exception {
        long before = jdbc.queryForObject("SELECT count(*) FROM pagos", Long.class);
        for (int i = 0; i < 2; i++) {
            assertEquals(201, call(port, "POST", "/api/pagos/procesar", pedidosHeaders(uuid4()), payload(uuid4(), "10.00", "tarjeta_simulada")).status());
        }
        for (int i = 0; i < 2; i++) assertEquals(404, receipt(Map.of("X-Service-Token", TOKEN_IN)).status());
        assert429(receipt(Map.of("X-Service-Token", TOKEN_IN)));
        var rejected = call(port, "POST", "/api/pagos/procesar", pedidosHeaders(uuid4()), payload(uuid4(), "10.00", "tarjeta_simulada"));
        assert429(rejected);
        assertEquals(before + 2, jdbc.queryForObject("SELECT count(*) FROM pagos", Long.class), "un 429 no crea pagos");
        assertEquals(404, receipt(bearer(validJwt(uuid4(), "admin"))).status());
    }

    @Test void sinCredencialSigueSiendo401HastaAgotarElCupoPorIp() throws Exception {
        for (int i = 0; i < 3; i++) assertEquals(401, receipt(Map.of()).status());
        assert429(receipt(Map.of("Authorization", "Bearer basura")));
        for (int i = 0; i < 2; i++) {
            assertEquals(401, call(port, "POST", "/api/pagos/procesar", Map.of("Content-Type", "application/json"), "{}").status());
        }
        assert429(call(port, "POST", "/api/pagos/procesar", Map.of("Content-Type", "application/json"), "{}"));
    }

    @Test void healthYReadyEstanExentos() {
        for (int i = 0; i < 20; i++) {
            assertEquals(200, call(port, "GET", "/health", Map.of(), null).status());
            assertEquals(200, call(port, "GET", "/ready", Map.of(), null).status());
        }
    }
}
