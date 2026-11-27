#!/bin/sh
# Entrypoint de api-carrito: espera a PostgreSQL, aplica migraciones (node src/migrate.js, idempotente) y cede
# el proceso al CMD con exec. Usa openPool de src/db.js, así la configuración de conexión es la misma que la
# del servicio. Nunca se ejecutan borrados de datos.
set -eu

fail() {
    echo "api-carrito: $1" >&2
    exit 1
}

[ -n "${DB_HOST:-}" ] || fail "falta DB_HOST"
[ -n "${DB_DATABASE:-}" ] || fail "falta DB_DATABASE"
[ -n "${DB_USERNAME:-}" ] || fail "falta DB_USERNAME"

BD_INTENTOS=30
BD_PAUSA_SEGUNDOS=2
COMPROBACION_BD="import { openPool } from './src/db.js'; const pool = openPool(); try { await pool.query('SELECT 1'); } finally { await pool.end(); }"

esperar_base() {
    intento=1
    until node --input-type=module -e "$COMPROBACION_BD" >/dev/null 2>&1; do
        [ "$intento" -lt "$BD_INTENTOS" ] \
            || fail "PostgreSQL no acepta conexiones tras $BD_INTENTOS intentos (${DB_HOST}:${DB_PORT:-5432})"
        echo "api-carrito: esperando PostgreSQL (intento $intento de $BD_INTENTOS)" >&2
        intento=$((intento + 1))
        sleep "$BD_PAUSA_SEGUNDOS"
    done
}

esperar_base
echo "api-carrito: aplicando migraciones" >&2
node src/migrate.js || fail "migraciones fallidas; el contenedor no arranca"

exec "$@"
