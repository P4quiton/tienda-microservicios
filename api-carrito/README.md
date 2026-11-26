# API de Carrito

Servicio Node.js 24, Express 5 y PostgreSQL 17. Escucha en el puerto 8005. El contrato HTTP está en [carrito.yaml](../docs/api/carrito.yaml).

## Desarrollo

Copia `.env.example` a `.env`. Configura la base de datos `db_carrito` y el rol `usr_carrito`, la ubicación de la clave pública RSA de Usuarios y el secreto interno exclusivo de Pedidos a Carrito. Si ejecutas el proceso fuera de la red de Compose, ajusta los nombres de host de PostgreSQL, Productos e Inventario.

```sh
npm ci
node --env-file=.env src/migrate.js
node --env-file=.env src/server.js
```

La migración crea las tablas del servicio. Se ejecuta como paso de despliegue antes de iniciar las réplicas. `/health` comprueba el proceso y `/ready` verifica que la base de datos y la tabla de carritos estén disponibles.

```sh
docker build -t tienda-api-carrito:dev .
```

Para desplegar la imagen, conecta el contenedor a la red de PostgreSQL y de las demás APIs. Inyecta las variables de entorno y monta la clave pública en la ubicación indicada. Ejecuta `node src/migrate.js` en un contenedor antes de iniciar el servicio.

## Carrito y checkout

La consulta admite el JWT del titular o admin, o la identidad interna de Pedidos. Al agregar, el servicio valida el producto y la disponibilidad orientativa y usa la clave de idempotencia para devolver el resultado previo de la misma solicitud. La reserva real se realiza en Inventario durante el checkout.

El almacenamiento permite preparar un snapshot inmutable por pedido y confirmar o cancelar su aplicación de forma transaccional. El cliente puede seguir agregando artículos: la disponibilidad orientativa se compara con las unidades fuera del snapshot pendiente, porque Inventario descuenta las reservas de sus disponibles. La reserva definitiva se comprueba en Inventario durante la siguiente compra. La confirmación conserva las cantidades añadidas después del snapshot, incluso en un reintento del mismo pedido. Para evitar que dos pedidos consuman las mismas cantidades, el almacenamiento admite un solo snapshot en curso por carrito; preparar otro snapshot vigente devuelve 503 temporal, mientras una versión o artículos desactualizados devuelven 409.

Hay un protocolo HTTP experimental de snapshot, desactivado por defecto y pendiente de acordarse en OpenAPI. Para pruebas locales exclusivamente, define `ENABLE_DRAFT_CART_CHECKOUT=true`: Pedidos consulta `GET /api/carrito/{usuario_id}/checkout` y envía `{pedido_id, version, items}` a `POST /api/carrito/{usuario_id}/checkout/preparar`, `/confirmar` o `/cancelar`. Las cuatro rutas exigen `X-Service-Token` de Pedidos; la versión y los artículos deben coincidir con el snapshot. El `DELETE /api/carrito/{usuario_id}/vaciar` existente exige la identidad de Pedidos y devuelve `200` para carrito vacío. Devuelve `409` y conserva un carrito con artículos hasta que se pueda indicar la compra confirmada de forma segura.

## Pruebas

```sh
npm test
```

Las pruebas HTTP usan una clave de prueba creada en memoria. Para ejecutar también la prueba de idempotencia, concurrencia y snapshot, usa una base de pruebas desechable de PostgreSQL 17. Aplica primero la migración con la configuración de esa base, define `TEST_DATABASE_URL` en el entorno y ejecuta `npm test`.
