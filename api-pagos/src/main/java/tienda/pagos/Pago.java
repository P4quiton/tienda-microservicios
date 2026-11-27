package tienda.pagos;

import java.time.Instant;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonProperty;

record Pago(
    UUID id,
    @JsonProperty("pedido_id") UUID pedidoId,
    String monto,
    @JsonProperty("metodo_pago") String metodoPago,
    String estado,
    @JsonProperty("creado_en") Instant creadoEn
) {}
