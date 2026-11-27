#!/usr/bin/env bash
# Prueba E2E por HTTP real de Carrito, Pedidos, Pagos y Envios (+ stubs de Productos/Inventario).
# Levanta PG17 temporal, servicios nativos/imagen existente, corre escenarios y limpia todo.
# Variables opcionales: CARRITO_NODE_MODULES, MVN, ENVIOS_VENV, PEDIDOS_VENDOR, SKIP_BUILD=1 (reusa el jar de Pagos).
set -uo pipefail
E2E="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$E2E/.." && pwd)"
TMP="$E2E/.tmp"
MVN="${MVN:-/tmp/tienda-pagos-maven.8R9aeV/apache-maven-3.9.11/bin/mvn}"
M2="${M2:-/mnt/disco/desarrollo-local/.m2/repository}"
ENVIOS_VENV="${ENVIOS_VENV:-/mnt/disco/desarrollo-local/tienda/envios/api-envios/.venv}"
PEDIDOS_VENDOR="${PEDIDOS_VENDOR:-/dev/shm/pedidos-runtime.7ARkWi/app/vendor}"
CARRITO_NODE_MODULES="${CARRITO_NODE_MODULES:-/mnt/disco/desarrollo-local/tienda/carrito/api-carrito/node_modules}"
CARRITO_LINK=""   # symlink temporal a node_modules de Carrito si este arbol no lo trae (se retira al limpiar)
PG_NAME=mojarra-pg-e2e; PG_PORT=55450
export NOTIF_INTERVALO=3   # Envios: ciclo del outbox corto para la prueba
export E2E_FASE=altos      # escenarios 1-14, 16, 17: limites altos, despacho/entrega lentos; el 15 (el ultimo en correr) pasa a 'default' (ver servicios.sh)
SERVICIOS=(pedidos pagos carrito envios envios2 inventario productos proxy-pagos proxy-carrito)

limpiar() {
  echo "== Limpieza =="
  for s in "${SERVICIOS[@]}"; do [ -f "$TMP/env.sh" ] && "$E2E/servicios.sh" stop "$s" >/dev/null 2>&1; done
  docker rm -f mojarra-pedidos-e2e "$PG_NAME" >/dev/null 2>&1
  [ -n "$CARRITO_LINK" ] && [ -L "$CARRITO_LINK" ] && rm -f "$CARRITO_LINK"
  for p in 8002 8003 8004 8005 8006 8007 8013 8105 8106 8107 8108 "$PG_PORT"; do
    ss -ltnH "sport = :$p" 2>/dev/null | grep -q . && echo "AVISO: puerto $p sigue ocupado"
  done
  return 0
}
trap limpiar EXIT
# Depuracion: MANTENER=1 deja todo arriba sin correr escenarios; ./run.sh --limpiar lo apaga.
[ "${1:-}" = "--limpiar" ] && exit 0

die() { echo "ERROR: $*" >&2; exit 1; }

# --- Preflight ---------------------------------------------------------------------------
for p in 8002 8003 8004 8005 8006 8007 8013 8105 8106 8107 8108 "$PG_PORT"; do
  ss -ltnH "sport = :$p" | grep -q . && die "puerto $p ocupado; libéralo antes de correr"
done
docker image inspect pedidos-test-temporal postgres:17 >/dev/null 2>&1 || die "faltan imagenes locales pedidos-test-temporal/postgres:17"
[ -d "$PEDIDOS_VENDOR" ] || die "no existe $PEDIDOS_VENDOR"
[ -x "$ENVIOS_VENV/bin/python" ] || die "no existe venv de Envios"
docker rm -f "$PG_NAME" >/dev/null 2>&1
if [ ! -e "$ROOT/api-carrito/node_modules" ]; then
  [ -d "$CARRITO_NODE_MODULES" ] || die "api-carrito sin node_modules y no existe CARRITO_NODE_MODULES=$CARRITO_NODE_MODULES"
  ln -s "$CARRITO_NODE_MODULES" "$ROOT/api-carrito/node_modules" && CARRITO_LINK="$ROOT/api-carrito/node_modules"
fi

# --- Secretos y claves (solo en e2e/.tmp, ignorado por git) -----------------------------------
rm -rf "$TMP"; mkdir -p "$TMP/pids" "$TMP/logs"
rnd() { python3 -c 'import secrets;print(secrets.token_hex(24))'; }
{
  echo "export PG_PORT=$PG_PORT PEDIDOS_VENDOR='$PEDIDOS_VENDOR' ENVIOS_VENV='$ENVIOS_VENV'"
  echo "export PG_PASSWORD=$(rnd) APP_KEY='base64:$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')'"
  for u in USUARIOS PRODUCTOS ENVIOS INVENTARIO CARRITO PEDIDOS PAGOS; do echo "export PW_$u=$(rnd)"; done
  for t in PEDIDOS_CARRITO PEDIDOS_INVENTARIO PEDIDOS_PAGOS PAGOS_PEDIDOS PEDIDOS_ENVIOS ENVIOS_PEDIDOS; do echo "export T_$t=$(rnd)"; done
} >"$TMP/env.sh"
chmod 600 "$TMP/env.sh"
# shellcheck disable=SC1091
source "$TMP/env.sh"
"$ENVIOS_VENV/bin/python" - "$TMP" <<'PY'
import sys
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization as s
k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
d = sys.argv[1]
open(f"{d}/jwt-private.pem", "wb").write(k.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()))
open(f"{d}/jwt-public.pem", "wb").write(k.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo))
# Segundo par: sirve para firmar un JWT "falso" (clave ajena) en la prueba de seguridad.
k2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
open(f"{d}/jwt-private-ajena.pem", "wb").write(k2.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()))
PY
chmod 600 "$TMP"/*.pem; chmod 644 "$TMP/jwt-public.pem"

# --- PostgreSQL 17 temporal; el script real de infra crea roles/BD (NOSUPERUSER, REVOKE PUBLIC) --
echo "== PostgreSQL =="
docker run -d --rm --name "$PG_NAME" -p 127.0.0.1:$PG_PORT:5432 --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" \
  -e POSTGRES_USUARIOS_PASSWORD="$PW_USUARIOS" -e POSTGRES_PRODUCTOS_PASSWORD="$PW_PRODUCTOS" \
  -e POSTGRES_ENVIOS_PASSWORD="$PW_ENVIOS" -e POSTGRES_INVENTARIO_PASSWORD="$PW_INVENTARIO" \
  -e POSTGRES_CARRITO_PASSWORD="$PW_CARRITO" -e POSTGRES_PEDIDOS_PASSWORD="$PW_PEDIDOS" \
  -e POSTGRES_PAGOS_PASSWORD="$PW_PAGOS" \
  -v "$ROOT/infra/postgres/init/01-create-databases.sh:/docker-entrypoint-initdb.d/01-create-databases.sh:ro" \
  postgres:17 >/dev/null || die "no arranca PG"
for i in $(seq 60); do docker exec "$PG_NAME" pg_isready -h 127.0.0.1 -q 2>/dev/null && break; sleep 1; done
docker exec "$PG_NAME" pg_isready -h 127.0.0.1 -q || die "PG no listo"
sleep 1
docker exec -e PGPASSWORD="$PW_CARRITO" "$PG_NAME" psql -h 127.0.0.1 -U usr_carrito -d db_carrito -Atc \
  "select current_user, (select rolsuper from pg_roles where rolname=current_user)" || die "rol carrito no conecta"

# --- Migraciones con el rol de cada servicio (Envios y Pagos migran solos al arrancar) --------
echo "== Migraciones =="
( cd "$ROOT/api-carrito" && DB_HOST=127.0.0.1 DB_PORT=$PG_PORT DB_DATABASE=db_carrito DB_USERNAME=usr_carrito \
  DB_PASSWORD=$PW_CARRITO node src/migrate.js ) || die "migracion carrito"
"$E2E/servicios.sh" _migrar_pedidos 2>&1 || die "migracion pedidos"

# --- Compilar Pagos (Maven offline, sin docker build) ------------------------------------------
if [ -z "${SKIP_BUILD:-}" ]; then
  echo "== Compilando Pagos =="
  ( cd "$ROOT/api-pagos" && "$MVN" -o -B -q -Dmaven.repo.local="$M2" package -DskipTests ) || die "mvn package"
fi
[ -f "$ROOT/api-pagos/target/api-pagos-0.1.0.jar" ] || die "falta el jar de Pagos"

# --- Arranque ---------------------------------------------------------------------------------
echo "== Arrancando servicios =="
for s in productos inventario proxy-carrito proxy-pagos carrito envios pagos pedidos; do
  "$E2E/servicios.sh" start "$s" || { tail -30 "$TMP/logs/$s.log"; die "no arranca $s"; }
  echo "  $s listo"
done

if [ -n "${MANTENER:-}" ]; then trap - EXIT; echo "Servicios arriba (MANTENER=1). Corre tests/e2e.py y luego ./run.sh --limpiar"; exit 0; fi

# --- Escenarios -------------------------------------------------------------------------------
echo "== Escenarios =="
"$ENVIOS_VENV/bin/python" -B "$E2E/tests/e2e.py" 2>&1 | tee "$TMP/e2e-salida.log"
RC=${PIPESTATUS[0]}
cp "$TMP/e2e-salida.log" "$E2E/ultima-salida.log" 2>/dev/null
echo "== Codigo de salida de escenarios: $RC =="
exit "$RC"
