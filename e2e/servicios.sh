#!/usr/bin/env bash
# Control de procesos de la corrida E2E. Uso: servicios.sh start|stop|kill|wait|logs <servicio>
# Lee .tmp/env.sh (generado por run.sh). Servicios: pg productos inventario envios envios2 carrito pagos pedidos
#   pedidos-recuperar (una pasada de `php artisan pedidos:recuperar`), proxy-pagos, proxy-carrito
set -uo pipefail
E2E="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$E2E/.." && pwd)"
# shellcheck disable=SC1091
source "$E2E/.tmp/env.sh"
PIDS="$E2E/.tmp/pids"; LOGS="$E2E/.tmp/logs"; mkdir -p "$PIDS" "$LOGS"

# Fases de limites: E2E_FASE=altos (escenarios 1-14: limites muy altos para no chocar y despacho de Envios
# muy lento para que no despache solo) o E2E_FASE=default (escenario 15: SIN ninguna variable de limites,
# valen los valores por defecto de cada servicio). Lo ya exportado por el llamador tiene prioridad.
LIMITES_VARS=(RATE_LIMIT_CONSULTA_POR_MIN RATE_LIMIT_MUTACION_POR_MIN RATE_LIMIT_CHECKOUT_POR_MIN RATE_LIMIT_INTERNA_POR_MIN MAX_JSON_BYTES)
if [ "${E2E_FASE:-altos}" = altos ]; then
  for v in RATE_LIMIT_CONSULTA_POR_MIN RATE_LIMIT_MUTACION_POR_MIN RATE_LIMIT_CHECKOUT_POR_MIN RATE_LIMIT_INTERNA_POR_MIN; do
    export "$v=${!v:-100000}"
  done
  export ENVIOS_DESPACHO_SEGUNDOS="${ENVIOS_DESPACHO_SEGUNDOS:-3600}"
  export ENVIOS_ENTREGA_SEGUNDOS="${ENVIOS_ENTREGA_SEGUNDOS:-3600}"   # tampoco entrega solo salvo el escenario 17
else
  for v in "${LIMITES_VARS[@]}"; do unset "$v"; done
  [ "${E2E_FASE_CONSERVA_DESPACHO:-}" = 1 ] || unset ENVIOS_DESPACHO_SEGUNDOS ENVIOS_DESPACHO_INTERVALO_SEGUNDOS ENVIOS_ENTREGA_SEGUNDOS
fi

puerto() {
  case "$1" in
    productos) echo 8002;; envios) echo 8003;; envios2) echo 8013;; inventario) echo 8004;; carrito) echo 8005;;
    pedidos) echo 8006;; pagos) echo 8007;; proxy-carrito) echo 8105;; proxy-pagos) echo 8107;;
  esac
}

pedidos_env() {
  cat <<EOT
-e APP_ENV=local -e APP_DEBUG=false -e APP_KEY=$APP_KEY -e DB_CONNECTION=pgsql -e DB_HOST=127.0.0.1
-e DB_PORT=$PG_PORT -e DB_DATABASE=db_pedidos -e DB_USERNAME=usr_pedidos -e DB_PASSWORD=$PW_PEDIDOS
-e JWT_PUBLIC_KEY_PATH=/run/secrets/jwt-public.pem -e CACHE_STORE=file -e LOG_CHANNEL=stderr
-e API_CARRITO_URL=http://127.0.0.1:8105 -e API_PRODUCTOS_URL=http://127.0.0.1:8002
-e API_INVENTARIO_URL=http://127.0.0.1:8004 -e API_PAGOS_URL=http://127.0.0.1:8107
-e API_ENVIOS_URL=http://127.0.0.1:8003
-e SERVICE_TOKEN_PEDIDOS_CARRITO=$T_PEDIDOS_CARRITO -e SERVICE_TOKEN_PEDIDOS_INVENTARIO=$T_PEDIDOS_INVENTARIO
-e SERVICE_TOKEN_PEDIDOS_PAGOS=$T_PEDIDOS_PAGOS -e SERVICE_TOKEN_PEDIDOS_ENVIOS=$T_PEDIDOS_ENVIOS
-e SERVICE_TOKEN_PAGOS_PEDIDOS=$T_PAGOS_PEDIDOS -e SERVICE_TOKEN_ENVIOS_PEDIDOS=$T_ENVIOS_PEDIDOS
EOT
}

# Monta solo lo necesario, de solo lectura; storage y cache de bootstrap en tmpfs.
pedidos_docker() { # args: nombre-o-"" ; resto = comando
  local nombre="$1"; shift
  local A="$ROOT/api-pedidos"
  # shellcheck disable=SC2046
  docker run --rm ${nombre:+--name "$nombre"} --network host \
    -v "$A/app:/app/app:ro" -v "$A/config:/app/config:ro" -v "$A/routes:/app/routes:ro" \
    -v "$A/database:/app/database:ro" -v "$A/resources:/app/resources:ro" \
    -v "$A/bootstrap/app.php:/app/bootstrap/app.php:ro" -v "$A/bootstrap/providers.php:/app/bootstrap/providers.php:ro" \
    -v "$A/artisan:/app/artisan:ro" -v "$A/public:/app/public:ro" -v "$A/composer.json:/app/composer.json:ro" \
    -v "$PEDIDOS_VENDOR:/app/vendor:ro" -v "$E2E/.tmp/jwt-public.pem:/run/secrets/jwt-public.pem:ro" \
    --tmpfs /app/storage --tmpfs /app/bootstrap/cache \
    -e PHP_CLI_SERVER_WORKERS=4 $(pedidos_env) $(for v in "${LIMITES_VARS[@]}"; do [ -n "${!v+x}" ] && echo "-e $v"; done) -w /app pedidos-test-temporal \
    sh -c 'mkdir -p storage/framework/cache/data storage/framework/sessions storage/framework/views storage/logs; exec "$@"' sh "$@"
}

esperar() { # url intentos
  local i; for ((i=0;i<${2:-90};i++)); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$1")" = 200 ] && return 0; sleep 1
  done; echo "TIMEOUT esperando $1" >&2; return 1
}

arrancar() {
  local s="$1"; local log="$LOGS/$s.log"
  case "$s" in
    productos) setsid nohup python3 "$E2E/stubs/stub_server.py" productos 8002 >"$log" 2>&1 & echo $! >"$PIDS/$s.pid";;
    inventario) SERVICE_TOKEN_PEDIDOS_INVENTARIO="$T_PEDIDOS_INVENTARIO" setsid nohup python3 "$E2E/stubs/stub_server.py" inventario 8004 >"$log" 2>&1 & echo $! >"$PIDS/$s.pid";;
    proxy-pagos) setsid nohup python3 "$E2E/stubs/fault_proxy.py" 8107 8007 8108 >"$log" 2>&1 & echo $! >"$PIDS/$s.pid";;
    proxy-carrito) setsid nohup python3 "$E2E/stubs/fault_proxy.py" 8105 8005 8106 >"$log" 2>&1 & echo $! >"$PIDS/$s.pid";;
    carrito)
      ( cd "$ROOT/api-carrito" && export PORT=8005 DB_HOST=127.0.0.1 DB_PORT=$PG_PORT DB_DATABASE=db_carrito DB_USERNAME=usr_carrito \
        DB_PASSWORD=$PW_CARRITO JWT_PUBLIC_KEY_PATH="$E2E/.tmp/jwt-public.pem" SERVICE_TOKEN_PEDIDOS_CARRITO=$T_PEDIDOS_CARRITO \
        API_PRODUCTOS_URL=http://127.0.0.1:8002 API_INVENTARIO_URL=http://127.0.0.1:8004 && exec setsid node src/server.js ) >"$log" 2>&1 &
      echo $! >"$PIDS/$s.pid";;
    pagos)
      ( cd "$ROOT/api-pagos" && export PORT=8007 DB_HOST=127.0.0.1 DB_PORT=$PG_PORT DB_DATABASE=db_pagos DB_USERNAME=usr_pagos \
        DB_PASSWORD=$PW_PAGOS JWT_PUBLIC_KEY_PATH="$E2E/.tmp/jwt-public.pem" API_PEDIDOS_URL=http://127.0.0.1:8006 \
        SERVICE_TOKEN_PEDIDOS_PAGOS=$T_PEDIDOS_PAGOS SERVICE_TOKEN_PAGOS_PEDIDOS=$T_PAGOS_PEDIDOS \
        && exec setsid java -jar target/api-pagos-0.1.0.jar ) >"$log" 2>&1 &
      echo $! >"$PIDS/$s.pid";;
    envios|envios2)   # envios2: segunda instancia (otro puerto, misma BD) para el escenario 17
      ( cd "$ROOT/api-envios" && export DB_HOST=127.0.0.1 DB_PORT=$PG_PORT DB_DATABASE=db_envios DB_USERNAME=usr_envios \
        DB_PASSWORD=$PW_ENVIOS JWT_ISSUER=api-usuarios JWT_AUDIENCE=tienda-microservicios \
        JWT_PUBLIC_KEY_PATH="$E2E/.tmp/jwt-public.pem" SERVICE_TOKEN_PEDIDOS_ENVIOS=$T_PEDIDOS_ENVIOS \
        SERVICE_TOKEN_ENVIOS_PEDIDOS=$T_ENVIOS_PEDIDOS API_PEDIDOS_URL=http://127.0.0.1:8006 \
        PEDIDOS_TIMEOUT_SECONDS=3 NOTIFICACION_INTERVALO_SECONDS=${NOTIF_INTERVALO:-30} \
        && exec setsid "$ENVIOS_VENV/bin/uvicorn" --factory app.main:build_app --host 127.0.0.1 --port $(puerto "$s") ) >"$log" 2>&1 &
      echo $! >"$PIDS/$s.pid";;
    pedidos)
      docker rm -f mojarra-pedidos-e2e >/dev/null 2>&1
      setsid nohup "$E2E/servicios.sh" _pedidos_fg >"$log" 2>&1 &
      echo $! >"$PIDS/$s.pid";;
    pedidos-recuperar) pedidos_docker "" php artisan pedidos:recuperar;;
    *) echo "servicio desconocido: $s" >&2; return 2;;
  esac
}

detener() {
  local s="$1"
  if [ "$s" = pedidos ]; then docker kill mojarra-pedidos-e2e >/dev/null 2>&1; docker rm -f mojarra-pedidos-e2e >/dev/null 2>&1; fi
  if [ -f "$PIDS/$s.pid" ]; then
    local pid; pid=$(cat "$PIDS/$s.pid")
    kill -9 -- "-$pid" 2>/dev/null; kill -9 "$pid" 2>/dev/null
    rm -f "$PIDS/$s.pid"
  fi
  # Java/uvicorn/node pueden quedar huerfanos si setsid dio otro grupo: se barre por puerto propio.
  local p; p=$(puerto "$s"); [ -n "$p" ] && ss -ltnpH "sport = :$p" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u | xargs -r kill -9 2>/dev/null
  return 0
}

listo() {
  case "$1" in
    pedidos|pagos|carrito|envios|envios2|productos|inventario) esperar "http://127.0.0.1:$(puerto "$1")/ready" "${2:-90}";;
    proxy-*) sleep 0.5;;
  esac
}

cmd="${1:-}"; svc="${2:-}"
case "$cmd" in
  start) arrancar "$svc" && listo "$svc";;
  stop|kill) detener "$svc";;
  restart) detener "$svc"; sleep 1; arrancar "$svc" && listo "$svc";;
  _migrar_pedidos) pedidos_docker "" php artisan migrate --force;;
  _pedidos_fg)
    if [ "${E2E_SCHEDULER:-}" = 1 ]; then
      # Mismo CMD que api-pedidos/Dockerfile (recuperar al arrancar + schedule:work + servidor), tomado del archivo.
      CMD_DOCKERFILE=$(python3 -c 'import json,re,sys
t=open(sys.argv[1]).read()
m=re.findall(r"^CMD (\[.*\])\s*$",t,re.M)
print(json.loads(m[-1])[2])' "$ROOT/api-pedidos/Dockerfile")
      echo "CMD del Dockerfile: $CMD_DOCKERFILE"
      pedidos_docker mojarra-pedidos-e2e sh -c "$CMD_DOCKERFILE"
    else
      pedidos_docker mojarra-pedidos-e2e php artisan serve --host 0.0.0.0 --port 8006 --no-reload
    fi;;
  wait) listo "$svc" "${3:-90}";;
  *) echo "uso: $0 start|stop|kill|restart|wait <servicio>" >&2; exit 2;;
esac
