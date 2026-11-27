# API Usuarios

Microservicio REST encargado de la gestión de usuarios, autenticación y autorización del proyecto Tienda Microservicios.

## Tecnologías

- PHP 8.5.
- Laravel 13.
- PostgreSQL 17.
- Composer 2.
- JWT RS256 mediante firebase/php-jwt.
- Apache HTTP Server.
- Docker y Docker Compose.
- PHPUnit 12.

## Responsabilidades

- Registro de clientes.
- Autenticación mediante correo electrónico y contraseña.
- Emisión de tokens JWT.
- Consulta de perfiles de usuarios.
- Control de acceso mediante roles.
- Creación controlada de administradores.
- Verificación de disponibilidad del servicio.

## Endpoints

| Método | Endpoint | Autenticación |
|---|---|---|
| POST | /api/usuarios/registro | Pública |
| POST | /api/usuarios/login | Pública |
| GET | /api/usuarios/{id} | JWT |
| GET | /health | Pública |
| GET | /ready | Pública |

La especificación OpenAPI se encuentra en `docs/api/usuarios.yaml`, desde la raíz del repositorio.

## Configuración local

Requisitos:

- PHP 8.5 con las extensiones requeridas por Composer.
- Composer 2.
- Docker Desktop.
- PostgreSQL disponible mediante Docker Compose.

Instalar las dependencias:

```bash
composer install
```

Crear el archivo `.env` a partir de `.env.example` y configurar `DB_PASSWORD` con el valor correspondiente a `POSTGRES_USUARIOS_PASSWORD` del entorno principal.

Generar la clave de aplicación:

```bash
php artisan key:generate
```

Generar un par de claves RSA de 3072 bits:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out storage/keys/jwt-private.pem

openssl pkey -in storage/keys/jwt-private.pem -pubout -out storage/keys/jwt-public.pem
```

Las claves deben generarse únicamente cuando no existan previamente. No deben incorporarse al repositorio.

Ejecutar las migraciones:

```bash
php artisan migrate
```

Iniciar el servidor de desarrollo:

```bash
composer dev
```

La API estará disponible en `http://127.0.0.1:8001`.

## Registro

Ejemplo de petición:

```json
{
  "nombre": "Usuario de ejemplo",
  "correo": "usuario@example.com",
  "contrasena": "ContrasenaDeEjemplo123!"
}
```

El registro público asigna exclusivamente el rol `cliente`. No se permite asignar roles administrativos ni identificadores desde la petición.

## Inicio de sesión

Ejemplo de petición:

```json
{
  "correo": "usuario@example.com",
  "contrasena": "ContrasenaDeEjemplo123!"
}
```

La respuesta incluye un token de acceso JWT, el tipo Bearer, su duración y los datos públicos del usuario.

Para consumir endpoints protegidos:

```http
Authorization: Bearer TOKEN
```

## Autenticación y autorización

Los JWT utilizan el algoritmo RS256 y claves RSA de 3072 bits.

- Emisor: `api-usuarios`.
- Audiencia: `tienda-microservicios`.
- Vigencia: 3600 segundos.
- Identificador del usuario: claim `sub`.
- Rol: claim `role`.

La clave privada permanece exclusivamente bajo el control del servicio de Usuarios. Los demás microservicios utilizan la clave pública para verificar los tokens.

Los clientes solamente pueden consultar su propio perfil. Los administradores pueden consultar perfiles de otros usuarios.

## Creación de administradores

La creación de administradores no está disponible mediante endpoints públicos.

Se realiza mediante el comando interactivo:

```bash
php artisan usuarios:crear-admin
```

El comando solicita nombre, correo, contraseña y confirmación. Rechaza correos duplicados y requiere confirmación antes de crear la cuenta.

## Seguridad

- Hashing de contraseñas mediante Argon2id.
- Memoria Argon2id: 65536 KiB.
- Iteraciones: 4.
- Hilos: 1.
- Validación de firma, emisor, audiencia y expiración de JWT.
- Validación de datos de entrada.
- Rechazo de propiedades JSON no permitidas.
- Restricciones de integridad en PostgreSQL.
- Normalización de correos electrónicos.
- Protección contra escalamiento de privilegios.
- Manejo centralizado de excepciones.
- Respuestas de error sin detalles internos.
- Modo de depuración desactivado.
- Límite de peticiones de 256 KiB.
- CORS restrictivo por defecto.
- Exclusión de archivos sensibles mediante Git y Docker.

### Rate limiting

| Operación | Límite |
|---|---|
| Registro | 5 solicitudes/minuto por IP |
| Login | 5 solicitudes/minuto por IP |
| Login | 5 solicitudes/minuto por correo |
| Consulta de perfiles | 300 solicitudes/minuto por IP |
| Consulta de perfiles | 120 solicitudes/minuto por usuario autenticado |

Los contadores actuales son locales a cada instancia. Una implementación distribuida requeriría un almacenamiento compartido.

La configuración definitiva de proxies de confianza se realizará durante la integración con el frontend y Kubernetes.

## Docker

El microservicio incluye:

- Dockerfile.
- .dockerignore.
- Configuración Apache.
- Configuración PHP.
- Declaración del servicio en el Docker Compose principal.

Configuración interna:

| Parámetro | Valor |
|---|---|
| Servicio | api-usuarios |
| Puerto | 8001 |
| Red | red-tienda |
| Host PostgreSQL | postgres |
| Puerto PostgreSQL | 5432 |
| Base de datos | db_usuarios |
| Usuario PostgreSQL | usr_usuarios |

La variable `USUARIOS_APP_KEY` debe configurarse en el archivo `.env` principal antes de iniciar el servicio.

Las claves RSA se montan externamente en modo de solo lectura. Los archivos de entorno y las claves no forman parte de la imagen.

La construcción de la imagen, las migraciones y las verificaciones HTTP contenerizadas se realizarán durante la integración general.

Comandos previstos desde la raíz del repositorio:

```bash
docker compose build api-usuarios
docker compose up -d api-usuarios
docker compose exec api-usuarios php artisan migrate --force
```

## Health y readiness

`GET /health` comprueba que la aplicación está disponible.

`GET /ready` verifica la conexión con PostgreSQL, la disponibilidad de la tabla de usuarios y la configuración de claves JWT.

## Pruebas

Se realizaron pruebas funcionales manuales sobre:

- Registro correcto y datos inválidos.
- Correos duplicados.
- Hashing de contraseñas.
- Autenticación válida e inválida.
- Emisión y manipulación de tokens.
- Autorización de clientes y administradores.
- Creación controlada de administradores.
- Rate limiting.
- CORS.
- Manejo de excepciones.
- Límites de tamaño de peticiones.
- Health y readiness.

### Entorno automatizado

El servicio incluye un entorno PostgreSQL independiente para PHPUnit:

- Base de datos: `db_usuarios_test`.
- Usuario: `usr_usuarios_test`.
- Puerto: 15433.
- Credenciales independientes.
- Claves RSA exclusivas de pruebas.
- Caché y sesiones en memoria.
- Protección contra ejecución accidental en la base de datos de desarrollo.

Se utiliza `.env.testing.example` como plantilla para generar `.env.testing`, con credenciales propias, una APP_KEY independiente y las claves RSA correspondientes.

Para levantar PostgreSQL de pruebas:

```bash
docker compose --env-file .env.testing -p usuarios-test -f compose.test.yaml up -d --wait
```

Para ejecutar las pruebas:

```bash
php artisan test
```

Resultados verificados:

- 5 pruebas automatizadas aprobadas.
- 15 aserciones aprobadas.
- Bloqueo correcto ante la ausencia de `.env.testing`.
- Base de datos de desarrollo intacta.

Las pruebas automatizadas exhaustivas de negocio, concurrencia y resiliencia quedan como trabajo posterior.

## Estado

- Funcionalidades REST: implementadas y validadas manualmente.
- Autenticación y autorización: implementadas y validadas.
- Infraestructura de pruebas: implementada y validada.
- Configuración Docker: implementada y validada sintácticamente.
- Construcción y ejecución de la imagen: pendientes de integración.
- Integración con otros microservicios: pendiente.