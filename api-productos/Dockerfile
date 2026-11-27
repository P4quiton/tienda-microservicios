FROM php:8.5.4-cli-alpine3.22 AS php-base

RUN apk add --no-cache libpq oniguruma \
    && apk add --no-cache --virtual .build-deps postgresql-dev oniguruma-dev $PHPIZE_DEPS \
    && docker-php-ext-install mbstring pdo_pgsql \
    && apk del .build-deps

FROM php-base AS vendor

WORKDIR /app
COPY --from=composer:2.9.5 /usr/bin/composer /usr/bin/composer
COPY . .
RUN composer install --no-dev --no-interaction --prefer-dist --optimize-autoloader

FROM php-base AS runtime

RUN addgroup -S -g 10001 app \
    && adduser -S -D -H -u 10001 -G app app

WORKDIR /var/www/html
COPY --chown=app:app . .
COPY --from=vendor --chown=app:app /app/vendor ./vendor

RUN mkdir -p storage/framework/cache/data storage/framework/sessions storage/framework/views storage/logs bootstrap/cache \
    && php artisan package:discover --ansi \
    && chown -R app:app storage bootstrap/cache

COPY docker/entrypoint.sh /usr/local/bin/api-productos-entrypoint
RUN chmod 0755 /usr/local/bin/api-productos-entrypoint

USER app
EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8002/health || exit 1

ENTRYPOINT ["api-productos-entrypoint"]
CMD ["php", "artisan", "serve", "--host=0.0.0.0", "--port=8002"]
