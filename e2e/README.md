# Pruebas E2E por HTTP real

Verifican, como lo haria un cliente con `curl`, el flujo de compra entre **Carrito (8005), Pedidos (8006), Pagos (8007) y Envios (8003)** reales. Productos (8002) e Inventario (8004) aun no existen: se sustituyen por stubs propios.

## Ejecutar

```sh
./e2e/run.sh          # levanta todo, corre los 15 escenarios, apaga y limpia
MANTENER=1 ./e2e/run.sh   # solo levanta (depuracion); luego ./e2e/run.sh --limpiar
```

Requisitos (sin `docker build` ni red): imagenes locales `postgres:17` y `pedidos-test-temporal` (PHP 8.5), Java 21 + Maven offline, Node 24, y el venv de Envios. Las rutas por defecto se pueden cambiar con `MVN`, `M2`, `ENVIOS_VENV`, `PEDIDOS_VENDOR`; `SKIP_BUILD=1` reutiliza el jar de Pagos. Codigo de salida 0 solo si todos los escenarios pasan. La salida de la ultima corrida queda en `ultima-salida.log`; el resultado analizado en `REPORTE.md`.

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
- `tests/e2e.py`: escenarios (solo biblioteca estandar + PyJWT del venv de Envios). Sin argumentos corre los 15; con numeros corre un subconjunto contra servicios ya arriba (`MANTENER=1 ./e2e/run.sh`, luego `python tests/e2e.py 13 14`).
  - 13: scheduler de Pedidos sin intervencion; 14: despacho automatico de Envios (`ENVIOS_DESPACHO_SEGUNDOS=3`); 15: limites por defecto (reinicia los 4 servicios sin variables de limite; ultimo escenario). El 11 comprueba que la notificacion pendiente sobrevive a reinicios de Pedidos y Envios; ya nadie invoca `despachar` ni `pedidos:recuperar` a mano en 11, 13, 14.
  - Duracion total ~200 s.

## Notas de alcance

- Los escenarios consultan las BD de Pagos y Envios con el rol de cada servicio solo para contar pagos/guias; todo lo demas es HTTP.
- No se prueba Usuarios, Productos ni Inventario reales: sus stubs solo garantizan lo que el contrato exige a sus consumidores.
- `docker pause` se aplica unicamente a `mojarra-pg-e2e`.
