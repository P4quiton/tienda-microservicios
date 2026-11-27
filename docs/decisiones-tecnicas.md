# Decisiones técnicas

Acuerdos de arquitectura aprobados por el coordinador; compartir con el equipo. Versiones mayores objetivo, no dependencias verificadas ni instaladas todavía.

| Servicio | Stack | BD |
|---|---|---|
| Usuarios, Productos, Pedidos | PHP 8.5 / Laravel 13 | PostgreSQL 17 |
| Envíos | Python 3.12 / FastAPI | PostgreSQL 17 |
| Inventario | Go 1.26 / Gin | PostgreSQL 17 |
| Carrito | Node 24 LTS / Express 5 | PostgreSQL 17 |
| Pagos | Java 21 / Spring Boot 3.5 | PostgreSQL 17 |
| Reseñas | Python 3.12 / FastAPI | MongoDB 8.0 |
| Frontend | Angular 21 / Node 24 LTS | Ninguna |

Fijar versiones patch y lockfiles al inicializar y comprobar compatibilidad, build y soporte. Cada contenedor escucha en 0.0.0.0 y puerto del README. BD `db_<servicio>`, usuario `usr_<servicio>`. PostgreSQL: revocar CONNECT de PUBLIC en bases de aplicación, otorgar solo al propietario autorizado; roles sin privilegios administrativos. MongoDB: rol limitado a db_resenas. Migraciones y datos de prueba propios. No usar latest, no copiar secretos, preferir multietapa y usuario no root.

UUID v4, JWT RS256, JSON estándar, importes decimal string en MXN, HTTP REST, Nginx como proxy, Pedidos como coordinador. No Kafka/RabbitMQ ni pasarela real. Health y readiness obligatorios. GitHub Container Registry opcional al integrar; inicialmente imágenes locales.

Entorno verificado: Docker Desktop 4.100.1, Engine 29.9.3, Compose 5.7.1, Kubernetes/kubectl 1.36.1 (kubeadm). Espacio libre observado: 27.29 GB; vigilar crecimiento. No se exige idéntica versión de Docker a todos los compañeros.

## Revisión checkout 1.1

Saga simplificada con PostgreSQL de Pedidos como fuente de verdad. Un checkout activo por usuario; snapshot transaccional versionado en Carrito y linea_id irrepetible. Permitir agregar durante checkout; finalizar únicamente snapshot comprado. Recuperación periódica durable, sin Redis ni broker. PATCH solo Envíos al despacho real. Mantener estados comerciales originales y estado_checkout interno separado.

## Decisiones de Integración (Sección 9)

- **Identidad en Reseñas**: El servicio de Reseñas obtiene el `usuario_id` directamente de los claims del JWT RS256 verificado (`sub`) y no de un campo controlado por el cliente en el cuerpo de la petición. Esto garantiza la integridad de la autoría y evita la suplantación de identidad (impersonation), aunque difiera de la rúbrica inicial que sugería un campo en el payload.
- **Finalización de Checkout**: El proceso de compra utiliza la finalización del snapshot del Carrito (`POST /api/carrito/{usuario_id}/finalizar`). Esto retira únicamente los artículos y cantidades exactas presentes en el snapshot del checkout (identificados por `linea_id` y `version_original`), preservando las nuevas líneas que el usuario haya podido añadir al carrito mientras el proceso de pago estaba en curso. El endpoint para vaciar el carrito por completo sigue disponible para uso explícito.
- **Simulación de Negocio**: Tanto el procesamiento de pagos en el servicio de Pagos como los plazos de entrega y tránsitos en el servicio de Envíos son simulados mediante temporizadores y estados internos. No existe integración real con pasarelas financieras ni transportistas logísticos en este MVP.
- **Estrategia de Migraciones**: En Compose, las migraciones que no se ejecutan al arranque se aplican como paso explícito mediante `docker compose run`. Ejecutarlas como `Jobs` en Kubernetes es un plan pendiente para Kubernetes, no una implementación existente. Este enfoque evita condiciones de carrera y bloqueos cuando se levantan múltiples réplicas de un mismo servicio de forma concurrente.
- **Exposición de Puertos**: Los puertos publicados en `localhost` (8001-8008, 4200, 15432, 27017) están destinados exclusivamente a tareas de diagnóstico, desarrollo y demostración. En entornos productivos, el acceso se realiza a través de la infraestructura de red interna y balanceadores de carga.
- **Autorización y CORS**: La configuración de CORS regula el acceso desde orígenes web específicos en el navegador, pero no sustituye los controles de autenticación (JWT) y autorización (roles `cliente`/`admin` y propiedad de recursos) implementados en cada microservicio.

## Tabla de comparación de variables de entorno

| Variable en `.env` / `init-env.ps1` | Uso en `docker-compose.yml` (`${VAR}`) | Aplicación / Servicio que la lee |
|---|---|---|
| `POSTGRES_USER` | `POSTGRES_USER` | postgres (Admin) |
| `POSTGRES_PASSWORD` | `POSTGRES_PASSWORD` | postgres (Admin) |
| `POSTGRES_USUARIOS_PASSWORD` | `POSTGRES_USUARIOS_PASSWORD` | postgres (init scripts), api-usuarios (`DB_PASSWORD`) |
| `POSTGRES_PRODUCTOS_PASSWORD` | `POSTGRES_PRODUCTOS_PASSWORD` | postgres (init scripts), api-productos (`DB_PASSWORD`) |
| `POSTGRES_ENVIOS_PASSWORD` | `POSTGRES_ENVIOS_PASSWORD` | postgres (init scripts), api-envios (`DB_PASSWORD`) |
| `POSTGRES_INVENTARIO_PASSWORD` | `POSTGRES_INVENTARIO_PASSWORD` | postgres (init scripts), api-inventario (`DB_PASSWORD`) |
| `POSTGRES_CARRITO_PASSWORD` | `POSTGRES_CARRITO_PASSWORD` | postgres (init scripts), api-carrito (`DB_PASSWORD`) |
| `POSTGRES_PEDIDOS_PASSWORD` | `POSTGRES_PEDIDOS_PASSWORD` | postgres (init scripts), api-pedidos (`DB_PASSWORD`) |
| `POSTGRES_PAGOS_PASSWORD` | `POSTGRES_PAGOS_PASSWORD` | postgres (init scripts), api-pagos (`DB_PASSWORD`) |
| `MONGO_INITDB_ROOT_USERNAME` | `MONGO_INITDB_ROOT_USERNAME` | mongodb (Admin) |
| `MONGO_INITDB_ROOT_PASSWORD` | `MONGO_INITDB_ROOT_PASSWORD` | mongodb (Admin) |
| `MONGO_RESENAS_PASSWORD` | `MONGO_RESENAS_PASSWORD` | mongodb (init scripts), api-resenas (`MONGO_PASSWORD`) |
| `USUARIOS_APP_KEY` | `USUARIOS_APP_KEY` | api-usuarios (`APP_KEY`) |
| `PRODUCTOS_APP_KEY` | `PRODUCTOS_APP_KEY` | api-productos (`APP_KEY`) |
| `PEDIDOS_APP_KEY` | `PEDIDOS_APP_KEY` | api-pedidos (`APP_KEY`) |
| `SERVICE_TOKEN_PEDIDOS_CARRITO` | `SERVICE_TOKEN_PEDIDOS_CARRITO` | api-pedidos, api-carrito |
| `SERVICE_TOKEN_PEDIDOS_INVENTARIO` | `SERVICE_TOKEN_PEDIDOS_INVENTARIO` | api-pedidos, api-inventario |
| `SERVICE_TOKEN_PEDIDOS_ENVIOS` | `SERVICE_TOKEN_PEDIDOS_ENVIOS` | api-pedidos, api-envios |
| `SERVICE_TOKEN_PEDIDOS_PAGOS` | `SERVICE_TOKEN_PEDIDOS_PAGOS` | api-pedidos, api-pagos |
| `SERVICE_TOKEN_ENVIOS_PEDIDOS` | `SERVICE_TOKEN_ENVIOS_PEDIDOS` | api-envios, api-pedidos |
| `SERVICE_TOKEN_PAGOS_PEDIDOS` | `SERVICE_TOKEN_PAGOS_PEDIDOS` | api-pagos, api-pedidos |
| `POSTGRES_HOST_PORT` | `POSTGRES_HOST_PORT` (opcional; predeterminado 15432) | docker-compose (publicación solo en 127.0.0.1) |
| `MONGO_HOST_PORT` | `MONGO_HOST_PORT` (opcional; predeterminado 27017) | docker-compose (publicación solo en 127.0.0.1) |
| `USUARIOS_HOST_PORT` | `USUARIOS_HOST_PORT` (opcional; predeterminado 8001) | docker-compose (publicación solo en 127.0.0.1) |
| Puertos de Productos, Envíos, Inventario, Carrito, Pedidos, Pagos y Reseñas | No son variables de entorno | Compose fija `127.0.0.1:8002` a `127.0.0.1:8008`, respectivamente |
| `FRONTEND_HOST_PORT` | `FRONTEND_HOST_PORT` (opcional; predeterminado 4200) | docker-compose (publicación solo en 127.0.0.1) |

## Validación de scripts PowerShell

El script `scripts/init-env.ps1` fue revisado por lectura para PowerShell 5.1; probado solo con PowerShell 7.4 en contenedor Docker usando la imagen `mcr.microsoft.com/powershell:7.4-ubuntu-22.04`. El parser AST confirmó que el script es sintácticamente válido en esa versión.

**Prueba ejecutada:**
```bash
tmpdir=$(mktemp -d /tmp/cont-b7-docs.XXXXXX)
mkdir -p "$tmpdir/scripts"
cp scripts/init-env.ps1 "$tmpdir/scripts/init-env.ps1"
cp .env.example "$tmpdir/.env.example"
docker run --rm -v "$tmpdir:/work" mcr.microsoft.com/powershell:7.4-ubuntu-22.04 pwsh -NoLogo -NoProfile -Command '& /work/scripts/init-env.ps1; $tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile("/work/scripts/init-env.ps1", [ref]$tokens, [ref]$errors) | Out-Null; if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }; if (!(Test-Path /work/.env)) { exit 1 }; "Parser check PASSED; .env generado en directorio temporal."'
python3 -c 'import shutil,sys; shutil.rmtree(sys.argv[1])' "$tmpdir"
```

**Resultado:** probado con PowerShell 7.4.6; parser check PASSED y `.env` generado correctamente en el directorio temporal, eliminado al terminar.
