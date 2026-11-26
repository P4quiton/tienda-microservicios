# API de Pedidos

Laravel 13, PHP 8.5 y PostgreSQL 17. Puerto 8006. Consulta el contrato en [pedidos.yaml](../docs/api/pedidos.yaml).

## Ejecución

1. Aprovisiona una base PostgreSQL para Pedidos y configura las variables de `.env.example`.
2. Ejecuta `composer install` y `php artisan migrate`.
3. Ejecuta `PHP_CLI_SERVER_WORKERS=4 php artisan serve --host=0.0.0.0 --port=8006 --no-reload`.

Los cuatro procesos permiten responder la consulta interna de Envíos mientras la solicitud de checkout sigue abierta. Para desarrollo integrado, construye la imagen con `docker build -t api-pedidos:local .`. Ejecuta las migraciones desde esa misma imagen con `php artisan migrate --force` después de configurar su conexión. `GET /health` comprueba el proceso y `GET /ready` comprueba acceso a la tabla del servicio.

## Checkout

PostgreSQL conserva el snapshot, la versión del carrito, la clave idempotente y el último paso confirmado. Ante un resultado incierto, una repetición con la misma clave continúa desde el paso pendiente. Los identificadores se reutilizan en las llamadas que admiten idempotencia. Se calculan importes en centavos enteros y se entregan como cadenas decimales MXN.

La integración HTTP provisional del carrito versionado se habilita únicamente en desarrollo local con `ENABLE_DRAFT_CART_CHECKOUT=true`, `API_CARRITO_URL` y `SERVICE_TOKEN_PEDIDOS_CARRITO`. Permanece deshabilitada por defecto mientras el equipo acuerda el contrato oficial. La preparación ocurre después de persistir el snapshot y antes de reservar inventario; la cancelación se reintenta tras rechazos conocidos, no ante pagos inciertos. La ruta PATCH requiere que el equipo designe una identidad de escritura específica. Pagos y Envíos tienen acceso interno de lectura.

## Pruebas

Ejecuta `composer test` con PHP 8.5. Para las comprobaciones de recuperación, configura una base PostgreSQL **exclusiva para pruebas** y habilita `TEST_POSTGRES=1`.
