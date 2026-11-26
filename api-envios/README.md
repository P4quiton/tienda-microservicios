# api-envios

Servicio de envíos de la tienda (Python 3.12, FastAPI, PostgreSQL 17). Puerto **8003**.
Contrato normativo: [`../docs/api/envios.yaml`](../docs/api/envios.yaml); `openapi.json` es su conversión a JSON
y es lo que sirve `GET /openapi.json`. Reglas generales: [`../docs/contratos-api.md`](../docs/contratos-api.md).

## Endpoints

| Método | Ruta | Acceso | Función |
|---|---|---|---|
| POST | `/api/envios/cotizar` | JWT o `X-Service-Token` | Cotización simulada |
| POST | `/api/envios/generar` | Solo `X-Service-Token` (Pedidos) + `Idempotency-Key` | Genera la guía (201) |
| GET | `/api/envios/rastreo/{guia}` | Titular/admin (JWT) o `X-Service-Token` | Consulta la guía |
| GET | `/health` | Público | Proceso vivo, sin BD |
| GET | `/ready` | Público | 200 si la BD responde y el esquema está migrado; 503 si no |

Reglas relevantes:
- **Cotización** (`app/cotizacion.py`): `89.00 + 10.00 × primer dígito del CP + 25.00 × (cantidad − 1)`; días `2 + zona // 3`. El contrato solo exige cantidad ≥ 1, pero `costo_envio` debe cumplir `^\d{1,10}\.\d{2}$`: una cantidad cuyo importe exceda 9999999999.99 se rechaza con 422.
- **Generar**: solo para pedidos `pagado`/`enviado` (se consulta a Pedidos). Una guía por pedido. Misma clave y payload devuelve lo guardado (sin consultar a Pedidos); misma clave con otro payload, 409. Con otra clave, el mismo pedido y dirección devuelven la guía existente; una dirección distinta produce 409. Misma clave **en curso** (aún ejecutándose, aquí o en otra réplica): 409 inmediato; al terminar, el reintento recibe la guía.
- **Contrato 1.1.0 / generar**: el resultado original (201) se guarda junto a la guía y la clave (`idempotencia.resultado`); toda repetición lo devuelve tal cual aunque el envío avance de estado. Una clave nueva con el mismo pedido y dirección recibe ese mismo resultado sin consultar a Pedidos; una dirección distinta es 409 aunque la clave sea otra. Estado inicial `preparando`; generar la guía nunca notifica.
- **Despacho y notificación a Pedidos**: `EnviosRepo.despachar(pedido_id)` pasa `preparando -> en_transito` y, en la misma transacción, encola en `notificaciones_pedido` (outbox, UNIQUE por pedido) el `PATCH /api/pedidos/{id}/estado {estado: enviado}` con `X-Service-Token` (`SERVICE_TOKEN_ENVIOS_PEDIDOS`) e `Idempotency-Key` estable (UUID v4 derivado por hash del pedido). `Notificador` (`app/notificaciones.py`) reintenta al arrancar y cada `NOTIFICACION_INTERVALO_SECONDS` (30) con backoff 5 s..15 min, lease de 60 s y `SKIP LOCKED` entre réplicas; solo un 200 confirma. **Decisión pendiente**: el contrato no define qué endpoint o evento dispara el despacho real, así que `despachar` es una función interna sin ruta HTTP; hoy nada la invoca en producción.
- **Rastreo**: un cliente solo ve guías de sus pedidos (titularidad vía Pedidos); si Pedidos no responde, 503.
- **UUID v4** en todo identificador: `pedido_id`, `Idempotency-Key` (422 si no es v4), `sub` del JWT (401) y `usuario_id` de Pedidos.
- No se imponen longitudes propias a `calle`, `ciudad`, `estado` ni `guia`: el contrato no las declara. Solo se rechaza (422) texto que PostgreSQL no puede almacenar (NUL, sustitutos Unicode sueltos).
- BD o esquema no disponibles en una ruta de negocio: 503 (no 500).
- Campos no declarados se rechazan (422). Sobres `{success, message, data|errors}`.

## Configuración

Copiar `.env.example` a `.env` (ignorado por Git) y reemplazar cada `REPLACE_ME`; el servicio no arranca con marcadores.
Los dos tokens de servicio deben ser distintos. `JWT_PUBLIC_KEY_PATH` apunta a la clave pública RS256 de api-usuarios
(la privada nunca vive aquí). Las migraciones de `migrations/*.sql` se aplican desde un hilo en segundo plano con reintentos (backoff hasta 30 s): el proceso arranca aunque la BD esté caída, `/health` responde 200 y `/ready` devuelve 503 hasta que la BD conteste y el esquema esté migrado. Varias réplicas se serializan con un advisory lock.

## Ejecución local

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
set -a; . ./.env; set +a
.venv/bin/uvicorn --factory app.main:build_app --port 8003
```

## Pruebas

```bash
.venv/bin/python -m pytest -q
```

Usan PostgreSQL real: `TEST_DATABASE_URL` (cadena libpq) si está definida; si no, levantan un contenedor
efímero `postgres:17-alpine` con Docker; sin ninguno de los dos se omiten.

## Docker

```bash
docker build -t api-envios .
docker run --rm -p 8003:8003 --env-file .env -v /ruta/jwt-public.pem:/run/secrets/jwt-public.pem:ro api-envios
```

La imagen corre como usuario no root (uid 10001) y define `HEALTHCHECK` sobre `/health`.
Sin acceso a PostgreSQL el contenedor sigue vivo (healthy) pero `/ready` da 503 y reintenta migrar.

## Estructura

`app/` (`routes`, `auth`, `cotizacion`, `repositorio`, `pedidos_client`, `db`, `config`, `errors`, `main`), `migrations/`, `tests/`.
