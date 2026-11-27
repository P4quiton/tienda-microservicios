#!/bin/sh
# Entrypoint de api-usuarios. Corre como root solo para preparar las claves JWT, espera a PostgreSQL y aplica
# migraciones (estas como www-data); luego cede el proceso a la imagen base (docker-php-entrypoint ->
# apache2-foreground), que ejecuta PHP como www-data.
#
# Por qué: Compose monta la clave privada desde el host; si el archivo es 0600 de otro uid, www-data no
# puede leerla. Aquí se copia a un directorio privado en /run, propiedad de www-data, con modo 0400.
# La clave pública se copia igual para no depender de los permisos del host. Las copias no van a la imagen
# ni se hacen públicas (no se cambia el modo de la clave original).
set -eu

KEY_DIR=/run/api-usuarios-keys

fail() {
    echo "api-usuarios: $1" >&2
    exit 1
}

copy_key() {
    source_path="$1"
    target_path="$2"

    if [ ! -f "$source_path" ] || [ ! -r "$source_path" ]; then
        fail "clave JWT no legible: $source_path"
    fi

    install -o www-data -g www-data -m 0400 "$source_path" "$target_path" \
        || fail "no se pudo copiar la clave JWT a $target_path"
}

[ -n "${JWT_PRIVATE_KEY_PATH:-}" ] || fail "falta JWT_PRIVATE_KEY_PATH"
[ -n "${JWT_PUBLIC_KEY_PATH:-}" ] || fail "falta JWT_PUBLIC_KEY_PATH"

mkdir -p "$KEY_DIR"
chown www-data:www-data "$KEY_DIR"
chmod 0700 "$KEY_DIR"

copy_key "$JWT_PRIVATE_KEY_PATH" "$KEY_DIR/jwt-private.pem"
copy_key "$JWT_PUBLIC_KEY_PATH" "$KEY_DIR/jwt-public.pem"

export JWT_PRIVATE_KEY_PATH="$KEY_DIR/jwt-private.pem"
export JWT_PUBLIC_KEY_PATH="$KEY_DIR/jwt-public.pem"

# Migraciones antes de Apache. Se ejecutan como www-data (no como root, para no crear archivos de storage y
# bootstrap/cache de propiedad root). Si PostgreSQL aún no acepta conexiones, se reintenta; si la migración
# falla, el contenedor sale con error y no arranca a medias. `migrate --force` sin pendientes no cambia nada.
: "${DB_HOST:?api-usuarios: falta DB_HOST}"
: "${DB_DATABASE:?api-usuarios: falta DB_DATABASE}"
: "${DB_USERNAME:?api-usuarios: falta DB_USERNAME}"

BD_INTENTOS=30
BD_PAUSA_SEGUNDOS=2
COMPROBACION_BD='try { new PDO(sprintf("pgsql:host=%s;port=%s;dbname=%s;sslmode=%s", getenv("DB_HOST"), getenv("DB_PORT") ?: "5432", getenv("DB_DATABASE"), getenv("DB_SSLMODE") ?: "prefer"), getenv("DB_USERNAME"), getenv("DB_PASSWORD"), [PDO::ATTR_TIMEOUT => 3]); } catch (Throwable $error) { exit(1); }'

esperar_base() {
    intento=1
    until php -r "$COMPROBACION_BD" >/dev/null 2>&1; do
        [ "$intento" -lt "$BD_INTENTOS" ] \
            || fail "PostgreSQL no acepta conexiones tras $BD_INTENTOS intentos (${DB_HOST}:${DB_PORT:-5432})"
        echo "api-usuarios: esperando PostgreSQL (intento $intento de $BD_INTENTOS)" >&2
        intento=$((intento + 1))
        sleep "$BD_PAUSA_SEGUNDOS"
    done
}

esperar_base
echo "api-usuarios: aplicando migraciones" >&2
cd /var/www/html
runuser -u www-data -- php artisan migrate --force \
    || fail "migraciones fallidas; el contenedor no arranca"

exec docker-php-entrypoint "$@"
