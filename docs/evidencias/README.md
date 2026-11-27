# Evidencias del frontend sobre Docker Compose

- Fecha de captura: 2026-11-27
- URL: `http://127.0.0.1:4200` (frontend real detrás de Nginx; modo API predeterminado).
- Las capturas fueron tomadas con Chrome headless por Chrome DevTools Protocol. Los datos visibles vienen de los servicios HTTP reales.

## Capturas disponibles

| Archivo | Contenido |
|---|---|
| `01-catalogo.png` | Catálogo con productos servidos por Productos/Inventario, buscador y filtros de categoría visibles. |
| `02-detalle.png` | Detalle real del Cuaderno de notas, disponibilidad de Inventario y reseñas de Reseñas. |

## Capturas pendientes

No se generaron `03-checkout.png`, `04-confirmacion.png` ni `05-mis-pedidos.png`. El E2E real sí creó un pedido pagado con guía, pero la sesión del frontend guarda el JWT solo en memoria. La automatización CDP perdió la sesión al cambiar de ruta protegida y el checkout redirigió a `/acceso`; por eso no se presentan pantallas de acceso como si fueran checkout o confirmación.

## Reproducción

Con Docker Compose ya levantado, comprobar el flujo de API real (10 escenarios) con:

```sh
E2E_EMAIL='correo-nuevo@example.test' E2E_PASSWORD='contraseña-de-prueba' \
E2E_PRODUCT_ID='uuid-v4-con-existencias' ./e2e/run.sh
```

El arnés registra usuarios, reseña y compra de prueba; modifica datos compartidos y descuenta una unidad de inventario. Para volver a tomar las dos vistas disponibles, iniciar Chrome headless con depuración remota, abrir `http://127.0.0.1:4200/catalogo` y guardar las páginas en esta carpeta. Las capturas pendientes requieren completar la autenticación UI y mantener el contexto SPA durante todo el flujo.
