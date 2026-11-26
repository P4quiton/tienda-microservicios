# Reporte E2E (corrida real del 2026-11-26)

Comando: `./e2e/run.sh` (71 s, codigo de salida 0). Salida completa en [`ultima-salida.log`](ultima-salida.log). Primera corrida: 10/12 OK (hallazgos abajo); tras las correcciones, 12/12.

## Resultado por escenario (corrida final)

| # | Escenario | Resultado | Evidencia clave |
|---|---|---|---|
| 1 | Carrito: vacio v0, agregar con clave, repetir no duplica | OK | `GET` => `items:[] version:0`; misma clave => cantidad 2 / version 1; otra clave => 3 / v2 misma `linea_id`; misma clave con otro cuerpo 409; sin clave 422 |
| 2 | Cotizar envio | OK | CP 06600 x2 => `114.00`, 2 dias; CP 91000 x1 => `179.00`, 5 dias; CP invalido 422; sin credencial 401 |
| 3 | Compra aprobada | OK | 201 `pagado`, total `314.00` (2x100 + 114 envio); 1 pago `aprobado`; 1 guia (rastreo `preparando`); stock fisico 10->8, reservado 0, 1 reservar + 1 confirmar; carrito `items:[]` v2 |
| 4 | Agregar 1 durante el pago | OK | vaciar durante checkout 409; agregar => cantidad 3; compra 201 con 2; carrito final 1 unidad, misma `linea_id` |
| 5 | Pago rechazado (`transferencia_simulada`) | OK | 201 `cancelado`; pago `rechazado`; reserva `liberada`, 10 disponibles; sin guia; carrito 3; nueva compra con tarjeta => `pagado` |
| 6 | Stock insuficiente | OK | 409; tabla `pagos` 4 -> 4; pedido `cancelado`; carrito 5 intacto y checkout liberado |
| 7 | Misma Idempotency-Key | OK | mismo pedido (cuerpo identico), 1 pago, 1 guia, stock sin cambio; otro cuerpo 409; carrito vacio con otra clave 409; sin clave 422 |
| 8 | Caidas / timeout | OK | (a) Carrito `kill -9` => 503, sin cobro; reinicio + misma clave => 201 pagado. (b0) respuesta de `/procesar` perdida => Pedidos concilia con GET: 201, 1 pago. (b) cobro hecho y POST+consulta perdidos => 503, pedido `pendiente`, reserva sigue `reservada`; Pagos `kill -9` => 503; reinicio + misma clave => 201 mismo pedido, 1 pago, stock 20->18 una vez. (c) `finalizar` falla => 503, pedido `pagado`; `pedidos:recuperar` => "revisados 1 (completados 1)"; carrito vaciado, 1 pago |
| 9 | Seguridad | OK | sin JWT 401; JWT manipulado, clave ajena, `alg=none`, expirado, `aud` erronea, `sub` no v4 => 401 en los 4 servicios; B sobre pedido/carrito/historial/rastreo/pago de A => 403; admin 200; rutas internas de Carrito sin token / token de otro par / JWT => 401; Pagos `/procesar` 401/401/403; Envios `/generar` 401/401/403; PATCH `/estado` con JWT cliente o admin, sin credencial o token desconocido => 401, token de Pagos 403 |
| 10 | PATCH pagado->enviado (token de Envios) | OK | 200 `enviado`; misma clave 200 mismo cuerpo; otra clave 200; `enviado->pagado/cancelado` 409; misma clave con otro estado 409; `cancelado->enviado` 409; inexistente 404 |
| 11 | Envios: guia, rastreo, `despachar` -> outbox -> Pedidos | OK | guia `preparando`; `/generar` repetido => misma guia; tras >1 ciclo del Notificador el pedido sigue `pagado`; `despachar` => `en_transito`, fila outbox `pendiente`; en segundos el pedido real pasa a `enviado`, outbox `enviada` (1 fila) |
| 12 | `/health` y `/ready` | OK | los 4 => 200. Con `docker pause` del PG e2e: `/ready` 503 y `/health` 200 en Carrito (5 s), Pedidos (**30 s**), Pagos (5 s), Envios (3 s); vuelven a 200 al reanudar |

## Bugs de servicio corregidos (con regresion)

1. **Pedidos genera `Idempotency-Key` UUIDv5 hacia Carrito (y Envios/Inventario), que exigen v4 => 422 y el checkout nunca avanzaba** (503 en toda compra real; las pruebas unitarias con `Http::fake` no lo detectaban).
   - `api-pedidos/app/Pedidos/Pedido.php`: `clave()` deriva ahora un UUID v4 determinista por hash (id + operacion).
   - Regresion: `api-pedidos/tests/Feature/CarritoHttpTest.php` (todas las operaciones deben dar UUID v4). Efecto lateral: un pedido en vuelo creado antes del cambio reintentaria con claves nuevas; aceptable pre-produccion.
2. **Carrito: `/ready` y las rutas colgaban indefinidamente con la BD congelada** (solo existia `statement_timeout`, que aplica el servidor).
   - `api-carrito/src/db.js`: `query_timeout: 5000` en el pool; `api-carrito/src/app.js`: "Query read timeout" se traduce a 503.
   - Regresion: `api-carrito/test/bd-congelada.test.js` (suite: 23 pass, 2 skip por no haber `TEST_DATABASE_URL`).

## Observaciones / ambiguedades del contrato (no modificadas)

- **El pedido no expone la guia** (`pedidos.yaml`) y Envios solo rastrea por guia: un cliente no puede descubrirla por HTTP. El E2E la lee de la BD de Envios. Conviene definirlo.
- **Disparador de `despachar` no definido** (decision pendiente ya documentada en Envios); solo se probo la funcion interna.
- Pedidos `/ready` tarda ~30 s con la BD congelada (devuelve 503, pero un probe con timeout corto lo vera como fallo/timeout). Sin cambio.
- `PATCH /estado` acepta cualquier estado conocido y responde 409 para `pagado`/`cancelado` aunque el contrato solo enumera `enviado` (422 seria lo esperable). Rutas internas dan 403 a un JWT en Pagos/Envios y 401 en Pedidos/Carrito: inconsistente pero admitido por el contrato.
- Un timeout/perdida de respuesta de Pagos se resuelve consultando `GET /api/pagos/pedido/{id}` dentro de la misma peticion (201); el 503 solo aparece si tambien falla la consulta.

## No verificado

- Productos, Inventario y Usuarios reales (stubs / JWT firmados por la prueba).
- Scheduler automatico de Pedidos (`schedule:work`, cada minuto): se invoco `pedidos:recuperar` a mano.
- Despliegue en contenedores/Compose/k8s de Carrito, Pagos y Envios (se ejecutaron nativos; Pedidos con la imagen de pruebas montando el codigo).
- `phpunit` completo de Pedidos: 50 pruebas, 28 omitidas y 1 fallo (`QaHostilTest.php:519`, falta una BD sqlite/Postgres de pruebas en este entorno), sin relacion con el cambio; `CarritoHttpTest` pasa.
