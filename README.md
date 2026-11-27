# Tienda Microservicios

Monorepo con ocho APIs, Angular y PostgreSQL 17/MongoDB 8 en la red Docker `red-tienda`.

## Tabla de puertos localhost

| Puerto | Servicio | Tecnología | BD |
|---|---|---|---|
| 8001 | api-usuarios | PHP 8.5 / Laravel 13 | PostgreSQL |
| 8002 | api-productos | PHP 8.5 / Laravel 13 | PostgreSQL |
| 8003 | api-envios | Python 3.12 / FastAPI | PostgreSQL |
| 8004 | api-inventario | Go 1.26 / Gin | PostgreSQL |
| 8005 | api-carrito | Node 24 / Express 5 | PostgreSQL |
| 8006 | api-pedidos | PHP 8.5 / Laravel 13 | PostgreSQL |
| 8007 | api-pagos | Java 21 / Spring Boot 3.5 | PostgreSQL |
| 8008 | api-resenas | Python 3.12 / FastAPI | MongoDB |
| 4200 | frontend-tienda | Angular 21 / Nginx | Ninguna |
| 15432 | postgres | PostgreSQL 17 | - |
| 27017 | mongodb | MongoDB 8.0 | - |

## Arranque del entorno

### Requisitos previos

- Docker Engine 24+ y Docker Compose 2.20+
- OpenSSL (para generar claves JWT)
- PowerShell (Windows; probado con PowerShell 7.4, 5.1 solo revisado por lectura) o bash (Linux)

### Pasos de inicialización

#### En Linux

```bash
# 1. No hay un script Linux equivalente a scripts/init-env.ps1.
# Crear .env desde la plantilla y generar credenciales aleatorias localmente.
set -euo pipefail
test ! -e .env || { echo '.env ya existe; consérvalo y no lo sobrescribas.' >&2; exit 1; }
umask 077
cp .env.example .env
for name in POSTGRES_PASSWORD POSTGRES_USUARIOS_PASSWORD POSTGRES_PRODUCTOS_PASSWORD POSTGRES_ENVIOS_PASSWORD POSTGRES_INVENTARIO_PASSWORD POSTGRES_CARRITO_PASSWORD POSTGRES_PEDIDOS_PASSWORD POSTGRES_PAGOS_PASSWORD MONGO_INITDB_ROOT_PASSWORD MONGO_RESENAS_PASSWORD SERVICE_TOKEN_PEDIDOS_CARRITO SERVICE_TOKEN_PEDIDOS_INVENTARIO SERVICE_TOKEN_PEDIDOS_ENVIOS SERVICE_TOKEN_PEDIDOS_PAGOS SERVICE_TOKEN_ENVIOS_PEDIDOS SERVICE_TOKEN_PAGOS_PEDIDOS; do
  value=$(openssl rand -hex 32)
  sed -i "s|^${name}=.*|${name}=${value}|" .env
done
for name in USUARIOS_APP_KEY PRODUCTOS_APP_KEY PEDIDOS_APP_KEY; do
  value="base64:$(openssl rand -base64 32)"
  sed -i "s|^${name}=.*|${name}=${value}|" .env
done

# 2. Generar claves JWT RSA de 3072 bits (la privada solo para api-usuarios).
mkdir -p api-usuarios/storage/keys
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out api-usuarios/storage/keys/jwt-private.pem
openssl pkey -in api-usuarios/storage/keys/jwt-private.pem -pubout -out api-usuarios/storage/keys/jwt-public.pem

# 3. Construir imágenes de aplicación.
docker compose --parallel 2 build

# 4. Levantar servicios base de datos
docker compose up -d --no-build postgres mongodb

# 5. Esperar a que las bases estén healthy
docker compose ps

# 6. Ejecutar migraciones por servicio
docker compose run --rm --no-deps api-usuarios php artisan migrate --force
docker compose run --rm --no-deps api-productos php artisan migrate --force
docker compose run --rm --no-deps api-carrito node src/migrate.js
docker compose run --rm --no-deps api-pedidos php artisan migrate --force

# 7. Levantar APIs aplicaciones y frontend
docker compose up -d --no-build
```

#### En Windows (PowerShell; probado con 7.4)

```powershell
# 1. Generar .env con variables y credenciales aleatorias
.\scripts\init-env.ps1
.\scripts\init-jwt.ps1

# 2. Construir imágenes de aplicación
docker compose --parallel 2 build

# 3. Levantar servicios base de datos
docker compose up -d --no-build postgres mongodb

# 4. Esperar a que las bases estén healthy
docker compose ps

# 5. Ejecutar migraciones por servicio
docker compose run --rm --no-deps api-usuarios php artisan migrate --force
docker compose run --rm --no-deps api-productos php artisan migrate --force
docker compose run --rm --no-deps api-carrito node src/migrate.js
docker compose run --rm --no-deps api-pedidos php artisan migrate --force

# 6. Levantar APIs aplicaciones y frontend
docker compose up -d --no-build
```

> **Nota**: Inventario, Envíos y Pagos ejecutan sus migraciones al arrancar (Go + SQL, FastAPI + SQL migrations y Spring Boot + Flyway). Usuarios, Productos, Carrito y Pedidos requieren el paso manual indicado. Los Jobs de migración en Kubernetes están planeados, no implementados.

### Verificación del arranque

```bash
# Verificar health endpoints (liveness) y ready endpoints (readiness)
curl http://localhost:8001/health
curl http://localhost:8001/ready
curl http://localhost:8002/health
curl http://localhost:8006/ready
curl http://localhost:8005/ready

# Verificar frontend
curl http://localhost:4200/

# Verificar bases de datos
docker compose exec postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres -tAc "SELECT 1"'
docker compose exec mongodb mongosh --eval "db.adminCommand('ping')"
```

## Migraciones por servicio

| Servicio | Base de datos | Usuario DB | Comando migración | Comportamiento |
|---|---|---|---|---|
| Usuarios | db_usuarios | usr_usuarios | `docker compose run --rm --no-deps api-usuarios php artisan migrate --force` | Manual (ejecutar explícitamente) |
| Productos | db_productos | usr_productos | `docker compose run --rm --no-deps api-productos php artisan migrate --force` | Manual (ejecutar explícitamente) |
| Carrito | db_carrito | usr_carrito | `docker compose run --rm --no-deps api-carrito node src/migrate.js` | Manual (ejecutar explícitamente) |
| Pedidos | db_pedidos | usr_pedidos | `docker compose run --rm --no-deps api-pedidos php artisan migrate --force` | Manual (ejecutar explícitamente) |
| Inventario | db_inventario | usr_inventario | `migrate()` en arranque | Automático al iniciar |
| Envíos | db_envios | usr_envios | `migrate()` en arranque | Automático al iniciar |
| Pagos | db_pagos | usr_pagos | Flyway al arranque | Automático al iniciar |
| Reseñas | db_resenas | usr_resenas | `ensure_review_indexes()` al arranque | Crea índices únicos; `/ready` responde 503 mientras los índices no estén listos |

El checkout de Pedidos tiene un límite propio de **5 solicitudes por minuto** (`RATE_LIMIT_CHECKOUT_POR_MIN` en Compose), además de los límites generales.

## Arquitectura y Decisiones Técnicas

### Comunicación entre servicios

- **Autenticación**: JWT RS256 emitido por `api-usuarios`.
  - Emisor (iss): `api-usuarios`
  - Audiencia (aud): `tienda-microservicios`
  - Identificador (sub): UUID v4
  - Roles: `cliente`, `admin`
  - TTL: 60 minutos (3600 segundos)

- **Tokens de servicio**: Claims separados para cada par de comunicación (p. ej. `SERVICE_TOKEN_PEDIDOS_INVENTARIO`).

- **Idempotencia**: `Idempotency-Key` UUID v4 en headers de mutaciones críticas.

### Políticas de rate limiting

- Consultas: 120/min
- Mutaciones: 30/min
- Internas (comunicación entre servicios): 300/min
- Respuestas: 429 JSON con header `Retry-After`

### Seguridad

- CORS restrictivo: orígenes configurables por servicio.
- Claves privadas solo en `api-usuarios`, montadas como secret read-only.
- Roles y permisos por servicio, sin privilegios de admin.

### Decisiones de integración

- Reseñas obtiene `usuario_id` del `sub` del JWT validado, no del cuerpo enviado por el cliente; así evita suplantación aunque difiera de la rúbrica inicial.
- Checkout finaliza el snapshot comprado para conservar artículos agregados durante el proceso; el endpoint para vaciar el carrito sigue disponible.
- El pago y los plazos/tránsitos de envío son simulados; no hay pasarela ni transportista real.
- Los puertos publicados en localhost son para diagnóstico y demostración, no exposición pública.
- CORS restringe orígenes en navegador, pero no reemplaza autenticación ni autorización.

Consulta [Decisiones técnicas](docs/decisiones-tecnicas.md) para el detalle.

### Documentación adicional

- `docs/arquitectura.md`: detalle de componentes y red.
- `docs/flujo-compra.md`: saga de checkout y manejo de estados.
- `docs/seguridad.md`: políticas de autenticación y autorización.
- `docs/api/`: contratos OpenAPI (usuarios.yaml, productos.yaml, etc.).
