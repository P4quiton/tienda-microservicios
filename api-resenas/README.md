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
uvicorn app.main:app --no-proxy-headers --host 0.0.0.0 --port "${PORT:-8008}"
```

Dentro de Docker usa `MONGO_HOST=mongodb`, `MONGO_PORT=27017` y `API_PRODUCTOS_URL=http://api-productos:8002`; ambos servicios deben estar conectados a `red-tienda`. En ejecución local, Productos usa `http://127.0.0.1:8002`.

## Endpoints

| Método | Ruta | Acceso |
|---|---|---|
| GET | `/api/resenas/producto/{producto_id}` | Público; UUID v4 |
| POST | `/api/resenas` | JWT RS256 de cliente o administrador |
| GET | `/health` | Liveness; no consulta MongoDB |
| GET | `/ready` | Readiness; comprueba MongoDB y habilita escrituras al preparar los índices |

La creación recibe `producto_id`, `calificacion` (entero de 1 a 5) y `comentario` (hasta 1000 caracteres). `usuario_id` se deriva del claim `sub` del JWT. La API comprueba el producto mediante Productos y garantiza una reseña por usuario y producto con un índice único de MongoDB. La lista devuelve `promedio: null` y `total: 0` si aún no hay reseñas. Si MongoDB falla al arrancar, `/health` sigue disponible y tanto `/ready` como la creación responden 503 mientras los índices estén pendientes. Cada consulta a `/ready` reintenta prepararlos hasta que MongoDB confirme su creación.

La aplicación admite cuerpos de hasta 256 KiB y devuelve 413 en JSON si la longitud declarada o los bytes entregados por el servidor HTTP superan el límite, incluido el envío en fragmentos.

La cuota por IP es de 120 consultas y 30 mutaciones en una ventana móvil de 60 segundos. `/internal` y sus subrutas reservan 300 solicitudes por minuto. Reseñas actualmente carece de endpoints internos. Las sondas GET de `/health` y `/ready` quedan exentas. Los excesos devuelven 429 en JSON con `Retry-After` en segundos. Cada proceso mantiene hasta 10 000 contadores en memoria, purga los vencidos al recibir tráfico y devuelve 429 a claves nuevas si se agota la capacidad. Cada instancia o worker mantiene sus propias cuotas.

Por defecto, la app identifica al cliente por la IP de la conexión. Con `TRUSTED_PROXIES`, solo acepta `X-Forwarded-For` de un proxy enumerado y toma la primera IP ajena a la lista al recorrer la cadena de derecha a izquierda. Configura redes específicas de proxies controlados que sobrescriban la cabecera o agreguen la IP del par real. Usa `--no-proxy-headers` al iniciar Uvicorn para conservar la IP original de la conexión en ASGI.

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
