# Flujo de compra

## Saga simplificada coordinada por Pedidos

1. Angular consulta carrito y cotiza envío; envía dirección, método simulado e Idempotency-Key a POST /api/pedidos. Identidad desde JWT. Pedidos crea un pedido pendiente durable y garantiza un único checkout activo por usuario mediante restricción transaccional. Una misma clave recupera ese pedido; una clave distinta mientras exista uno activo devuelve 409.
2. Pedidos lee carrito y persiste versión observada, pedido_id y claves estables antes de invocar POST /api/carrito/{usuario_id}/iniciar. Carrito verifica versión y captura snapshot en una transacción. Si cambió la versión o hay otro checkout activo, /iniciar responde 409; Pedidos responde 503 y deja el pedido pendiente y reintentable, sin cobro ni reserva. Una vez iniciado, agregar sigue permitido; vaciar se rechaza mientras esté activo. Cada línea posee linea_id irrepetible. Pedidos persiste snapshot, consulta catálogo y recalcula precios y envío en backend.
3. Reservar inventario atómicamente por pedido_id y artículos agregados por producto. Stock disponible = físico - reservado. Confirmar reduce físico y reservado; liberar solo reduce reservado. Una reserva por pedido. Si stock insuficiente, Inventario devuelve un error 409 `stock_insuficiente` específico que se almacena en su registro de idempotencia. Este rechazo es definitivo y persistente: cualquier reintento con la misma `Idempotency-Key` devolverá el mismo 409 incluso si el stock se reabastece posteriormente, garantizando la consistencia del pedido fallido. Pedidos libera el checkout del carrito y cancela sin cobrar ante este error. Los errores 409 genéricos (conflictos de concurrencia) se tratan como resultado incierto y permiten reintento.
4. Persistir intención de pago y clave antes de llamar Pagos. Una transacción simulada por pedido. Rechazo explícito: liberar inventario y checkout, conservar artículos y cancelar. Timeout: consultar pago o repetir misma clave y payload; 404 no prueba que no haya operación en curso. No cancelar ni liberar por resultado incierto.
5. Pago aprobado: confirmar reserva, marcar pagado, generar guía única y finalizar carrito con pedido_id, version_original e items exactos del snapshot (incluidos linea_id). Retirar solo cantidades compradas; conservar adiciones posteriores. Carrito guarda efecto y resultado en una transacción. La versión actual puede ser mayor que la original. Pedidos no usa vaciar durante checkout.
6. Angular consulta pedido, comprobante y rastreo por titular. Guía inicial preparando; cuando Envíos registra despacho real (en_transito), notifica PATCH de Pedidos con credencial propia y clave estable. Reintenta notificación persistida si falla. Pedido pagado pasa a enviado, nunca por mera generación de guía.

## Recuperación durable

PostgreSQL de Pedidos es fuente de verdad. Guardar snapshot, versión, precios, dirección, método, estado comercial, estado_checkout, claves por operación, resultados, referencias de pago y guía, intentos, próximo intento y último error sin secretos. Reserva identificada por pedido_id en contrato actual. Estados internos sugeridos: iniciado, carrito_iniciado, inventario_reservado, pago_en_proceso, pago_aprobado, inventario_confirmado, envio_generado, carrito_finalizado, completado, compensacion_pendiente, cancelado. No son campos públicos nuevos del pedido.

Un proceso de reconciliación ejecutado al arrancar y periódicamente recupera operaciones pendientes, incluso sin petición del cliente. Usar bloqueo/lease durable por pedido para evitar trabajadores simultáneos, sin mantener transacciones abiertas durante HTTP. Persistir intención y clave antes de cada llamada y resultado después. Reintentos con backoff; conservar operaciones inciertas para revisión, nunca cancelar un pago aprobado por timeout. Compensaciones antes de cobro también son persistentes e idempotentes; no cerrar checkout activo hasta completarlas. No hay atomicidad distribuida ni expiración automática de reservas con pago incierto. No se implementa reembolso en este MVP.

## Pruebas de aceptación

- Compra aprobada: un pago, una guía y descuento de inventario una vez; carrito vacío si no hubo adiciones.
- Dos unidades compradas y una añadida durante pago: queda una. Repetir finalizar no descuenta otra vez.
- Versión obsoleta o checkout activo al iniciar: 503 de Pedidos, pedido pendiente y reintentable, sin cobro ni reserva. Solo el 409 explícito `stock_insuficiente` de Inventario cancela; vaciar durante checkout: 409.
- Pago rechazado: liberar reserva y snapshot, conservar carrito, cancelar. Stock insuficiente: sin cobro.
- Misma clave y payload: mismo efecto; payload diferente: 409.
- Timeout y reinicio después del pago: recuperar sin doble cargo; reconciliación incluso sin cliente.
- JWT incorrecto, rol insuficiente y acceso ajeno: 401/403. PATCH con JWT o token de otro servicio: rechazo; guía creada no implica enviado.
- Reinicio de contenedor: datos persistentes. Escalar Productos y eliminar un Pod: recuperación sin perder datos.

Los contratos describen obligaciones; las pruebas de ejecución e implementación siguen pendientes.
