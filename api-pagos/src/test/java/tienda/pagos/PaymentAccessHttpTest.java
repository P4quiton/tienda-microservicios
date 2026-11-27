package tienda.pagos;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class PaymentAccessHttpTest {
    private final UUID order = UUID.randomUUID();
    private final UUID owner = UUID.randomUUID();
    private final AtomicReference<String> request = new AtomicReference<>();
    private HttpServer server;
    private PaymentAccess access;
    private int status = 200;
    private String body;

    @BeforeEach
    void setUp() throws Exception {
        body = """
            {"success":true,"message":"OK","data":{"id":"%s","usuario_id":"%s",
            "items":[],"direccion":{"codigo_postal":"38000","calle":"Centro","ciudad":"Celaya","estado":"Guanajuato"},
            "costo_envio":"0.00","total":"10.00","estado":"pagado","creado_en":"2026-01-01T00:00:00Z"}}
            """.formatted(order, owner);
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            request.set(exchange.getRequestMethod() + " " + exchange.getRequestURI() + " "
                + exchange.getRequestHeaders().getFirst("X-Service-Token"));
            byte[] response = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, response.length);
            try (var output = exchange.getResponseBody()) { output.write(response); }
        });
        server.start();
        access = new PaymentAccess("inbound-test", "outbound-test",
            "http://127.0.0.1:" + server.getAddress().getPort(), "");
    }

    @AfterEach
    void tearDown() { server.stop(0); }

    @Test
    void confirmsOwnerOverInternalHttpAndRejectsOtherCustomer() {
        access.requireOwner(order, new PaymentAccess.Identity(owner, "cliente"));
        assertEquals("GET /api/pedidos/" + order + " outbound-test", request.get());
        assertEquals(403, assertThrows(ApiError.class,
            () -> access.requireOwner(order, new PaymentAccess.Identity(UUID.randomUUID(), "cliente"))).status);
    }

    @Test
    void mapsMissingOrderAndUnavailableOrMalformedResponses() {
        var identity = new PaymentAccess.Identity(owner, "cliente");
        status = 404;
        body = "{\"success\":false,\"message\":\"No encontrado\",\"errors\":{}}";
        assertEquals(404, assertThrows(ApiError.class, () -> access.requireOwner(order, identity)).status);
        status = 503;
        assertEquals(503, assertThrows(ApiError.class, () -> access.requireOwner(order, identity)).status);
        status = 200;
        body = "{\"success\":true,\"message\":\"OK\",\"data\":{\"usuario_id\":\"invalid\"}}";
        assertEquals(503, assertThrows(ApiError.class, () -> access.requireOwner(order, identity)).status);
    }

    @Test
    void adminDoesNotNeedOwnerLookup() {
        access.requireOwner(order, new PaymentAccess.Identity(UUID.randomUUID(), "admin"));
        assertNull(request.get());
    }
}
