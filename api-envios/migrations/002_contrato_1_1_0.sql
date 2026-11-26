-- Contrato 1.1.0: resultado original persistido junto al efecto y outbox durable de notificaciones a Pedidos.

-- Resultado original de POST /generar (lo que se devuelve ante cualquier repetición, aunque el envío avance).
ALTER TABLE envios ADD COLUMN resultado_inicial JSONB;
UPDATE envios SET resultado_inicial = jsonb_build_object(
    'id', id::text, 'pedido_id', pedido_id::text, 'guia', guia, 'estado', 'preparando');
ALTER TABLE envios ALTER COLUMN resultado_inicial SET NOT NULL;
ALTER TABLE envios ADD COLUMN despachado_en TIMESTAMPTZ;

ALTER TABLE idempotencia ADD COLUMN resultado JSONB;
UPDATE idempotencia i SET resultado = e.resultado_inicial FROM envios e WHERE e.id = i.envio_id;
ALTER TABLE idempotencia ALTER COLUMN resultado SET NOT NULL;
-- pedido_id junto a la clave: toda clave queda atada a un único pedido.
ALTER TABLE idempotencia ADD COLUMN pedido_id UUID;
UPDATE idempotencia i SET pedido_id = e.pedido_id FROM envios e WHERE e.id = i.envio_id;
ALTER TABLE idempotencia ALTER COLUMN pedido_id SET NOT NULL;

-- Outbox: una notificación PATCH enviado por pedido, creada en la misma transacción que el paso a en_transito.
CREATE TABLE notificaciones_pedido (
    id              UUID PRIMARY KEY,
    pedido_id       UUID NOT NULL UNIQUE,
    envio_id        UUID NOT NULL REFERENCES envios(id),
    idempotency_key UUID NOT NULL,                       -- estable: derivada del pedido
    estado          TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'enviada')),
    intentos        INTEGER NOT NULL DEFAULT 0,
    proximo_intento TIMESTAMPTZ NOT NULL DEFAULT now(),  -- también hace de lease mientras se intenta
    ultimo_error    TEXT,                                -- sin secretos
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    enviada_en      TIMESTAMPTZ
);
CREATE INDEX notificaciones_pedido_pendientes ON notificaciones_pedido (proximo_intento) WHERE estado = 'pendiente';
