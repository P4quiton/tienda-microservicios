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

Los endpoints del catálogo, su persistencia y las instrucciones de contenedorización se incorporarán en commits posteriores. Consulta el contrato vigente en [`../docs/api/productos.yaml`](../docs/api/productos.yaml).
