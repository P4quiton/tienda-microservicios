-- Una guía por pedido (UNIQUE pedido_id). Los importes no se almacenan: la cotización es pura.
CREATE TABLE envios (
    id            UUID PRIMARY KEY,
    pedido_id     UUID NOT NULL UNIQUE,
    guia          TEXT NOT NULL UNIQUE,
    estado        TEXT NOT NULL DEFAULT 'preparando'
                  CHECK (estado IN ('preparando', 'en_transito', 'entregado')),
    codigo_postal TEXT NOT NULL,
    calle         TEXT NOT NULL,
    ciudad        TEXT NOT NULL,
    estado_region TEXT NOT NULL,
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotencia de POST /generar: misma clave + mismo hash devuelve el resultado previo.
CREATE TABLE idempotencia (
    clave        UUID NOT NULL,
    solicitante  TEXT NOT NULL,
    operacion    TEXT NOT NULL,
    hash_solicitud TEXT NOT NULL,
    envio_id     UUID NOT NULL REFERENCES envios(id),
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (clave, solicitante, operacion)
);
