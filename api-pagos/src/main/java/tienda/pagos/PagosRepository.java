package tienda.pagos;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.Optional;
import java.util.UUID;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
class PagosRepository {
    private final JdbcClient jdbc;

    PagosRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional
    public Pago process(PagoRequest request, UUID key) {
        String hash = hash(request);
        // La restricción única serializa reintentos concurrentes incluso entre réplicas.
        jdbc.sql("""
            INSERT INTO pagos (id, pedido_id, idempotency_key, request_hash, monto, metodo_pago, estado)
            VALUES (:id, :pedido, :key, :hash, :monto, :metodo, :estado)
            ON CONFLICT DO NOTHING
            """).param("id", UUID.randomUUID()).param("pedido", request.pedidoId()).param("key", key)
            .param("hash", hash).param("monto", request.monto()).param("metodo", request.metodoPago())
            .param("estado", simulate(request.metodoPago())).update();

        return jdbc.sql("SELECT * FROM pagos WHERE idempotency_key = :key").param("key", key)
            .query((row, number) -> {
                if (!hash.equals(row.getString("request_hash"))) {
                    throw new ApiError(409, "La clave de idempotencia pertenece a otra solicitud");
                }
                return read(row);
            }).optional().orElseThrow(() -> new ApiError(409, "El pedido ya tiene un pago"));
    }

    Optional<Pago> find(UUID pedidoId) {
        return jdbc.sql("SELECT * FROM pagos WHERE pedido_id = :pedido").param("pedido", pedidoId)
            .query((row, number) -> read(row)).optional();
    }

    boolean ready() {
        jdbc.sql("SELECT 1 FROM pagos LIMIT 0").query(Integer.class).list();
        return true;
    }

    static String simulate(String metodoPago) {
        return metodoPago.equals("tarjeta_simulada") ? "aprobado" : "rechazado";
    }

    private static Pago read(ResultSet row) throws SQLException {
        return new Pago(row.getObject("id", UUID.class), row.getObject("pedido_id", UUID.class),
            row.getBigDecimal("monto").toPlainString(), row.getString("metodo_pago"),
            row.getString("estado"), row.getObject("creado_en", OffsetDateTime.class).toInstant());
    }

    private static String hash(PagoRequest request) {
        try {
            String normalized = request.pedidoId() + "|" + request.monto().toPlainString() + "|" + request.metodoPago();
            return HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-256").digest(normalized.getBytes(StandardCharsets.UTF_8))
            );
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
