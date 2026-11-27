BEGIN;

-- Serializa ejecuciones simultáneas (varias réplicas o reintentos de despliegue).
SELECT pg_advisory_xact_lock(hashtextextended('api-carrito:migracion', 0));

CREATE TABLE IF NOT EXISTS carritos (
    usuario_id uuid PRIMARY KEY,
    version bigint NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS carrito_items (
    usuario_id uuid NOT NULL REFERENCES carritos (usuario_id),
    producto_id uuid NOT NULL,
    cantidad integer NOT NULL CHECK (cantidad > 0),
    PRIMARY KEY (usuario_id, producto_id)
);

CREATE TABLE IF NOT EXISTS carrito_adiciones (
    actor_id uuid NOT NULL,
    clave uuid NOT NULL,
    hash text NOT NULL,
    resultado jsonb NOT NULL,
    PRIMARY KEY (actor_id, clave)
);

CREATE TABLE IF NOT EXISTS carrito_compras (
    pedido_id uuid PRIMARY KEY,
    usuario_id uuid NOT NULL REFERENCES carritos (usuario_id),
    version bigint NOT NULL,
    items jsonb NOT NULL,
    estado text NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'confirmado', 'cancelado')),
    resultado jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS carrito_compra_pendiente
ON carrito_compras (usuario_id)
WHERE estado = 'pendiente';

COMMIT;
