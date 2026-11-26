# Flujo de compra

1. Angular consulta carrito y cotiza envío; envía dirección, método simulado e Idempotency-Key a POST /api/pedidos.
2. Pedidos obtiene identidad desde JWT, lee carrito, consulta catálogo y calcula precios y envío en backend. Persiste pedido pendiente con snapshot de artículos y clave idempotente. Bloquear modificaciones de carrito durante checkout o aplicar versión de snapshot; acordar mecanismo antes de implementar.
3. Reserva inventario con pedido_id y artículos, de manera atómica. Stock disponible = físico - reservado. Confirmar reduce físico y reservado; liberar solo reduce reservado. No descontar dos veces. Una reserva por pedido. Si falla stock, cancelar sin cobrar.
4. Pedidos invoca Pagos con monto calculado y clave estable. El resultado simulado se persiste una sola vez por pedido. Si rechazo explícito: liberar reserva, cancelar pedido y conservar carrito. Si timeout: consultar resultado o repetir misma clave; nunca asumir rechazo.
5. Si aprobado: confirmar reserva, marcar pagado, generar guía única y vaciar carrito. Persistir avance de cada operación para reanudar tras fallos. No cancelar un pedido cobrado ni liberar su stock por un timeout. Reintentar finalización pendiente con las mismas claves. No prometer atomicidad distribuida.
6. Angular muestra pedido y consulta comprobante/rastreo. El historial se obtiene por titular. Si la guía todavía no existe se muestra pendiente, no se inventa.

## Pruebas de aceptación
- Compra aprobada: pedido pagado, un pago, una guía, stock descontado una vez, carrito vacío.
- Pago rechazado: pedido cancelado, stock disponible restaurado, carrito intacto.
- Stock insuficiente: 409 o pedido cancelado documentado; sin cobro.
- Repetición de solicitud con misma clave: sin duplicados.
- Timeout posterior a pago: recuperación por consulta/reintento sin doble cargo.
- JWT incorrecto, rol insuficiente y acceso a pedidos ajenos: 401/403.
- Reinicio de contenedor: datos persistentes. Escalar API de productos y eliminar un Pod: recuperación sin perder datos.

Los detalles de reconciliación durable y bloqueo/versionado del carrito son trabajo de implementación, no están resueltos solo por OpenAPI.
