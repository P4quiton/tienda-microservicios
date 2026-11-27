# Pruebas E2E por HTTP real

Verifican, como lo haria un cliente con `curl`, el flujo de compra entre **Carrito (8005), Pedidos (8006), Pagos (8007) y Envios (8003)** reales. Productos (8002) e Inventario (8004) aun no existen: se sustituyen por stubs propios.

## Ejecutar

```sh
./e2e/run.sh          # levanta todo, corre los 17 escenarios, apaga y limpia
MANTENER=1 ./e2e/run.sh   # solo levanta (depuracion); luego ./e2e/run.sh --limpiar
```

Requisitos (sin `docker build` ni red): imagenes locales `postgres:17` y `pedidos-test-temporal` (PHP 8.5), Java 21 + Maven offline, Node 24, y el venv de Envios. Las rutas por defecto se pueden cambiar con `MVN`, `M2`, `ENVIOS_VENV`, `PEDIDOS_VENDOR`; `SKIP_BUILD=1` reutiliza el jar de Pagos. Si `api-carrito/` no trae `node_modules`, `run.sh` enlaza temporalmente `CARRITO_NODE_MODULES` (por defecto el del arbol `tienda/carrito`) y retira el enlace al limpiar. Codigo de salida 0 solo si todos los escenarios pasan. La salida de la ultima corrida queda en `ultima-salida.log`; el resultado analizado en `REPORTE.md`.

## Que levanta `run.sh`

| Pieza | Como |
|---|---|
| PostgreSQL 17 | contenedor `mojarra-pg-e2e`, puerto 55450, datos en tmpfs, contrasena aleatoria. Usa el propio `infra/postgres/init/01-create-databases.sh` (roles `usr_*` NOSUPERUSER/NOCREATEDB, REVOKE PUBLIC). |
| Migraciones | Carrito (`node src/migrate.js`) y Pedidos (`artisan migrate --force`) con su rol; Envios y Pagos (Flyway) migran solos al arrancar, tambien con su rol. |
| Carrito, Envios, Pagos | procesos nativos (`node`, `uvicorn`, `java -jar`; Pagos se compila con `mvn -o package -DskipTests`). |
| Pedidos | `docker run --rm --network host` con la imagen existente, codigo y vendor montados `:ro`, storage en tmpfs, `PHP_CLI_SERVER_WORKERS=4`. |
| Stubs | `stubs/stub_server.py` (Productos e Inventario segun `docs/api/{productos,inventario}.yaml`: stock disponible = fisico - reservado, reservar/confirmar/liberar idempotentes con `Idempotency-Key` obligatoria, 409 si no alcanza). Las rutas `/__test/*` solo siembran datos. |
| Proxies de fallos | `stubs/fault_proxy.py` entre Pedidos y Pagos/Carrito: `delay`, `drop_response` (el efecto ocurre, la respuesta se pierde) y `refuse`. |
| Identidad | par RSA de prueba y secretos de servicio aleatorios (uno distinto por par) solo en `e2e/.tmp/` (ignorado por git; se borra al empezar cada corrida). JWT de cliente A, B y admin con `sub` UUID v4. |

## Archivos

- `run.sh`: orquestacion y limpieza (trap: mata procesos, `docker rm -f` del PG y de Pedidos, avisa de puertos ocupados).
- `servicios.sh`: arrancar/matar/reiniciar cada servicio (lo usan los escenarios de caidas). `E2E_FASE=altos` (por defecto: limites 100000 y despacho de Envios a 3600 s) o `default` (sin variables de limite); `E2E_SCHEDULER=1` arranca Pedidos con el CMD del Dockerfile (recuperar + `schedule:work` + servidor).
- `tests/e2e.py`: escenarios (solo biblioteca estandar + PyJWT del venv de Envios). Sin argumentos corre los 17; con numeros corre un subconjunto contra servicios ya arriba (`MANTENER=1 ./e2e/run.sh`, luego `python tests/e2e.py 13 14`).
  - 13: scheduler de Pedidos sin intervencion; 14: despacho automatico de Envios (`ENVIOS_DESPACHO_SEGUNDOS=3`); 15: limites por defecto (reinicia los 4 servicios sin variables de limite; ultimo escenario). El 11 comprueba que la notificacion pendiente sobrevive a reinicios de Pedidos y Envios; ya nadie invoca `despachar` ni `pedidos:recuperar` a mano en 11, 13, 14.
  - 16: campos del pedido por HTTP (`guia`, `pago_id`, `metodo_pago`) en 201/detalle/historial/PATCH para compra aprobada, pago rechazado, 409 por stock, idempotencia, titularidad y recuperacion de un pago incierto (Pagos `kill -9` + `pedidos:recuperar`), contrastados con Pagos, Envios y la BD de Pedidos.
  - 17: entrega automatica de Envios (`ENVIOS_ENTREGA_SEGUNDOS`): (A) preparando -> en_transito -> entregado sin intervencion, `despachado_en` persistido, pedido sigue `enviado`, el outbox no crece por la entrega; (B) segunda instancia (`envios2`, puerto 8013, misma BD): cada envio transita una sola vez; (C) con `ENVIOS_ENTREGA_SEGUNDOS=60` no entrega antes de tiempo; (D) Envios apagado con `kill -9` mientras vence el plazo, al reiniciar entrega solo. Para probar "una sola vez" instala en el PG temporal (rol `postgres`, solo para esto) un trigger que audita cada UPDATE de `envios` y lo retira al terminar.
  - Orden real de ejecucion: 1-14, 16, 17 y 15 al final (el 15 reinicia todo sin variables de limite, por eso va ultimo). Las fases `altos` incluyen `ENVIOS_ENTREGA_SEGUNDOS=3600`; los escenarios que prueban despacho/entrega restauran esa fase al terminar.
  - Duracion total ~290 s.

## Notas de alcance

- Los escenarios consultan las BD de Pagos y Envios con el rol de cada servicio para contar pagos/guias, contrastar `pago_id` y `despachado_en` y auditar transiciones de `envios` (escenario 17: un trigger temporal en el PG efimero, retirado al terminar); todo lo demas es HTTP.
- No se prueba Usuarios, Productos ni Inventario reales: sus stubs solo garantizan lo que el contrato exige a sus consumidores.
- `docker pause` se aplica unicamente a `mojarra-pg-e2e`.
