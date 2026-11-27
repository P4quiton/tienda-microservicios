package tienda.pagos;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
class PagosController {
    private final PagosRepository repository;
    private final PaymentAccess access;
    @Value("${pagos.max-json-bytes:" + CuerpoJson.DEFAULT_MAX_BYTES + "}")
    private int maxJsonBytes = CuerpoJson.DEFAULT_MAX_BYTES;

    PagosController(PagosRepository repository, PaymentAccess access) {
        this.repository = repository;
        this.access = access;
    }

    @PostMapping("/api/pagos/procesar")
    ResponseEntity<Success> process(
        @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
        HttpServletRequest request
    ) {
        access.requirePedidos(serviceToken, authorization);
        var key = PagoRequest.uuid(idempotencyKey, "Idempotency-Key");
        var pago = repository.process(PagoRequest.parse(CuerpoJson.read(request, maxJsonBytes)), key);
        return ResponseEntity.status(201).body(new Success(true, "OK", pago));
    }

    @GetMapping("/api/pagos/pedido/{pedido_id}")
    Success receipt(
        @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @PathVariable("pedido_id") String pedidoId
    ) {
        var identity = access.isPedidos(serviceToken) ? null : access.authenticate(authorization);
        var id = PagoRequest.uuid(pedidoId, "pedido_id");
        if (identity != null) {
            access.requireOwner(id, identity);
        }
        var pago = repository.find(id).orElseThrow(() -> new ApiError(404, "Pago no encontrado"));
        return new Success(true, "OK", pago);
    }

    @GetMapping("/health")
    Health health() {
        return new Health("ok", "api-pagos");
    }

    @GetMapping("/ready")
    ResponseEntity<Health> ready() {
        try {
            if (repository.ready()) {
                return ResponseEntity.ok(health());
            }
        } catch (RuntimeException exception) {
            // BD inaccesible (DataAccessException) o Flyway sin acceso al historial: ambos son "no listo".
        }
        return ResponseEntity.status(503).body(new Health("unavailable", "api-pagos"));
    }

    record Success(boolean success, String message, Pago data) {}
    record Health(String status, String service) {}
}
