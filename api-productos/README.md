# API Productos

Servicio de catálogo desarrollado con Laravel 13 y PHP 8.5. El servicio escucha en el puerto `8002` y utiliza la base `db_productos` con el rol dedicado `usr_productos`.

## Desarrollo local

Requisitos: PHP 8.5 con `pdo_pgsql` y Composer.

Desde esta carpeta, instala dependencias y prepara la configuración local:

```bash
composer install
cp .env.example .env
php artisan key:generate
```

Configura `.env` con las credenciales locales de Productos. Para ejecutar la aplicación:

```bash
php artisan serve --host=0.0.0.0 --port=8002
```

## Endpoints

| Método | Ruta | Acceso |
|---|---|---|
| GET | `/api/productos` | Público; filtros `q`, `categoria`, `pagina` y `limite` |
| GET | `/api/productos/{id}` | Público; UUID |
| POST | `/api/productos` | JWT RS256 con rol `admin` |

El catálogo muestra 20 productos por página de forma predeterminada, permite hasta 100 y busca por nombre o descripción. El alta requiere `nombre`, `descripcion`, `precio`, `categoria` e `imagen_url`; precio es una cadena decimal positiva con dos posiciones. Se rechazan campos adicionales. La validación JWT requiere configurar `JWT_ISSUER`, `JWT_AUDIENCE` y `JWT_PUBLIC_KEY_PATH` con la clave pública compartida localmente por el servicio de Usuarios.

Consulta el contrato vigente en [`../docs/api/productos.yaml`](../docs/api/productos.yaml). Las rutas de salud y la contenedorización se documentarán al incorporar esos componentes.
