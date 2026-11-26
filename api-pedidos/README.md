# API de Pedidos

Laravel 13, PHP 8.5 y PostgreSQL 17. Puerto 8006. Consulta el contrato en [pedidos.yaml](../docs/api/pedidos.yaml).

## Ejecución

1. Aprovisiona una base PostgreSQL para Pedidos y configura las variables de `.env.example`.
2. Ejecuta `composer install` y `php artisan migrate`.
3. Ejecuta `PHP_CLI_SERVER_WORKERS=4 php artisan serve --host=0.0.0.0 --port=8006 --no-reload`.

Los cuatro procesos permiten responder la consulta interna de Envíos mientras la solicitud de checkout sigue abierta. Para desarrollo integrado, construye la imagen con `docker build -t api-pedidos:local .`. Ejecuta las migraciones desde esa misma imagen con `php artisan migrate --force` después de configurar su conexión. `GET /health` comprueba el proceso y `GET /ready` comprueba acceso a la tabla del servicio.

## Checkout (contrato 1.1.0)

`POST /api/pedidos` ya no depende de ningún interruptor: el protocolo con Carrito está acordado en `carrito.yaml`. Si falta la URL o el `SERVICE_TOKEN_*` de un servicio, el checkout responde 503 controlado.

Orden: lee el carrito (versión entera) -> **persiste el pedido pendiente con su `Idempotency-Key`** -> `iniciar` (snapshot versionado con `linea_id`; 409 si la versión cambió u otro checkout está activo) -> recalcula importes con Productos y Envíos -> reserva en Inventario -> Pagos -> confirma reserva -> genera guía -> `finalizar` el carrito (con `version_original` y `linea_id`). Un pago rechazado devuelve 201 con estado `cancelado` y libera la reserva y el carrito. Resultado incierto o finalización pendiente: 503; repetir la misma clave devuelve el mismo pedido. Un pedido cobrado nunca se cancela. Un pago ambiguo se resuelve con `GET /api/pagos/pedido/{id}` o reintentando la misma clave, nunca asumiendo rechazo.

Solo hay un checkout activo por usuario (índice único parcial en PostgreSQL). Las claves por operación son estables (`Pedido::clave()`): Inventario reservar y Pagos usan el id del pedido; el resto, un UUIDv5 derivado de él. El avance de cada paso, los intentos, el próximo intento y el último error se guardan en `pedidos`.

### Recuperación sin cliente

`php artisan pedidos:recuperar [--limite=50]` reanuda los pasos pendientes con las mismas claves, respetando el backoff (5 s duplicando hasta 300 s) y un bloqueo advisory por usuario. Está en el scheduler (`routes/console.php`, cada minuto). La imagen lo ejecuta al arrancar y deja `php artisan schedule:work` en segundo plano; fuera de Docker, programa `* * * * * php artisan schedule:run`. El scheduler usa `CACHE_STORE=file`. Los pedidos que siguen fallando se conservan con `ultimo_error` para revisión; no hay reembolso ni expiración de reservas (MVP).

### PATCH /api/pedidos/{id}/estado

Solo Envíos con `SERVICE_TOKEN_ENVIOS_PEDIDOS` (comparación en tiempo constante) y `Idempotency-Key` UUID. Únicamente `pagado -> enviado`; repetir `enviado` responde 200 sin cambios; cualquier otra transición, 409. Los tokens de otros pares reciben 403; sin token válido o con JWT, 401. Pedidos pasa `pendiente -> pagado/cancelado` por su cuenta. Pagos y Envíos tienen además acceso interno de lectura (`GET /api/pedidos/{id}`).

## Pruebas

Ejecuta `composer test` con PHP 8.5. Los servicios externos se simulan con `Http::fake` (`tests/Support/ServiciosFalsos.php`). Para las comprobaciones de recuperación, configura una base PostgreSQL **exclusiva para pruebas** y habilita `TEST_POSTGRES=1`.
