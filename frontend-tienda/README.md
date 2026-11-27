# Nébula · frontend-tienda

Tienda web en Angular 21 con catálogo, detalle, checkout, historial y acceso. La interfaz usa el sistema visual Liquid Glass de Nébula y consume los contratos REST mediante rutas relativas `/api/...`. Al abrir o recargar la aplicación presenta una breve animación de entrada del emblema extruido en Three.js; respeta `prefers-reduced-motion` y ofrece el SVG local como respaldo cuando WebGL no está disponible.

## Desarrollo local

```bash
npm ci
npm start
```

Abre `http://localhost:4200/`. El modo predeterminado usa datos simulados. Para usar los servicios HTTP abre `http://localhost:4200/?mode=api`; la preferencia se conserva en `sessionStorage` durante la sesión de esa pestaña, incluso al cambiar de ruta o recargar. Para volver a mocks, abre `http://localhost:4200/?mode=mock`.

En modo API, Angular usa `proxy.conf.json` durante desarrollo. En Docker, Nginx enruta las rutas públicas/protegidas permitidas a los servicios internos y bloquea las operaciones internas de Pedidos. El token de servicio nunca se envía desde el navegador.

La sesión de usuario se conserva solo en memoria. Al recargar la página se debe iniciar sesión de nuevo; nunca se guardan contraseñas ni JWT en URL, `localStorage` o `sessionStorage`.

## Vistas

| Ruta | Funciones |
|---|---|
| `/catalogo` | Búsqueda, categorías derivadas del catálogo, orden, calificaciones y disponibilidad. |
| `/producto/:id` | Detalle, disponibilidad, reseñas públicas y formulario para usuarios con sesión. |
| `/checkout` | Carrito, cotización de envío, dirección, pago simulado y confirmación. |
| `/mis-pedidos` | Historial, estado, detalle y comprobante de pago. |
| `/acceso` | Registro y login; al registrar vuelve al formulario de login. |

No hay controles para quitar artículos o reducir cantidades: el contrato de Carrito solo permite consultar y agregar desde Angular. El vaciado y la coordinación de checkout son internos de Pedidos.

La siguiente actualización del contrato de Pedidos contempla `guia` y `pago_id` como valores nullable, además de `metodo_pago`. El frontend acepta tanto esa respuesta como la versión actual que todavía omite esos campos: un campo omitido o `null` se muestra como pendiente y no habilita rastreo. Cuando existe una guía, consulta `GET /api/envios/rastreo/{guia}`; el estado del paquete (`preparando`, `en_transito` o `entregado`) se mantiene separado del estado comercial del pedido (`pagado` o `enviado`). Los cambios del contrato y el despacho a `entregado` después de 60 segundos adicionales aún deben publicarse en `feature-mojarra-3` antes de considerarse implementados.

## Arquitectura frontend

- `src/app/core/`: clientes API, modelos de contrato, autenticación, sesión en memoria e interceptor Bearer.
- `src/app/datos/`: fachadas usadas por las vistas y adaptadores HTTP.
- `src/app/mock/`: fixtures y proveedores simulados, aislados de la capa HTTP.
- `src/app/pages/`: catálogo, detalle, acceso, checkout e historial.
- `src/app/shared/`: estados de vista, estrellas, tarjetas, imágenes de respaldo y formato MXN.
- `src/app/shared/intro-logo.*`: intro 3D autocontenida; Three.js y SVGLoader se cargan bajo demanda y liberan recursos al terminar.

## Comandos

```bash
npm run build
npm test
```

El `docker-compose.yml` raíz todavía debe integrar los contenedores de microservicios y el frontend para permitir el flujo E2E completo en Compose.
