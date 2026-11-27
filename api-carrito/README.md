# API de Carrito

Servicio Node.js 24, Express 5 y PostgreSQL 17. Escucha en el puerto 8005. El contrato HTTP está en [carrito.yaml](../docs/api/carrito.yaml).

## Desarrollo

Copia `.env.example` a `.env`. Configura la base de datos `db_carrito` y el rol `usr_carrito`, la ubicación de la clave pública RSA de Usuarios y el secreto interno exclusivo de Pedidos a Carrito. Si ejecutas el proceso fuera de la red de Compose, ajusta los nombres de host de PostgreSQL, Productos e Inventario.

```sh
npm ci
node --env-file=.env src/migrate.js
node --env-file=.env src/server.js
```

`src/migrate.js` aplica en orden todas las migraciones de `migrations/` (`001-carrito.sql`, `002-contrato-1-1.sql`...); son idempotentes y se pueden ejecutar varias veces o en paralelo. Crean las tablas del servicio. Se ejecuta como paso de despliegue antes de iniciar las réplicas. `/health` comprueba el proceso y `/ready` verifica que la base de datos y la tabla de carritos estén disponibles.

```sh
docker build -t tienda-api-carrito:dev .
```

Para desplegar la imagen, conecta el contenedor a la red de PostgreSQL y de las demás APIs. Inyecta las variables de entorno y monta la clave pública en la ubicación indicada. Ejecuta `node src/migrate.js` en un contenedor antes de iniciar el servicio.

## Carrito y checkout (contrato 1.1.0)

`GET /api/carrito/{usuario_id}` (titular/admin o Pedidos) devuelve `{usuario_id, items:[{producto_id, cantidad, linea_id}], version}`. La versión inicial es 0 y es monotónica por usuario (también al vaciar). `linea_id` identifica una generación de línea: `agregar` incrementa cantidad y versión de forma atómica y lo conserva; si la línea se elimina y se vuelve a crear recibe otro. `agregar` valida producto y disponibilidad orientativa; la reserva real ocurre en Inventario durante el checkout. Se puede agregar durante un checkout: la disponibilidad orientativa solo cuenta las unidades fuera del snapshot activo.

Operaciones internas (solo Pedidos, `X-Service-Token` del par Pedidos->Carrito, `Idempotency-Key` UUID obligatorio; no se exponen por el proxy):

| Ruta | Cuerpo | Efecto |
|---|---|---|
| `POST /api/carrito/{usuario_id}/iniciar` | `{pedido_id, version_original}` | Bloquea el carrito, verifica la versión y crea el snapshot inmutable. 409 si la versión cambió, el carrito está vacío u otro checkout está activo. Repetir el mismo pedido devuelve el snapshot original. |
| `POST .../finalizar` | `{pedido_id, version_original, items}` | Retira del carrito las cantidades del snapshot por `linea_id`, conserva lo agregado después, incrementa la versión y registra el pedido. Repetir devuelve el resultado registrado sin nuevos descuentos. 409 si el snapshot no existe, no coincide o fue liberado. |
| `POST .../liberar` | `{pedido_id}` | Cierra el checkout sin modificar artículos. Sin snapshot registra el cierre y el inicio tardío del mismo pedido da 409. 409 si ya fue finalizado. |
| `DELETE .../vaciar` | sin cuerpo | Vacía el carrito; 409 con checkout activo. Sube la versión solo si cambió el contenido. |

La misma `Idempotency-Key` con la misma solicitud devuelve el resultado registrado; con otra solicitud, 409. Un solo checkout activo por carrito. Los JSON exactos están en la sección "Contrato 1.1.0" de [QA-INFORME.md](QA-INFORME.md). El protocolo experimental `/checkout/*` y la variable `ENABLE_DRAFT_CART_CHECKOUT` se eliminaron.

## Límites de uso

Configurables por entorno (ver `.env.example`), en memoria por proceso con ventana fija de 60 s. **Con varias réplicas el límite es por instancia.**

| Variable | Defecto | Aplica a |
|---|---|---|
| `RATE_LIMIT_CONSULTA_POR_MIN` | 120 | GET con JWT, por `sub` |
| `RATE_LIMIT_MUTACION_POR_MIN` | 30 | `agregar` con JWT, por `sub` |
| `RATE_LIMIT_INTERNA_POR_MIN` | 300 | identidad de servicio (`X-Service-Token` válido): operaciones internas y GET interno |
| `MAX_JSON_BYTES` | 262144 | tamaño máximo del cuerpo JSON (antes 16 kB con 400; ahora 413) |

`RATE_LIMIT_CHECKOUT_POR_MIN` no aplica a Carrito. Exceso => 429 con `Retry-After` y el formato de error del contrato. Primero se autentica (sin credencial sigue 401) y después se limita; los fallos de autenticación cuentan por IP. `/health` y `/ready` están exentos. Un valor inválido impide el arranque.

Idempotencia: `carrito_operaciones` y `carrito_adiciones` no expiran ni se borran. Es una decisión de MVP; la retención queda pendiente.

## Pruebas

```sh
npm test
```

Las pruebas HTTP usan una clave de prueba creada en memoria. Para ejecutar también las pruebas de idempotencia, concurrencia, snapshot y contrato 1.1.0, usa una base de pruebas desechable de PostgreSQL 17. Aplica primero las migraciones (`node src/migrate.js`) con la configuración de esa base, define `TEST_DATABASE_URL` en el entorno y ejecuta `npm test`.

Las suites importan `test/env-limites-altos.js` para usar límites altos; solo `test/limites.test.js` usa límites bajos.
