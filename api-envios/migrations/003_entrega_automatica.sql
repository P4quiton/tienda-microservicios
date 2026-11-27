-- La 002 ya agrega la columna. Se asegura aquí para que la operación sea repetible.
ALTER TABLE envios ADD COLUMN IF NOT EXISTS despachado_en TIMESTAMPTZ;

-- Una guía en tránsito sin fecha empieza su plazo al migrar para evitar entregas inmediatas.
UPDATE envios SET despachado_en = now()
WHERE estado = 'en_transito' AND despachado_en IS NULL;
