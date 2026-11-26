# API Inventario

Servicio de existencias con Go 1.26, Gin y PostgreSQL 17. Escucha en el puerto `8004` y utiliza `db_inventario` con el rol `usr_inventario`.

## Configuración local

Copia `.env.example` a `.env` y configura `DB_PASSWORD` con el valor local de `POSTGRES_INVENTARIO_PASSWORD` del `.env` raíz. Usa `DB_HOST=127.0.0.1` y `DB_PORT=15432` fuera de Docker; dentro de la red del proyecto, usa `DB_HOST=postgres` y `DB_PORT=5432`.

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
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness; comprueba PostgreSQL |

La consulta devuelve las unidades disponibles (`stock_fisico - reservado`). Si el producto existe en Productos y aún no tiene registro de inventario, devuelve cero. Las respuestas de negocio usan `success`, `message` y `data`; los errores incluyen `errors`.

El contrato completo está en [`../docs/api/inventario.yaml`](../docs/api/inventario.yaml). Los endpoints de mutación se incorporarán en los siguientes cambios.
