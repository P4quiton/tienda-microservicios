# Contratos de API v1 — revisión checkout 1.1

Los YAML OpenAPI 3.0.3 son la referencia normativa de integración. Los endpoints originales se conservan; se agregan confirmar/liberar inventario, consulta individual de pedido y health/ready.

## Revisión común vs revisión por API

La revisión común identifica el conjunto coordinado de cambios de integración; la versión por API identifica la evolución independiente del contrato OpenAPI de cada servicio.

| Alcance | Revisión común | Versión del contrato | Significado |
|---|---:|---:|---|
| Checkout e integración común | 1.1 | — | Revisión del flujo y de los cambios coordinados que comparten los servicios. |
| Usuarios | 1.1 | 1.1.0 | Versión declarada en `docs/api/usuarios.yaml`. |
| Productos | 1.1 | 1.1.0 | Versión declarada en `docs/api/productos.yaml`. |
| Envíos | 1.1 | 1.1.0 | Versión declarada en `docs/api/envios.yaml`. |
| Inventario | 1.1 | 1.3.0 | Versión declarada en `docs/api/inventario.yaml`. |
| Pedidos | 1.1 | 1.2.0 | Versión declarada en `docs/api/pedidos.yaml`. |
| Carrito | 1.1 | 1.1.0 | Versión declarada en `docs/api/carrito.yaml`. |
| Pagos | 1.1 | 1.1.0 | Versión declarada en `docs/api/pagos.yaml`. |
| Reseñas | 1.1 | 1.1.0 | Versión declarada en `docs/api/resenas.yaml`. |

| Servicio | Método | Ruta | Acceso | Función |
|---|---|---|---|---|
| usuarios | POST | /api/usuarios/registro | Público | Registrar cliente |
| usuarios | POST | /api/usuarios/login | Público | Iniciar sesión |
| usuarios | GET | /api/usuarios/{id} | JWT del titular o admin | Consultar perfil |
| productos | GET | /api/productos | Público | Listar catálogo |
| productos | GET | /api/productos/{id} | Público | Consultar producto |
| productos | POST | /api/productos | JWT admin | Crear producto |
| envios | POST | /api/envios/cotizar | JWT o identidad interna autorizada | Cotizar envío |
| envios | POST | /api/envios/generar | Identidad interna autorizada | Generar guía |
| envios | GET | /api/envios/rastreo/{guia} | Titular/admin o identidad interna autorizada | Rastrear envío |
| inventario | GET | /api/inventario/{producto_id} | Público | Consultar existencias |
| inventario | POST | /api/inventario/reservar | Identidad interna autorizada | Reservar existencias |
| inventario | POST | /api/inventario/reabastecer | JWT admin | Reabastecer |
| inventario | POST | /api/inventario/confirmar | Identidad interna autorizada | Confirmar reserva |
| inventario | POST | /api/inventario/liberar | Identidad interna autorizada | Liberar reserva |
| carrito | GET | /api/carrito/{usuario_id} | Titular/admin o identidad interna autorizada | Consultar carrito |
| carrito | POST | /api/carrito/{usuario_id}/agregar | JWT del titular o admin | Agregar artículo |
| carrito | DELETE | /api/carrito/{usuario_id}/vaciar | Solo Pedidos, sin checkout activo | Vaciar carrito |
| carrito | POST | /api/carrito/{usuario_id}/iniciar | Solo Pedidos | Capturar snapshot versionado |
| carrito | POST | /api/carrito/{usuario_id}/finalizar | Solo Pedidos | Retirar cantidades compradas |
| carrito | POST | /api/carrito/{usuario_id}/liberar | Solo Pedidos | Cerrar snapshot sin retirar artículos |
| pedidos | POST | /api/pedidos | JWT cliente o admin | Crear pedido y coordinar compra |
| pedidos | GET | /api/pedidos/usuario/{usuario_id} | JWT del titular o admin | Historial de pedidos |
| pedidos | PATCH | /api/pedidos/{id}/estado | Solo Envíos | Actualizar pagado a enviado |
| pedidos | GET | /api/pedidos/{id} | Titular/admin o identidad interna autorizada | Consultar pedido |
| pagos | POST | /api/pagos/procesar | Identidad interna autorizada | Procesar pago simulado |
| pagos | GET | /api/pagos/pedido/{pedido_id} | Titular/admin o identidad interna autorizada | Consultar comprobante |
| resenas | GET | /api/resenas/producto/{producto_id} | Público | Consultar reseñas |
| resenas | POST | /api/resenas | JWT cliente o admin | Crear reseña |

## Convenciones
- JSON UTF-8, snake_case, UUID v4, UTC ISO 8601. Importes MXN como cadenas decimales de dos posiciones (ej. "899.99"); nunca float para cálculo. Cantidades positivas; stock no negativo. Se concreta así el acuerdo monetario previo.
- Éxito: `{"success":true,"message":"OK","data":{}}`. Error: `{"success":false,"message":"Error","errors":{}}`. Los endpoints de salud son excepción y retornan status/service.
- 400 JSON inválido, 401 sin identidad válida, 403 sin autorización, 404 inexistente, 409 conflicto, 422 validación, 429 límite, 500 error interno, 503 dependencia o resultado incierto.
- Idempotency-Key UUID: almacenar identidad, operación, hash de solicitud y resultado; misma clave y payload devuelve resultado previo; diferente payload 409. Una solicitud en curso devuelve 409 o 503 sin repetir efectos.
- No confiar en usuario_id, precios, monto o rol enviados por navegador. Los campos no declarados se rechazan. En Reseñas, usuario_id es opcional y solo se acepta si coincide con el sub del JWT (403 con errors.usuario_no_coincide). Los esquemas no sustituyen las reglas de negocio descritas.
- `/health`: proceso vivo, sin depender de BD; `/ready`: comprobar BD y retornar 503 si no está disponible.
- Para listar catálogo: página 1 y límite 20 por defecto. Para envío, se adopta cantidad como unidad de cotización simulada; peso queda fuera del MVP.

- Revisión 1.1: version y linea_id obligatorios en respuestas de Carrito; agregar conserva su body. Idempotency-Key obligatorio en mutaciones internas de Inventario, Carrito y PATCH de Pedidos. Ver flujo-compra.md para recuperación durable.
