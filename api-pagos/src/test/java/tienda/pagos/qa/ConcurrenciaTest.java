package tienda.pagos.qa;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.stream.Collectors;

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

/** Mismas claves/pedidos en paralelo: sin duplicados ni errores 5xx. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ConcurrenciaTest {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry registry) { QaBase.properties(registry); }
    @BeforeAll static void requireDatabase() { QaBase.requireDb(); }
    @BeforeEach void clean() { jdbc.update("DELETE FROM pagos"); }

    private List<Resp> parallel(int n, java.util.function.IntFunction<Resp> task) throws Exception {
        var pool = Executors.newFixedThreadPool(n);
        var ready = new CountDownLatch(n);
        var go = new CountDownLatch(1);
        var futures = new ArrayList<Future<Resp>>();
        for (int i = 0; i < n; i++) {
            int idx = i;
            futures.add(pool.submit(() -> { ready.countDown(); go.await(); return task.apply(idx); }));
        }
        ready.await();
        go.countDown();
        var out = new ArrayList<Resp>();
        for (var f : futures) out.add(f.get());
        pool.shutdown();
        return out;
    }

    private long count() { return jdbc.queryForObject("SELECT count(*) FROM pagos", Long.class); }

    @Test void sameKeySamePayloadInParallelYieldsOnePaymentAndIdenticalAnswers() throws Exception {
        var pedido = uuid4();
        var key = uuid4();
        var rs = parallel(40, i -> call(port, "POST", "/api/pagos/procesar", pedidosHeaders(key), payload(pedido, "100.00", "tarjeta_simulada")));
        assertTrue(rs.stream().allMatch(r -> r.status() == 201), rs.stream().map(r -> r.status() + r.body()).collect(Collectors.joining("\n")));
        var ids = rs.stream().map(r -> r.body().replaceAll(".*\"id\":\"([^\"]+)\".*", "$1")).distinct().toList();
        assertEquals(1, ids.size(), ids.toString());
        assertEquals(1, count());
    }

    @Test void differentKeysSamePedidoInParallelYieldExactlyOne201() throws Exception {
        var pedido = uuid4();
        var rs = parallel(40, i -> call(port, "POST", "/api/pagos/procesar", pedidosHeaders(uuid4()), payload(pedido, "100.00", "tarjeta_simulada")));
        long created = rs.stream().filter(r -> r.status() == 201).count();
        long conflicts = rs.stream().filter(r -> r.status() == 409).count();
        assertEquals(1, created, rs.stream().map(r -> String.valueOf(r.status())).collect(Collectors.joining(",")));
        assertEquals(39, conflicts);
        assertEquals(1, count());
    }

    @Test void sameKeyDifferentPayloadsInParallelNeverCreatesTwoAndOnlyOneWins() throws Exception {
        var key = uuid4();
        var rs = parallel(30, i -> call(port, "POST", "/api/pagos/procesar", pedidosHeaders(key), payload(uuid4(), (i + 1) + ".00", "tarjeta_simulada")));
        assertEquals(1, rs.stream().filter(r -> r.status() == 201).count(), rs.stream().map(r -> String.valueOf(r.status())).collect(Collectors.joining(",")));
        assertTrue(rs.stream().allMatch(r -> r.status() == 201 || r.status() == 409));
        assertEquals(1, count());
    }

    @Test void manyDistinctOrdersInParallelAllSucceedWithoutPoolStarvation() throws Exception {
        var rs = parallel(60, i -> call(port, "POST", "/api/pagos/procesar", pedidosHeaders(uuid4()), payload(uuid4(), "10.00", i % 2 == 0 ? "tarjeta_simulada" : "transferencia_simulada")));
        assertTrue(rs.stream().allMatch(r -> r.status() == 201), rs.stream().map(r -> String.valueOf(r.status())).collect(Collectors.joining(",")));
        assertEquals(60, count());
    }

    @Test void retryAfterLostResponseReturnsOriginalWithoutSecondCharge() throws Exception {
        var pedido = uuid4();
        var key = uuid4();
        var first = call(port, "POST", "/api/pagos/procesar", pedidosHeaders(key), payload(pedido, "77.10", "tarjeta_simulada"));
        for (int i = 0; i < 5; i++) {
            var again = call(port, "POST", "/api/pagos/procesar", pedidosHeaders(key), payload(pedido, "77.10", "tarjeta_simulada"));
            assertEquals(first.status(), again.status());
            assertEquals(first.body(), again.body());
        }
        assertEquals(1, count());
    }
}
