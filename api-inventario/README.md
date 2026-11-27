# API Inventario

Servicio de existencias con Go 1.26, Gin y PostgreSQL 17. Escucha en el puerto `8004` y utiliza `db_inventario` con el rol `usr_inventario`.

## Configuración local

Copia `.env.example` a `.env` y configura `DB_PASSWORD` con el valor local de `POSTGRES_INVENTARIO_PASSWORD` del `.env` raíz. Usa `DB_HOST=127.0.0.1` y `DB_PORT=15432` fuera de Docker; dentro de la red del proyecto, usa `DB_HOST=postgres` y `DB_PORT=5432`. `JWT_PUBLIC_KEY_PATH` debe apuntar a la clave pública RS256 de Usuarios.

```bash
go mod download
set -a
. ./.env
set +a
go run ./cmd/api
```

Al iniciar, el servicio aplica las migraciones pendientes dentro de una transacción.

## Endpoints disponibles

| Método | Ruta | Acceso |
|---|---|---|
| GET | `/api/inventario/{producto_id}` | Público; UUID v4 |
| POST | `/api/inventario/reabastecer` | JWT RS256 con rol `admin` e `Idempotency-Key` UUID v4 |
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness; comprueba PostgreSQL |


Las operaciones internas de reserva solo aceptan llamadas de Pedidos mediante `X-Service-Token`. Reservar, confirmar y liberar requieren `Idempotency-Key` UUID v4. La reserva bloquea existencias dentro de una transacción; una clave repetida devuelve el resultado anterior y una reserva existente para el mismo pedido no vuelve a incrementar el reservado. Confirmar descuenta stock físico y reservado una sola vez; liberar reduce únicamente el reservado.

La consulta devuelve las unidades disponibles (`stock_fisico - reservado`). Si el producto existe en Productos y aún no tiene registro de inventario, devuelve cero. Reabastecer recibe `producto_id` y `cantidad`, valida el producto y actualiza el stock en una transacción. La clave de idempotencia guarda identidad, operación, hash y resultado con el efecto; repetir clave y cuerpo devuelve el resultado anterior, y reutilizar la clave con otros datos devuelve `409`.

La migración de idempotencia conserva los reabastecimientos anteriores y permite reintentar sus claves sin volver a incrementar el stock. Las respuestas de negocio usan `success`, `message` y `data`; los errores incluyen `errors`.

El contrato completo está en [`../docs/api/inventario.yaml`](../docs/api/inventario.yaml). Las rutas internas de reserva, confirmación y liberación coordinan el checkout con Pedidos.
