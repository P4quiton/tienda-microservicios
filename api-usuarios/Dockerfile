
FROM composer:2 AS composer-bin

FROM php:8.5-apache

ENV COMPOSER_ALLOW_SUPERUSER=1

WORKDIR /var/www/html

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libicu-dev \
        libpq-dev \
        unzip \
    && docker-php-ext-install -j$(nproc) \
        intl \
        pdo_pgsql \
        opcache \
    && rm -rf /var/lib/apt/lists/*

COPY --from=composer-bin /usr/bin/composer /usr/local/bin/composer

RUN cp "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini"

RUN a2enmod rewrite headers

RUN sed -i 's/Listen 80/Listen 8001/' \
        /etc/apache2/ports.conf \
    && sed -i 's/<VirtualHost \*:80>/<VirtualHost *:8001>/' \
        /etc/apache2/sites-available/000-default.conf \
    && sed -i 's|DocumentRoot /var/www/html|DocumentRoot /var/www/html/public|' \
        /etc/apache2/sites-available/000-default.conf

COPY docker/apache.conf /etc/apache2/conf-available/api-usuarios.conf
COPY docker/php.ini /usr/local/etc/php/conf.d/99-api-usuarios.ini

RUN a2enconf api-usuarios

COPY composer.json composer.lock ./

RUN composer install \
    --no-dev \
    --no-interaction \
    --no-progress \
    --prefer-dist \
    --no-scripts \
    --no-autoloader

COPY . .

RUN mkdir -p \
        storage/framework/cache/data \
        storage/framework/sessions \
        storage/framework/views \
        storage/logs \
        bootstrap/cache \
    && composer dump-autoload --no-dev --optimize \
    && chown -R www-data:www-data storage bootstrap/cache \
    && chmod -R u+rwX,g+rwX,o-rwx storage bootstrap/cache

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD php -r 'exit(@file_get_contents("http://127.0.0.1:8001/health") === false ? 1 : 0);'

CMD ["apache2-foreground"]
