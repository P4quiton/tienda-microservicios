FROM composer:2.9@sha256:b09bccd91a78fe8a9ab4b33d707b862e8fe54fec17782e32683ad2a69c46867d AS composer
FROM php:8.5-cli@sha256:e33c9c494e41d56e18c4e9609b98dbdeac68682916cd7d2917582492a6e15618 AS php-base

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev \
    && docker-php-ext-install pdo_pgsql \
    && find /var/lib/apt/lists -type f -delete
WORKDIR /app

FROM php-base AS dependencias
COPY --from=composer /usr/bin/composer /usr/local/bin/composer
COPY composer.json composer.lock ./
RUN apt-get update && apt-get install -y --no-install-recommends unzip \
    && composer install --no-dev --prefer-dist --no-interaction --no-scripts --no-autoloader
COPY . .
RUN composer dump-autoload --optimize --no-dev --no-interaction --no-scripts

FROM php-base
COPY --from=dependencias --chown=www-data:www-data /app /app
USER www-data
# Envíos consulta Pedidos durante checkout; se necesitan solicitudes concurrentes.
ENV PHP_CLI_SERVER_WORKERS=4
EXPOSE 8006
# Recuperación durable: reconcilia al arrancar y cada minuto (schedule:work) sin depender de clientes.
CMD ["sh", "-c", "php artisan pedidos:recuperar; php artisan schedule:work & exec php artisan serve --host=0.0.0.0 --port=8006 --no-reload"]
