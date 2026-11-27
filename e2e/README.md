# E2E contra Docker Compose

El modo predeterminado prueba por HTTP los **ocho servicios reales** levantados por Docker Compose: Usuarios, Productos, Envíos, Inventario, Carrito, Pedidos, Pagos y Reseñas. No inicia ni detiene contenedores y no usa stubs. El resumen enumera cada escenario como `OK` o `FAIL`; el código de salida es distinto de cero si falta configuración, no responde un servicio o falla una aserción.

## Ejecución

Desde la raíz del monorepo, con Compose ya levantado:

```sh
E2E_EMAIL='correo-de-prueba@example.test' E2E_PASSWORD='contraseña-de-prueba' \
E2E_PRODUCT_ID='uuid-v4-de-producto-existente' ./e2e/run.sh
```

`E2E_EMAIL` debe ser un correo nuevo: el escenario registra esa cuenta mediante la API de Usuarios y no reutiliza cuentas. `E2E_PASSWORD` se envía solo a Usuarios; el script nunca la muestra. `E2E_PRODUCT_ID` debe ser UUID v4 existente en Productos y con al menos una unidad disponible en Inventario. El test registra por API un segundo usuario con alias derivado del correo configurado. Antes de la compra, el segundo usuario agrega al carrito la disponibilidad observada completa; la compra del primer usuario (1 unidad) deja ese carrito sin stock suficiente al hacer checkout. No necesita una ruta de siembra ni muta inventario directamente.

Variables opcionales:

| Variable | Valor predeterminado | Uso |
|---|---|---|
| `USUARIOS_URL` ... `RESENAS_URL` | `http://127.0.0.1:8001` ... `:8008` | Sustituir individualmente el origen del servicio; por ejemplo, usar Nginx. |
| `E2E_NOMBRE` | `Prueba E2E` | Nombre del usuario que registra la prueba. |
| `E2E_CODIGO_POSTAL` | `06600` | Código para cotización y dirección de compra. |

## Escenarios incluidos

1. Readiness HTTP 200 en los ocho servicios.
2. Registro por API y login con JWT RS256 emitido por Usuarios.
3. Listado del catálogo y disponibilidad en Inventario para el producto seleccionado.
4. Crear una reseña autenticada y verificarla en el listado público.
5. Cotizar envío y rastrear la guía generada por la compra.
6. Agregar al carrito usando `Idempotency-Key` UUID v4.
7. Crear un segundo usuario y preparar un carrito competidor antes de comprar.
8. Compra aprobada: pedido pagado, comprobante aprobado, stock descontado, carrito vacío y guía rastreable.
9. Repetir la misma compra con la misma clave y verificar cuerpo idéntico.
10. Falta de stock: HTTP 409 de Inventario, pedido cancelado, sin comprobante y carrito conservado. El servicio Pedidos expone actualmente el mensaje `Inventario insuficiente`, no un campo de código `stock_insuficiente`.
11. Solicitud al carrito sin token: HTTP 401.

El escenario opcional de exceso de límite 429 no se ejecuta: depende de los límites configurados y podría consumir cuota de la instancia compartida. `Retry-After` tampoco se comprueba.

## Modo legado con stubs

El arnés anterior, que arranca servicios de prueba y sustituye Productos e Inventario, sigue disponible explícitamente:

```sh
./e2e/run.sh --stubs
```

Ese modo es independiente del modo Compose real y conserva sus requisitos previos documentados en `run-stubs.sh` y `servicios.sh`.
