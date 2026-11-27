CREATE TABLE inventarios (
    producto_id UUID PRIMARY KEY,
    stock_fisico BIGINT NOT NULL DEFAULT 0 CHECK (stock_fisico >= 0),
    reservado BIGINT NOT NULL DEFAULT 0 CHECK (reservado >= 0 AND reservado <= stock_fisico),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE reservas (
    pedido_id UUID PRIMARY KEY,
    request_hash CHAR(64) NOT NULL,
    items JSONB NOT NULL,
    estado VARCHAR(16) NOT NULL CHECK (estado IN ('reservada', 'confirmada', 'liberada')),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE reabastecimientos (
    idempotency_key UUID PRIMARY KEY,
    request_hash CHAR(64) NOT NULL,
    producto_id UUID NOT NULL,
    cantidad BIGINT NOT NULL CHECK (cantidad > 0),
    disponibles BIGINT,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX reservas_estado_idx ON reservas (estado);
