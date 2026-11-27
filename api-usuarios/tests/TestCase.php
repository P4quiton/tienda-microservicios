<?php

declare(strict_types=1);

namespace Tests;

use Illuminate\Foundation\Application;
use Illuminate\Foundation\Testing\TestCase as BaseTestCase;
use RuntimeException;

abstract class TestCase extends BaseTestCase
{
    public function createApplication(): Application
    {
        $basePath = dirname(__DIR__);

        if (! is_file($basePath.'/.env.testing')) {
            throw new RuntimeException(
                'Pruebas bloqueadas: falta .env.testing.'
            );
        }

        if (is_file($basePath.'/bootstrap/cache/config.php')) {
            throw new RuntimeException(
                'Pruebas bloqueadas: ejecuta php artisan config:clear.'
            );
        }

        $app = parent::createApplication();

        if (
            ! $app->environment('testing')
            || $app->configurationIsCached()
        ) {
            throw new RuntimeException(
                'Pruebas bloqueadas: entorno incorrecto.'
            );
        }

        $config = $app->make('config');

        if ($config->get('database.default') !== 'pgsql') {
            throw new RuntimeException(
                'Pruebas bloqueadas: conexion distinta de PostgreSQL.'
            );
        }

        $connection = $app->make('db')->connection();

        $expected = [
            'driver' => 'pgsql',
            'host' => '127.0.0.1',
            'port' => '15433',
            'database' => 'db_usuarios_test',
            'username' => 'usr_usuarios_test',
        ];

        foreach ($expected as $key => $value) {
            if ((string) $connection->getConfig($key) !== $value) {
                throw new RuntimeException(
                    'Pruebas bloqueadas: configuracion de base de datos incorrecta.'
                );
            }
        }

        $identity = $connection->selectOne(
            'SELECT current_database() AS database_name,
                    current_user AS username'
        );

        if (
            $identity->database_name !== 'db_usuarios_test'
            || $identity->username !== 'usr_usuarios_test'
        ) {
            throw new RuntimeException(
                'Pruebas bloqueadas: identidad de base de datos incorrecta.'
            );
        }

        if (
            $config->get('jwt.private_key_path')
                !== 'storage/testing-keys/jwt-private.pem'
            || $config->get('jwt.public_key_path')
                !== 'storage/testing-keys/jwt-public.pem'
        ) {
            throw new RuntimeException(
                'Pruebas bloqueadas: claves JWT incorrectas.'
            );
        }

        if ($config->get('cache.default') !== 'array') {
            throw new RuntimeException(
                'Pruebas bloqueadas: cache no aislada.'
            );
        }

        return $app;
    }
}
