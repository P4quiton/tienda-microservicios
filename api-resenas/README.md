# API Reseñas

Servicio REST con FastAPI, Python 3.12 y MongoDB 8.0. Escucha en el puerto `8008`; utiliza únicamente `db_resenas` con el usuario `usr_resenas`.

## Configuración local

La raíz del monorepo debe tener un `.env` generado para la infraestructura. No lo reemplaces si ya existe. Copia `.env.example` a `.env` solo si todavía no tienes uno para este servicio y configura `MONGO_PASSWORD` con el valor local de `MONGO_RESENAS_PASSWORD` del `.env` raíz. Conserva MongoDB en `127.0.0.1:27017` y configura `JWT_PUBLIC_KEY_PATH` con la ruta local a la clave pública RS256 de Usuarios.

Instala Python 3.12 y ejecuta desde esta carpeta:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
set -a
. ./.env
set +a
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8008}"
```

Dentro de Docker usa `MONGO_HOST=mongodb`, `MONGO_PORT=27017` y `API_PRODUCTOS_URL=http://api-productos:8002`; ambos servicios deben estar conectados a `red-tienda`. En ejecución local, Productos usa `http://127.0.0.1:8002`.

## Endpoints

| Método | Ruta | Acceso |
|---|---|---|
| GET | `/api/resenas/producto/{producto_id}` | Público; UUID v4 |
| POST | `/api/resenas` | JWT RS256 de cliente o administrador |
| GET | `/health` | Liveness; no consulta MongoDB |
| GET | `/ready` | Readiness; comprueba MongoDB |

La creación recibe `producto_id`, `calificacion` (entero de 1 a 5) y `comentario` (hasta 1000 caracteres). `usuario_id` se deriva del claim `sub` del JWT. La API comprueba el producto mediante Productos y garantiza una reseña por usuario y producto con un índice único de MongoDB. La lista devuelve `promedio: null` y `total: 0` si aún no hay reseñas.

Las respuestas de negocio siguen el sobre `success`, `message` y `data`; los errores incluyen `errors`. La especificación normativa es [`../docs/api/resenas.yaml`](../docs/api/resenas.yaml).

## Docker

Construye desde la raíz del monorepo:

```bash
docker build -t api-resenas:local ./api-resenas
```

Inyecta las variables y monta la clave pública como secreto de solo lectura. La imagen corre como usuario no root y no incorpora archivos `.env` ni claves.

## Pruebas

```bash
pip install -r requirements-dev.lock
pytest
```

La suite cubre el contrato, autenticación, derivación del usuario desde JWT, validación, producto inexistente, fallos de dependencia y duplicados.
