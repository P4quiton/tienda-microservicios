package tienda.pagos;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;

import com.fasterxml.jackson.databind.JsonNode;

record PagoRequest(UUID pedidoId, BigDecimal monto, String metodoPago) {
    private static final Pattern UUID_V4 = Pattern.compile(
        "(?i)[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    );

    static PagoRequest parse(JsonNode body) {
        if (!body.isObject() || body.size() != 3
            || !body.has("pedido_id") || !body.has("monto") || !body.has("metodo_pago")) {
            throw invalid("body", "Se requieren pedido_id, monto y metodo_pago");
        }
        var pedidoId = uuid(body.path("pedido_id").textValue(), "pedido_id");
        var rawMonto = body.path("monto").textValue();
        if (rawMonto == null || !rawMonto.matches("[0-9]{1,10}\\.[0-9]{2}")) {
            throw invalid("monto", "Debe ser una cadena decimal con dos posiciones");
        }

        var monto = new BigDecimal(rawMonto);
        if (monto.signum() <= 0) {
            throw invalid("monto", "Debe ser positivo");
        }
        var metodo = body.path("metodo_pago").asText("");
        if (!metodo.equals("tarjeta_simulada") && !metodo.equals("transferencia_simulada")) {
            throw invalid("metodo_pago", "Método simulado inválido");
        }
        return new PagoRequest(pedidoId, monto, metodo);
    }

    static UUID uuid(String value, String field) {
        if (value == null || !UUID_V4.matcher(value).matches()) {
            throw invalid(field, "Debe ser un UUID v4");
        }
        return UUID.fromString(value);
    }

    private static ApiError invalid(String field, String message) {
        return new ApiError(422, "Validación", Map.of(field, List.of(message)));
    }
}
