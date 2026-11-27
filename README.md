## Configuración del microservicio de Usuarios

El servicio de Usuarios está implementado con PHP 8.5, Laravel 13, PostgreSQL 17 y autenticación JWT RS256.

### Configuración inicial en Windows

Desde la raíz del repositorio:

```powershell
.\scripts\init-env.ps1
.\scripts\init-jwt.ps1
```

El primer script genera las variables de entorno y credenciales independientes. El segundo genera las claves RSA de 3072 bits.

Los archivos existentes no se sobrescriben. Si ya existe `.env`, deben incorporarse manualmente las variables nuevas sin modificar las credenciales de las bases de datos existentes.

### Comunicación interna

Los microservicios validarán los JWT emitidos por Usuarios utilizando la misma clave pública RSA.

- Emisor: `api-usuarios`.
- Audiencia: `tienda-microservicios`.
- Algoritmo: RS256.
- Duración: 3600 segundos.
- Identificador: UUID v4 mediante el claim `sub`.
- Roles: `cliente` y `admin`.

La clave privada se proporciona exclusivamente a Usuarios. La clave pública se proporciona a los servicios que necesitan verificar tokens.

### Ejecución mediante Docker Compose

El servicio está declarado en el archivo `docker-compose.yml` principal.

```bash
docker compose build api-usuarios
docker compose up -d api-usuarios
docker compose exec api-usuarios php artisan migrate --force
```

Endpoints de infraestructura:

- `http://localhost:8001/health`
- `http://localhost:8001/ready`

La construcción y ejecución contenerizada deberán validarse durante la integración general.

### Documentación específica

- `api-usuarios/README.md`: configuración, seguridad y pruebas.
- `docs/api/usuarios.yaml`: contrato OpenAPI versión 1.1.0.
- `api-usuarios/compose.test.yaml`: infraestructura PostgreSQL independiente para PHPUnit.