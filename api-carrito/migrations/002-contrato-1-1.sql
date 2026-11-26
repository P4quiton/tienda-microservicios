-- Contrato 1.1.0: linea_id por línea y registro de operaciones internas idempotentes.
-- Idempotente: se puede aplicar varias veces y en paralelo.
BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('api-carrito:migracion', 0));

-- Las filas existentes reciben un UUID propio (el valor por defecto volátil se evalúa por fila).
-- Una línea eliminada y vuelta a crear recibe otro UUID: linea_id no se reutiliza.
ALTER TABLE carrito_items ADD COLUMN IF NOT EXISTS linea_id uuid NOT NULL DEFAULT gen_random_uuid();

CREATE UNIQUE INDEX IF NOT EXISTS carrito_items_linea_id ON carrito_items (linea_id);

-- Resultado registrado por (identidad llamadora, Idempotency-Key) para vaciar/iniciar/finalizar/liberar.
CREATE TABLE IF NOT EXISTS carrito_operaciones (
    identidad text NOT NULL,
    clave uuid NOT NULL,
    operacion text NOT NULL,
    hash text NOT NULL,
    resultado jsonb NOT NULL,
    PRIMARY KEY (identidad, clave)
);

COMMIT;
