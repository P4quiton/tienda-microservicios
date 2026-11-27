CREATE TABLE pagos (
    id UUID PRIMARY KEY,
    pedido_id UUID NOT NULL UNIQUE,
    idempotency_key UUID NOT NULL UNIQUE,
    request_hash CHAR(64) NOT NULL,
    monto NUMERIC(12, 2) NOT NULL CHECK (monto > 0),
    metodo_pago TEXT NOT NULL CHECK (metodo_pago IN ('tarjeta_simulada', 'transferencia_simulada')),
    estado TEXT NOT NULL CHECK (estado IN ('aprobado', 'rechazado')),
    creado_en TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
