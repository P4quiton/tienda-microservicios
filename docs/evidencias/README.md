# Evidencias del frontend sobre Docker Compose

- Fecha de captura: 2026-11-27
- URL: `http://127.0.0.1:4200` (frontend real detrás de Nginx; modo API predeterminado).
- Las capturas fueron tomadas con Chrome headless por Chrome DevTools Protocol. Los datos visibles vienen de los servicios HTTP reales.

## Capturas disponibles

| Archivo | Contenido |
|---|---|
| `01-catalogo.png` | Catálogo con productos servidos por Productos/Inventario, buscador y filtros de categoría visibles. |
| `02-detalle.png` | Detalle real del Cuaderno de notas, disponibilidad de Inventario y reseñas de Reseñas. |
| `03-checkout.png` | Checkout autenticado con Cuaderno en el carrito, cotización real de envío y formulario de dirección. |
| `04-confirmacion.png` | Confirmación de compra desde la UI con pedido pagado, pago simulado e identificador de guía. |
| `05-mis-pedidos.png` | Historial autenticado con el pedido, estado pagado y guía de rastreo. |

Las cinco vistas se capturaron desde Chrome headless en la misma sesión SPA. La sesión de autenticación se inició mediante el formulario real de acceso; la compra se completó desde checkout.

## Reproducción

Con Docker Compose ya levantado, comprobar el flujo de API real (10 escenarios) con:

```sh
E2E_EMAIL='correo-nuevo@example.test' E2E_PASSWORD='contraseña-de-prueba' \
E2E_PRODUCT_ID='uuid-v4-con-existencias' ./e2e/run.sh
```

El arnés E2E registra usuarios, reseña y compra de prueba; modifica datos compartidos y descuenta una unidad de inventario. Estas capturas adicionales registraron un usuario nuevo y completaron otra compra real con pago simulado. La sesión de la UI vive en memoria, así que hay que conservar el contexto SPA durante el flujo; recargar la ruta protegida requiere volver a iniciar sesión.
