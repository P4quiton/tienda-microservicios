#!/bin/sh
# Entrypoint de api-pedidos: espera a PostgreSQL, aplica migraciones pendientes y cede el proceso al CMD con
# exec. Debe migrar antes de `pedidos:recuperar` y del worker de schedule, que leen las tablas de pedidos.
# Las migraciones son idempotentes: sin pendientes, `migrate --force` no cambia nada. Nunca se ejecutan
# migrate:fresh ni borrados de datos.
set -eu

fail() {
    echo "api-pedidos: $1" >&2
    exit 1
}

[ -n "${DB_HOST:-}" ] || fail "falta DB_HOST"
[ -n "${DB_DATABASE:-}" ] || fail "falta DB_DATABASE"
[ -n "${DB_USERNAME:-}" ] || fail "falta DB_USERNAME"

BD_INTENTOS=30
BD_PAUSA_SEGUNDOS=2
COMPROBACION_BD='try { new PDO(sprintf("pgsql:host=%s;port=%s;dbname=%s;sslmode=%s", getenv("DB_HOST"), getenv("DB_PORT") ?: "5432", getenv("DB_DATABASE"), getenv("DB_SSLMODE") ?: "prefer"), getenv("DB_USERNAME"), getenv("DB_PASSWORD"), [PDO::ATTR_TIMEOUT => 3]); } catch (Throwable $error) { exit(1); }'

esperar_base() {
    intento=1
    until php -r "$COMPROBACION_BD" >/dev/null 2>&1; do
        [ "$intento" -lt "$BD_INTENTOS" ] \
            || fail "PostgreSQL no acepta conexiones tras $BD_INTENTOS intentos (${DB_HOST}:${DB_PORT:-5432})"
        echo "api-pedidos: esperando PostgreSQL (intento $intento de $BD_INTENTOS)" >&2
        intento=$((intento + 1))
        sleep "$BD_PAUSA_SEGUNDOS"
    done
}

esperar_base
echo "api-pedidos: aplicando migraciones" >&2
php artisan migrate --force || fail "migraciones fallidas; el contenedor no arranca"

exec "$@"
