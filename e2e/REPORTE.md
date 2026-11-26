# Reporte E2E (corrida real del 2026-11-26)

Comando: `./e2e/run.sh` (197 s, codigo de salida 0). Salida completa en [`ultima-salida.log`](ultima-salida.log). Los escenarios 1-12 dieron 10/12 OK en la primera corrida historica (hallazgos abajo) y 12/12 despues. La ampliacion 11/13/14/15 se ejecuto el 2026-11-26: primera corrida con 3 FALLA del propio test (el escenario 11 consultaba el rastreo HTTP con Pedidos caido, que no responde porque Envios consulta a Pedidos para la titularidad; ese error dejo Pedidos apagado y rompio 12, y a Envios con despacho a 8 s, lo que cambio el estado final en 13); corregido el test, corrida final **15/15 OK**. No se encontraron bugs de servicio nuevos; no se modifico ningun `api-*`.

Fases: escenarios 1-14 con `RATE_LIMIT_*=100000` y `ENVIOS_DESPACHO_SEGUNDOS=3600` (para que Envios no despache solo fuera de los escenarios 11 y 14); el 15 reinicia los 4 servicios SIN variables de limite (valores por defecto). Los escenarios 11 y 14 reinician Envios con su propia configuracion de despacho.

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
| 11 | Envios: guia, rastreo, `/generar` idempotente; notificacion pendiente sobrevive a reinicios (sin `despachar` manual) | OK | guia `preparando`; `/generar` repetido => misma guia; tras >1 ciclo del Notificador pedido `pagado` y 0 filas de outbox. Con despacho a 8 s y Pedidos apagado: envio `en_transito` solo (9 s), outbox 1 fila `pendiente` (intentos 1, `ConnectError`); `kill -9` y reinicio de Envios: sigue `pendiente`; al reiniciar Pedidos se entrega: pedido `enviado`, outbox 1 fila `enviada` |
| 12 | `/health` y `/ready` | OK | los 4 => 200. Con `docker pause` del PG e2e: `/ready` 503 y `/health` 200 en Carrito (5 s), Pedidos (**30 s**), Pagos (5 s), Envios (3 s); vuelven a 200 al reanudar |
| 13 | Scheduler de Pedidos (`schedule:work`, CMD del Dockerfile leido del archivo) | OK | Carrito rechaza `/finalizar` => 503, pedido `pagado`, carrito con 2 unidades; Carrito `kill -9` + reinicio; sin tocar nada el carrito queda vacio en 58 s (limite 110 s); el log del contenedor muestra `Running ['artisan' pedidos:recuperar] ... DONE` (19:02:00). 1 pago `aprobado` (total de pagos +1), 1 guia, reserva `confirmada`, stock 20->18 una vez; repetir la clave => 201 mismo pedido `pagado`, sigue 1 pago/1 guia |
| 14 | Despacho automatico de Envios (3 s, barrido 1 s, notificador 1 s) | OK | sin tocar nada: rastreo `en_transito` a 3.5 s de la compra, pedido `enviado` de inmediato, outbox 1 fila `enviada`. Repetir `/generar` y esperar 6 s => 1 guia, 1 fila, rastreo `en_transito`, pedido `enviado`. Dos compras simultaneas: ambas `enviado` en 3.7 s con 1 fila cada una |
| 15 | Limites por defecto | OK | 6 POST `/api/pedidos` del mismo usuario: `[201, 409, 409, 409, 409, 429]`, `Retry-After: 60`. Cuerpo de 300 KiB => 413 en Carrito, Pedidos, Pagos y Envios (con credencial; sin credencial => 401; 200 KiB no da 413). 130 `/health` + 130 `/ready` por servicio => solo 200 y no consumen cupo. 130 GET autenticados por servicio: primer 429 exactamente en el 121, con `Retry-After` 53-60; sin credencial 401; `/health` 200 con el usuario saturado |

## Bugs de servicio corregidos (con regresion)

1. **Pedidos genera `Idempotency-Key` UUIDv5 hacia Carrito (y Envios/Inventario), que exigen v4 => 422 y el checkout nunca avanzaba** (503 en toda compra real; las pruebas unitarias con `Http::fake` no lo detectaban).
   - `api-pedidos/app/Pedidos/Pedido.php`: `clave()` deriva ahora un UUID v4 determinista por hash (id + operacion).
   - Regresion: `api-pedidos/tests/Feature/CarritoHttpTest.php` (todas las operaciones deben dar UUID v4). Efecto lateral: un pedido en vuelo creado antes del cambio reintentaria con claves nuevas; aceptable pre-produccion.
2. **Carrito: `/ready` y las rutas colgaban indefinidamente con la BD congelada** (solo existia `statement_timeout`, que aplica el servidor).
   - `api-carrito/src/db.js`: `query_timeout: 5000` en el pool; `api-carrito/src/app.js`: "Query read timeout" se traduce a 503.
   - Regresion: `api-carrito/test/bd-congelada.test.js` (suite: 23 pass, 2 skip por no haber `TEST_DATABASE_URL`).

## Observaciones / ambiguedades del contrato (no modificadas)

- **El pedido no expone la guia** (`pedidos.yaml`) y Envios solo rastrea por guia: un cliente no puede descubrirla por HTTP. El E2E la lee de la BD de Envios. Conviene definirlo.
- **Disparador de despacho**: ahora es automatico (por tiempo desde la guia) y el E2E lo verifica sin invocar nada a mano. Sigue sin haber contrato HTTP para despachar o para fijar `ENVIOS_DESPACHO_SEGUNDOS`.
- **`POST /generar` repetido despues del despacho** devuelve 201 con `estado: "preparando"` aunque el envio ya esta `en_transito` (el rastreo si da `en_transito`). La idempotencia devuelve la respuesta original; `envios.yaml` no dice si debe reflejar el estado actual. No modificado.
- **Con Pedidos caido el rastreo de Envios no responde** (verifica titularidad consultando a Pedidos). El E2E lee el estado de la BD en ese tramo. Comportamiento de acoplamiento, no definido en el contrato.
- **Limites**: el checkout (`RATE_LIMIT_CHECKOUT_POR_MIN=5`) cuenta tambien los POST que terminan en 409 (carrito vacio): el 6o es 429 aunque los intermedios no creen pedido. Los contadores son por proceso/instancia (Carrito: ventana fija; Envios: deslizante), y `RATE_LIMIT_CHECKOUT_POR_MIN` no aplica a Carrito/Envios/Pagos pese a aceptarse en `.env`.
- Pedidos `/ready` tarda ~30 s con la BD congelada (devuelve 503, pero un probe con timeout corto lo vera como fallo/timeout). Sin cambio.
- `PATCH /estado` acepta cualquier estado conocido y responde 409 para `pagado`/`cancelado` aunque el contrato solo enumera `enviado` (422 seria lo esperable). Rutas internas dan 403 a un JWT en Pagos/Envios y 401 en Pedidos/Carrito: inconsistente pero admitido por el contrato.
- Un timeout/perdida de respuesta de Pagos se resuelve consultando `GET /api/pagos/pedido/{id}` dentro de la misma peticion (201); el 503 solo aparece si tambien falla la consulta.

## No verificado

- Productos, Inventario y Usuarios reales (stubs / JWT firmados por la prueba).
- Que el scheduler funcione con varias replicas de Pedidos (`onOneServer` con cache de archivo por instancia no coordina; solo se probo una instancia).
- Limites `RATE_LIMIT_INTERNA_POR_MIN` (300) y `RATE_LIMIT_MUTACION_POR_MIN` (30) por defecto: solo se verificaron consulta (120) y checkout (5) y el tope de cuerpo.
- Despliegue en contenedores/Compose/k8s de Carrito, Pagos y Envios (se ejecutaron nativos; Pedidos con la imagen de pruebas montando el codigo).
- `phpunit` completo de Pedidos: 50 pruebas, 28 omitidas y 1 fallo (`QaHostilTest.php:519`, falta una BD sqlite/Postgres de pruebas en este entorno), sin relacion con el cambio; `CarritoHttpTest` pasa.
