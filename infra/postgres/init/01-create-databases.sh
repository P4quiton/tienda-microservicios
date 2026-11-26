
#!/usr/bin/env bash

set -euo pipefail

export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

create_service_database() {
    local database="$1"
    local username="$2"
    local password="$3"

    psql \
        --username "$POSTGRES_USER" \
        --dbname postgres \
        --set ON_ERROR_STOP=1 \
        --set db_name="$database" \
        --set db_user="$username" \
        --set db_password="$password" <<'EOSQL'

CREATE ROLE :"db_user"
    WITH LOGIN
    PASSWORD :'db_password'
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION;

CREATE DATABASE :"db_name"
    OWNER :"db_user";

REVOKE ALL PRIVILEGES
    ON DATABASE :"db_name"
    FROM PUBLIC;

GRANT CONNECT
    ON DATABASE :"db_name"
    TO :"db_user";

EOSQL

    echo "Base de datos creada: $database"
}

create_service_database \
    db_usuarios usr_usuarios "$POSTGRES_USUARIOS_PASSWORD"

create_service_database \
    db_productos usr_productos "$POSTGRES_PRODUCTOS_PASSWORD"

create_service_database \
    db_envios usr_envios "$POSTGRES_ENVIOS_PASSWORD"

create_service_database \
    db_inventario usr_inventario "$POSTGRES_INVENTARIO_PASSWORD"

create_service_database \
    db_carrito usr_carrito "$POSTGRES_CARRITO_PASSWORD"

create_service_database \
    db_pedidos usr_pedidos "$POSTGRES_PEDIDOS_PASSWORD"

create_service_database \
    db_pagos usr_pagos "$POSTGRES_PAGOS_PASSWORD"

psql --username "$POSTGRES_USER" --dbname postgres \
    --set ON_ERROR_STOP=1 <<'EOSQL'

REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;

EOSQL

echo "Inicializacion de PostgreSQL completada."

unset PGPASSWORD
