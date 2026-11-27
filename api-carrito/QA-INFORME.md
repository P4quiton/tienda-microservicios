# QA "romper y arreglar": api-carrito (puerto 8005)

Entorno: Node v24.18.1, Express 5.3.0, PostgreSQL 17 temporal (`mojarra-pg-carrito`, puerto 55435, tmpfs, detenido al final).
Suite nueva: `test/qa-hostil.test.js` (21 pruebas). No se cambió `docs/api/*.yaml` ni otros servicios.

## Resultado antes / después

| Momento | Comando | Resultado |
|---|---|---|
| Línea base | `TEST_DATABASE_URL=... npm test` | 9 pruebas, 9 OK |
| Tras escribir la suite, antes de arreglar | `node --test test/qa-hostil.test.js` | 18 pruebas, 13 OK, **5 fallan** (la 6.ª, migración concurrente, se añadió después y falló también) |
| Final con BD | `npm test` | **30 pruebas, 30 OK, 0 fallos** (25 ejecuciones consecutivas sin fallos) |
| Final sin BD | `env -u TEST_DATABASE_URL npm test` | 20 pruebas, 17 OK, 3 omitidas (las que requieren PostgreSQL) |

## Hallazgos

| # | Sev. | Hallazgo (prueba roja) | Arreglo |
|---|---|---|---|
| 1 | Media | Ruta con porcentaje mal codificado (`/api/carrito/%E0%A4%A`) y `Content-Type` con charset desconocido devolvían **500** "Error interno" (errores 4xx de Express/body-parser reclasificados como 500). | `src/app.js`: errores de cliente no-ApiError con status 4xx devuelven 400 "Solicitud incorrecta". |
| 2 | Media | BD colgada/cortada: el error del pool `timeout exceeded when trying to connect` (sin `code`) devolvía **500** en vez de 503. También `Connection terminated...`, 53300, 57P03. | `src/app.js`: `isDatabaseUnavailable` reconoce códigos y mensajes del driver, y `AggregateError` con ECONNREFUSED. |
| 3 | Media | Migración ejecutada en paralelo sobre BD virgen (varias réplicas) fallaba con `duplicate key ... pg_type_typname_nsp_index` (7 de 8). | `migrations/001-carrito.sql`: `pg_advisory_xact_lock` tras `BEGIN`. Dos ejecuciones seguidas y 8 paralelas OK. |
| 4 | Baja | Repetición idempotente devolvía el JSON con otro orden de claves que la primera respuesta (jsonb reordena). | `src/store.js`: `canonical()`/`lines()` reconstruyen la forma del contrato en repetición de `agregar`, `prepararCheckout`, `confirmar` y `cancelar`. |
| 5 | Baja | Con `usuario_id` inválido y sin credencial se respondía 422 antes que 401 (orden validación/autenticación). | `src/app.js`: GET y `agregar` autentican primero (401/403) y validan el UUID después (422). |

## Ataques que NO encontraron fallo (cubiertos por pruebas)

- JSON malformado, arreglos/primitivos/`null`, campos extra (`precio`, `usuario_id`, `__proto__`), tipos erróneos de `cantidad`, `1e400`, 0, negativos, > 2^31-1: 400/422, nunca 5xx.
- UUID v1/v5/nil/con llaves/sin guiones en ruta, cuerpo y `Idempotency-Key`: 422.
- Cuerpo de 20 kB y 5 MB: 400/4xx. Respuestas de error sin stack traces.
- JWT: `alg=none`, HS256 con clave pública como secreto, RS384/PS256, otra clave, payload alterado, expirado, `iat` futuro, vigencia de 2 h, sin `exp`/`sub`, `sub` no v4, rol inválido, emisor/audiencia ajenos, truncado, sin firma, esquema Basic: todos 401.
- Titularidad: usuario A sobre B en GET y `agregar` = 403 sin tocar la BD; admin accede.
- `X-Service-Token` ausente, vacío, parcial, mayúsculas, de otro par, enviado como Bearer; servicio sin token configurado: 401.
- Concurrencia con PostgreSQL real: 30 peticiones misma clave y cuerpo, un solo efecto; misma clave con cuerpos distintos, un 200 y 19 x 409; 40 claves distintas suman 40; tope de disponibilidad 5 con 20 carreras da exactamente 5; misma clave desde dos carritos de un admin, un solo efecto.
- Inyección SQL en ruta, cuerpo y cabeceras: 422; esquema intacto (consultas parametrizadas).
- `/health` 200 y `/ready` 503 con BD caída (puerto cerrado y host que no responde) y sin migración; 200 tras migrar.

## Comandos

```sh
docker run --rm -d --name mojarra-pg-carrito -p 55435:5432 --tmpfs /var/lib/postgresql/data -e POSTGRES_PASSWORD=<aleatoria> postgres:17
DB_HOST=127.0.0.1 DB_PORT=55435 DB_DATABASE=postgres DB_USERNAME=postgres DB_PASSWORD=<aleatoria> node src/migrate.js   # 2 veces seguidas: OK
TEST_DATABASE_URL=postgres://postgres:<aleatoria>@127.0.0.1:55435/postgres npm test
docker stop mojarra-pg-carrito
```

## Pendientes / NO VERIFICADO

- **NO VERIFICADO**: `docker build` del Dockerfile (prohibido por la tarea; disco raíz casi lleno) y despliegue en Compose/Kubernetes.
- **NO VERIFICADO**: el protocolo experimental `/checkout/*` por HTTP bajo ataque concurrente (solo las pruebas existentes; la capa de almacenamiento sí está cubierta).
- Diseño (Media): `available()` (2 llamadas HTTP, 1 s cada una) se ejecuta dentro de la transacción con el candado del carrito; un Productos/Inventario lento retiene conexiones (pool de 10) y degrada a 503. Sacar la consulta de la transacción rompería la garantía de tope bajo carrera; requiere decisión del equipo.
- `DELETE /vaciar` responde 409 si el carrito tiene artículos (comportamiento documentado en README, pendiente de acordar con Pedidos).
- `carrito_adiciones` crece sin límite (sin expiración de claves de idempotencia).
- Rate limiting: resuelto, ver 'Decisiones del equipo (rate limiting)'. Sigue sin exigirse longitud mínima a `SERVICE_TOKEN_PEDIDOS_CARRITO` (solo se rechaza vacío/`REPLACE_ME`).
- Tamaño de cuerpo: el límite de 16 kB/400 se sustituyó por 256 KiB/413 (ver sección de decisiones del equipo).
- Importes MXN: este servicio no recibe importes; el rechazo de campos extra (`precio`) está probado, pero la validación de decimales MXN no aplica aquí.

## Nota de reverificación
Las pruebas con base de datos exigen aplicar antes `node src/migrate.js` sobre la BD de prueba. Sin migrar, 9 de las 30 fallan (comprobado en una BD vacía); con la migración aplicada pasan las 30.

## Contrato 1.1.0

Entorno: PostgreSQL 17 temporal `mojarra-pg-carrito2` (puerto 55444, tmpfs, detenido al final), `node src/migrate.js` aplicado dos veces antes de cada corrida, con el rol `usr_carrito` (sin CREATEDB, dueño de su BD) y con superusuario. No se tocó `docs/api` ni otros servicios.

### Cambios

- `migrations/002-contrato-1-1.sql` (nueva, idempotente; la 001 no se editó): `carrito_items.linea_id uuid` único (las filas existentes reciben su propio UUID) y tabla `carrito_operaciones` (identidad, Idempotency-Key, operación, hash, resultado). `src/migrate.js` aplica todas las migraciones en orden.
- `GET` y `agregar`: `version` (inicial 0) y `linea_id` por artículo. `agregar` conserva `linea_id` mientras exista la línea.
- Nuevos `iniciar`, `finalizar`, `liberar` y `vaciar` (ahora vacía de verdad; antes devolvía 409 con artículos), todos con `Idempotency-Key` y solo `X-Service-Token`.
- Eliminado el protocolo experimental: rutas `/checkout/*`, bandera `ENABLE_DRAFT_CART_CHECKOUT` y `test/draft-checkout.test.js`. Se conserva lo probado: un snapshot activo por carrito, snapshot original en repeticiones, confirmación idempotente y preservación de adiciones posteriores. Cambia: el segundo checkout activo ahora es 409 (antes 503), por contrato.
- Bloqueos en orden fijo (clave de idempotencia, pedido, fila del carrito) para evitar interbloqueos.

### Resultado antes / después

| Momento | Resultado |
|---|---|
| Línea base (superusuario) | 30 pruebas, 30 OK. Con `usr_carrito`: 27 OK y 3 omitidas (requieren CREATEDB) |
| Pruebas nuevas `test/contrato-1-1.test.js`, antes del código | 18 pruebas, **18 fallan** |
| Tras implementar (superusuario, 3 corridas) | **46 pruebas, 46 OK**, 0 omitidas |
| Con `usr_carrito` | 43 contadas, 42 OK, 0 fallos, 1 omitida (migración sobre BD temporal: requiere CREATEDB) |
| Sin BD (`env -u TEST_DATABASE_URL npm test`) | 23 pruebas, 21 OK, 0 fallos, 2 omitidas |

Las 30 previas siguen cubiertas salvo las 2 del protocolo experimental, sustituidas por pruebas del contrato 1.1.0. Se adaptaron al contrato las pruebas de `vaciar` (app y QA hostil, ahora con Idempotency-Key y `clear`) y las de `store.test.js` (nueva API `start/finish/release`) sin debilitar aserciones.

Cubierto con PostgreSQL real: aceptación (2 en compra + 1 durante el pago: aprobado queda 1, cancelado 3, repetir finalizar sigue en 1), versión/linea_id, `linea_id` nuevo tras retirar una línea, pedido ajeno a otro carrito, liberar sin snapshot, vaciar con checkout activo, idempotencia por clave (misma clave y otra solicitud: 409), concurrencia (12 agregar + 4 finalizar en paralelo, 5 rondas: sin pérdidas ni duplicados; 6 iniciar simultáneos del mismo pedido; mismo pedido desde dos usuarios sin 5xx) y migración 002 sobre datos existentes, repetida y en paralelo.

### JSON para Pedidos

Todas las llamadas: cabeceras `X-Service-Token: <token Pedidos->Carrito>`, `Idempotency-Key: <uuid estable por operación>`, `Content-Type: application/json`. Las respuestas exitosas son `{"success":true,"message":"OK","data":...}`; los errores `{"success":false,"message":"...","errors":{}}`. `version` y `version_original` son enteros JSON (no cadenas). Orden de validación: 401 (credencial), 422 (usuario, clave, cuerpo), 409 (estado). Una misma clave con otra solicitud devuelve 409.

`GET /api/carrito/{usuario_id}` (y `data` de `agregar`, `finalizar`, `liberar`, `vaciar`):

```json
{"success":true,"message":"OK","data":{"usuario_id":"U","items":[{"producto_id":"P","cantidad":2,"linea_id":"L"}],"version":1}}
```

`POST /api/carrito/{usuario_id}/iniciar`, solicitud y `data`:

```json
{"pedido_id":"O","version_original":1}
{"pedido_id":"O","version_original":1,"items":[{"producto_id":"P","cantidad":2,"linea_id":"L"}]}
```

`POST /api/carrito/{usuario_id}/finalizar`, solicitud (items exactos del snapshot, incluido `linea_id`) y `data` (carrito resultante; la versión puede superar `version_original`; con 2 comprados y 1 añadida durante el pago):

```json
{"pedido_id":"O","version_original":1,"items":[{"producto_id":"P","cantidad":2,"linea_id":"L"}]}
{"usuario_id":"U","items":[{"producto_id":"P","cantidad":1,"linea_id":"L"}],"version":3}
```

`POST /api/carrito/{usuario_id}/liberar`, solicitud y `data` (carrito sin cambios):

```json
{"pedido_id":"O"}
{"usuario_id":"U","items":[{"producto_id":"P","cantidad":3,"linea_id":"L"}],"version":2}
```

`DELETE /api/carrito/{usuario_id}/vaciar` (sin cuerpo; solo fuera de checkout) devuelve `data` `{"usuario_id":"U","items":[],"version":N}`.

Códigos: 200; 401 token interno ausente o inválido (un JWT no sirve); 422 UUID, clave o cuerpo inválidos (campos extra, `items` vacío o con `linea_id` repetido); 409 versión distinta, carrito vacío, otro checkout activo, pedido de otro carrito, snapshot inexistente o incompatible, checkout liberado o ya finalizado, clave reutilizada; 503 BD no disponible.

Decisiones a confirmar con Pedidos: `finalizar` sin snapshot previo responde 409 (el YAML no distingue 404); `iniciar` repetido de un pedido ya finalizado devuelve el snapshot original (solo lectura), de uno liberado 409; el cierre sin snapshot de `liberar` se guarda como un checkout cancelado vacío.

### Pendientes / NO VERIFICADO

- **NO VERIFICADO**: `docker build`, integración real con Pedidos y el proxy (que debe bloquear las rutas internas).
- Snapshots pendientes creados con el protocolo experimental antes de la 002 no traen `linea_id`: su `finalizar` daría 409 y deberían liberarse. Resultados de `agregar` guardados antes de 1.1.0 se repiten con el estado actual del carrito.
- `carrito_operaciones` y `carrito_adiciones` crecen sin expiración.
- La suite no valida las respuestas contra el YAML con un validador OpenAPI; se comprobó a mano la forma de `data`.

## Decisiones del equipo (rate limiting)

Decisión del integrante 1: límites configurables por entorno, en memoria por proceso. Implementación en `src/limits.js` (config, contador de ventana fija de 60 s) y `src/app.js` (aplicación tras autenticar).

| Variable | Defecto | Alcance |
|---|---|---|
| `RATE_LIMIT_CONSULTA_POR_MIN` | 120 | GET con JWT, por `sub` |
| `RATE_LIMIT_MUTACION_POR_MIN` | 30 | `agregar` con JWT, por `sub` |
| `RATE_LIMIT_INTERNA_POR_MIN` | 300 | identidad de servicio (X-Service-Token válido): iniciar/finalizar/liberar/vaciar y GET interno, un solo cupo |
| `MAX_JSON_BYTES` | 262144 | cuerpo JSON; exceso => 413 |
| `RATE_LIMIT_CHECKOUT_POR_MIN` | n/a | no aplica a Carrito; se ignora |

Comportamiento: exceso => 429 con `Retry-After` (segundos restantes de la ventana) y `{success:false,message,errors:{}}`. Se autentica primero: sin credencial/credencial inválida sigue 401 (y 403 sin permiso); esos fallos cuentan contra la IP (cupo de consultas), así que una IP que insiste sin autenticarse acaba en 429. `/health` y `/ready` exentos. Valores de entorno inválidos (no entero positivo) abortan el arranque.

Cambios en pruebas existentes (justificados):
- `qa-hostil` 'cuerpos enormes...': esperaba 400 para 20 kB; con 256 KiB ese cuerpo llega a validación (422), y se añadieron 300 kB => 413 y 5 MB => 413 (antes solo "4xx").
- Todas las suites importan `test/env-limites-altos.js` (límites de 1.000.000/min) para no chocar con los cupos; `test/limites.test.js` (15 pruebas nuevas) usa límites bajos propios.

### Resultado antes / después

| Momento | Comando | Resultado |
|---|---|---|
| Línea base (BD PG17 `mojarra-pg-carrito3`, puerto 55454, rol NOSUPERUSER/NOCREATEDB) | `TEST_DATABASE_URL=... npm test` (5 suites previas) | 45 pruebas: 44 OK, 0 fallos, 1 omitida (migración 002 en BD temporal: el rol no tiene CREATEDB) |
| Rojo | `node --test test/limites.test.js` antes de código | falla al importar `src/limits.js` (inexistente); no se ejecutó ninguna prueba |
| Final con BD | `npm test` (3 ejecuciones consecutivas) | 60 pruebas: 59 OK, 0 fallos, 1 omitida (la misma) |
| Final sin BD | `npm test` sin `TEST_DATABASE_URL` | 40 pruebas: 38 OK, 0 fallos, 2 omitidas |

### Pendientes / NO VERIFICADO

- Con varias réplicas el límite es por instancia (no hay almacén compartido); el límite efectivo es N x valor.
- Sin `trust proxy`, `req.ip` detrás de proxy/Ingress es la IP del proxy: el límite por IP de peticiones sin autenticar sería compartido por todos los clientes. Decidir con el equipo la configuración de proxies de confianza; no se tocó.
- Un cuerpo > máximo recibe 413 antes de autenticar (lo aplica el analizador de JSON, previo a la autenticación); el 429 sí va después de autenticar.
- El contrato (`docs/api/carrito.yaml`) declara 429 pero no 413 ni `Retry-After`; no se modificó `docs/api`.
- Ventana fija: permite ráfagas de hasta 2x el límite en el cambio de ventana.
- El contador no se probó bajo carga real ni con proxy; `docker build` y Compose NO VERIFICADOS.
- Idempotencia: sin expiración ni borrado de `carrito_operaciones`/`carrito_adiciones`; decisión de MVP, no implementado.
- Se ejecutó `npm ci` (crea `node_modules/` en el servicio; no hay `.gitignore` local).
