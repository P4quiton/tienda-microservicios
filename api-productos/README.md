# API Productos

Servicio REST de catálogo con Laravel 13, PHP 8.5 y PostgreSQL 17. Escucha en el puerto `8002` y usa la base `db_productos` con el rol dedicado `usr_productos`.

## Ejecución local

Requisitos: PHP 8.5 con `pdo_pgsql`, `openssl` y `mbstring`; Composer 2.9; PostgreSQL de la infraestructura del monorepo.

Desde esta carpeta, conserva un `.env` existente. Si aún no tienes uno, copia el ejemplo y configura los valores locales:

```bash
test -f .env || cp .env.example .env
composer install
if grep -q '^APP_KEY=base64:REPLACE_WITH_A_GENERATED_KEY$' .env; then php artisan key:generate; fi
```

Usa `DB_HOST=127.0.0.1`, `DB_PORT=15432`, `DB_DATABASE=db_productos` y `DB_USERNAME=usr_productos`. `DB_PASSWORD` debe coincidir con `POSTGRES_PRODUCTOS_PASSWORD` del `.env` raíz. Configura `JWT_PUBLIC_KEY_PATH` con la ruta local a la clave pública compartida por Usuarios; no guardes la clave en Git. Consulta la [guía de infraestructura](../docs/infraestructura.md) para preparar PostgreSQL.

Aplica la migración y carga datos de catálogo de ejemplo:

```bash
php artisan migrate --seed
```

Ejecuta el servicio:

```bash
php artisan serve --host=0.0.0.0 --port=8002
```

## API

| Método | Ruta | Acceso |
|---|---|---|
| GET | `/api/productos` | Público; filtros `q`, `categoria`, `pagina` y `limite` |
| GET | `/api/productos/{id}` | Público; UUID |
| POST | `/api/productos` | JWT RS256 con rol `admin` |
| GET | `/health` | Liveness; no consulta PostgreSQL |
| GET | `/ready` | Readiness; verifica conexión PostgreSQL |

El catálogo usa página `1` y límite `20` por defecto; el límite máximo es `100`. La búsqueda consulta nombre y descripción. El alta requiere `nombre`, `descripcion`, `precio`, `categoria` e `imagen_url`. El precio es una cadena decimal positiva con dos posiciones. Se rechazan campos adicionales. JWT valida firma RS256, emisor, audiencia, expiración, emisión, UUID v4 de `sub` y rol. Configura `JWT_ISSUER`, `JWT_AUDIENCE` y `JWT_PUBLIC_KEY_PATH` con los valores acordados con Usuarios.

Todas las respuestas de negocio usan `success`, `message` y `data`; los errores usan `success`, `message` y `errors`. El contrato está en [`../docs/api/productos.yaml`](../docs/api/productos.yaml).

## Pruebas

Con Composer instalado:

```bash
php artisan test --compact
```

La suite utiliza SQLite en memoria y genera claves JWT temporales. No necesita conectarse a PostgreSQL.

## Docker

Desde la raíz del monorepo, con Docker activo y las credenciales de infraestructura preparadas:

```bash
docker compose up -d postgres
docker build -t api-productos:local ./api-productos
```

El contenedor se conecta a PostgreSQL por `postgres:5432`. Para ejecutarlo junto a la infraestructura:

```bash
docker run --rm --name api-productos \
  --network red-tienda \
  -p 127.0.0.1:8002:8002 \
  --env-file api-productos/.env \
  -e APP_ENV=production \
  -e APP_DEBUG=false \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public_key \
  --mount type=bind,src=/ruta/segura/jwt-public.pem,dst=/run/secrets/jwt_public_key,readonly \
  api-productos:local
```

En otra terminal, prepara el esquema y datos de demostración:

```bash
docker exec api-productos php artisan migrate --seed --force
```

La imagen incluye un healthcheck para `/health`, ejecuta como usuario no root y no contiene `.env` ni pruebas. Inyecta secretos en tiempo de ejecución; no los agregues a Git ni a la imagen. El servicio aún debe incorporarse al `docker-compose.yml` raíz durante la integración de infraestructura.
