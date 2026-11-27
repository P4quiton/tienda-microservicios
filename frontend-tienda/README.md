# Nébula · frontend-tienda

Interfaz Angular 21 (standalone, zoneless, señales) de la tienda Nébula. Estilo *Liquid Glass* claro: vidrio en la barra de navegación, filtros y resumen de compra; contenido sobre superficies opacas con contraste alto.

## Comandos

```bash
npm install
npm start          # ng serve → http://localhost:4200
npm run build      # build de producción en dist/
npm test           # pruebas unitarias (Vitest vía ng test)
```

No hay linter configurado todavía (`ng lint` no está disponible).

## Vistas

| Ruta | Vista | Notas |
|---|---|---|
| `/catalogo` | Grid con búsqueda (`?q=`), chips de categoría (`?categoria=`), orden y promedio de reseñas | Las categorías se derivan de los productos devueltos (texto libre en el contrato). |
| `/producto/:id` | Datos, disponibilidad, reseñas y formulario de reseña | El formulario pide sesión iniciada. |
| `/checkout` | Carrito, cotización por CP, dirección, método simulado, confirmación | Requiere sesión. |
| `/mis-pedidos` | Historial, estado, detalle desplegable | Requiere sesión. |
| `/acceso` | Iniciar sesión / registro con validación | `?volver=` regresa a la ruta solicitada. |

Todas las vistas incluyen estados de carga, error (con reintento) y vacío.

## Estructura

```
src/app/
  datos/      Fachadas que usa la UI (puntos de integración)
    tienda-datos.ts   interfaz TiendaDatos + token TIENDA_DATOS (un método por endpoint)
    sesion-ui.ts      interfaz SesionUi + token SESION_UI + guard requiereSesion
    carrito.store.ts  estado compartido del carrito (contador del encabezado)
    models.ts, dinero.ts  tipos UI y aritmética en centavos (importes como cadenas)
  mock/       Fixtures y simulaciones AISLADAS (eliminar al integrar)
  layout/     Shell: navegación, búsqueda, carrito, sesión (único layout)
  shared/     EstadoVista, Estrellas, ProductoCard, pipe mxn
  pages/      catalogo, producto, checkout, pedidos, acceso
  core/       Capa API/auth del coordinador (no la toca la UI)
public/brand  Logo Nébula (PNG) y emblema SVG; public/mock  imágenes de fixtures
```

## Datos simulados (supuestos)

`app.config.ts` provee `MockTiendaDatos` y `MockSesionUi`. Mientras estén activos:

- Productos, inventario, reseñas y pedidos salen de `src/app/mock/fixtures.ts` (no son datos reales). Carrito inicial con 2 artículos.
- Agrega `?mock=error` o `?mock=vacio` a cualquier URL para ver los estados de error y vacío.
- Acceso: cualquier correo válido y contraseña de 8+ caracteres; un correo que contenga `invalido` falla; registrar `demo@nebula.mx` simula correo duplicado.
- Pago: `tarjeta_simulada` aprueba; `transferencia_simulada` rechaza. Supuesto de UI: un rechazo llega como pedido `cancelado` y el carrito se conserva.
- Cotización de envío: tarifa determinista por CP y cantidad (el servidor recalcula al crear el pedido).

## Limitaciones de los contratos actuales

- **Carrito**: solo existen consultar y agregar (vaciar es interno). La UI no ofrece quitar ni editar cantidades y lo indica en pantalla.
- **Guía/rastreo**: `GET /api/pedidos/usuario/{id}` no devuelve guía; se muestra «Pendiente» y el botón *Rastrear envío* deshabilitado. La línea de tiempo usa solo el estado del pedido (`pendiente/pagado/enviado/cancelado`).
- **Categorías**: no hay endpoint de categorías; se derivan del catálogo.
- **Reseñas**: no incluyen nombre del autor; se muestran como «Cliente verificado».

## Integración pendiente

1. Implementar `TiendaDatos` y `SesionUi` sobre `StoreApiService` / `AuthService` / `SessionService` de `core/`.
2. En `app.config.ts`, sustituir `MockTiendaDatos` y `MockSesionUi` y registrar `provideHttpClient(withInterceptors([apiInterceptor]))`.
3. Mapear el resultado real de pago rechazado (código o estado) a la pantalla de rechazo de `checkout`.
