# API Inventario

API REST de existencias con Go 1.26, Gin y PostgreSQL 17. Escucha en el puerto `8004`; usa su propia base `db_inventario` y el rol `usr_inventario`.

## Configuración

Copia `.env.example` a `.env` y configura la conexión PostgreSQL. En ejecución local usa `127.0.0.1:15432`; dentro de Docker usa `postgres:5432`. La base `db_inventario` y el rol `usr_inventario` son creados por la infraestructura del equipo con permisos limitados. Usa como `DB_PASSWORD` el valor local de `POSTGRES_INVENTARIO_PASSWORD` del `.env` raíz. `SERVICE_TOKEN_PEDIDOS_INVENTARIO` y la clave pública JWT son valores locales/secrets; no los subas al repositorio.

El servicio aplica sus migraciones versionadas al iniciar. La migración `002_idempotency.sql` copia al registro común las claves y resultados previos de reabastecimiento; como las filas antiguas no guardaban identidad, se marcan `admin:legacy` y siguen pudiendo repetirse por un administrador con la misma clave y solicitud. Las operaciones nuevas almacenan identidad, operación, hash y resultado en una transacción; la migración conserva las tablas anteriores y no borra inventario ni reservas. Requiere acceso a PostgreSQL. `PRODUCTOS_API_BASE_URL` apunta a Productos para validar que el producto exista al consultar un producto aún no inventariado o reabastecerlo. La URL interna predeterminada es `http://api-productos:8002`.

Para compilar y ejecutar fuera de Docker:

```bash
go mod download
set -a
. ./.env
set +a
go run ./cmd/api
```

## Endpoints

| Método | Ruta | Acceso |
|---|---|---|
| GET | `/api/inventario/{producto_id}` | Público; UUID v4 |
| POST | `/api/inventario/reservar` | `X-Service-Token` de Pedidos + `Idempotency-Key` UUID v4 |
| POST | `/api/inventario/confirmar` | `X-Service-Token` de Pedidos + `Idempotency-Key` UUID v4 |
| POST | `/api/inventario/liberar` | `X-Service-Token` de Pedidos + `Idempotency-Key` UUID v4 |
| POST | `/api/inventario/reabastecer` | JWT RS256 con rol `admin` e `Idempotency-Key` UUID v4 |
| GET | `/health` | Liveness; no consulta PostgreSQL |
| GET | `/ready` | Readiness; comprueba PostgreSQL |

Las reservas se aplican en una transacción, bloqueando los productos en orden UUID. El stock disponible es `stock_fisico - reservado`. Las mutaciones requieren `Idempotency-Key`; el servicio persiste identidad autenticada, operación, hash y resultado junto con cada efecto. Repetir la misma clave, identidad y payload devuelve el resultado guardado; reutilizar una clave con otra identidad, operación o payload produce `409`. Una reserva por pedido evita descontar dos veces, incluso con otra clave y los mismos artículos. Confirmar reduce físico y reservado; liberar reduce solo reservado. Los reintentos no repiten los efectos.

Si falta stock en cualquier artículo, se revierte la reserva completa y se guarda el `409` con `errors.stock[0] = stock_insuficiente`. La misma clave con el mismo cuerpo repite ese resultado incluso después de reabastecer. Una clave nueva permite evaluar de nuevo el stock para el mismo pedido si aún carece de reserva. Pedidos debe mantener su clave al reintentar. Reutilizar la clave con otros datos, identidad u operación devuelve `409` con `errors.idempotency_key[0] = conflicto_idempotencia`.

`POST /api/inventario/reabastecer` recibe `{ "producto_id": "UUID-v4", "cantidad": 5 }`. Una repetición con la misma clave y el mismo cuerpo devuelve el resultado previo; la misma clave con cuerpo diferente devuelve `409`.

Todas las respuestas de negocio usan `success`, `message` y `data`; los errores usan `success`, `message` y `errors`. El contrato OpenAPI está en [`../docs/api/inventario.yaml`](../docs/api/inventario.yaml).

## Límites de solicitudes

- Por IP y por instancia, cada ventana de un minuto admite 120 consultas, 30 mutaciones administrativas y 300 llamadas al conjunto de rutas internas autenticadas con `X-Service-Token`. Las solicitudes fallidas también consumen cuota. El `429` se devuelve en JSON con `Retry-After` en segundos. Las sondas `/health` y `/ready` quedan fuera de los límites.
- Cada grupo purga contadores vencidos al recibir tráfico. Al alcanzar el tope de 10000 clientes registrados, los clientes nuevos comparten un contador adicional. Los límites y el tope se pueden configurar con `RATE_LIMIT_CONSULTA_POR_MIN`, `RATE_LIMIT_MUTACION_POR_MIN`, `RATE_LIMIT_INTERNA_POR_MIN` y `RATE_LIMIT_MAX_CLIENTES`.
- Por defecto la IP se obtiene de la conexión. Configura `TRUSTED_PROXIES` con IP o CIDR separados por comas para aceptar `X-Forwarded-For` únicamente de esos proxies. Configura el proxy de entrada para sobrescribir el encabezado recibido del cliente.
- El cuerpo JSON de las mutaciones admite hasta 262144 bytes. Si lo supera, la API devuelve `413` en JSON.

## Docker

Desde la raíz del monorepo:

```bash
docker build -t api-inventario:local ./api-inventario
```

La imagen es multietapa, no incluye dependencias de desarrollo y ejecuta como usuario no root. El despliegue debe inyectar las variables de entorno/secrets y conectar el contenedor a PostgreSQL y a `api-productos`.

Ejecuta las pruebas desde esta carpeta con `go test ./...`. Para incluir la integración, configura `TEST_PG_HOST`, `TEST_PG_PORT`, `TEST_PG_DATABASE`, `TEST_PG_USER` y `TEST_PG_PASSWORD` con una base PostgreSQL 17 desechable y ejecuta `go test ./... -p 1 -count=1` para aplicar las migraciones desde un paquete a la vez.
