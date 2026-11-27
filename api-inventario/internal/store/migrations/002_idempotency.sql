CREATE TABLE operaciones_idempotentes (
    idempotency_key UUID PRIMARY KEY,
    identidad TEXT NOT NULL,
    operacion VARCHAR(32) NOT NULL CHECK (operacion IN ('reabastecer', 'reservar', 'confirmar', 'liberar')),
    request_hash CHAR(64) NOT NULL,
    resultado JSONB NOT NULL,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO operaciones_idempotentes (idempotency_key, identidad, operacion, request_hash, resultado, creado_en)
SELECT
    idempotency_key,
    'admin:legacy',
    'reabastecer',
    request_hash,
    jsonb_build_object('producto_id', producto_id, 'disponibles', disponibles),
    creado_en
FROM reabastecimientos
WHERE disponibles IS NOT NULL
ON CONFLICT (idempotency_key) DO NOTHING;
