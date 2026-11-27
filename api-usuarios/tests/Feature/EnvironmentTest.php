<?php

declare(strict_types=1);

namespace Tests\Feature;

use App\Services\JwtService;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class EnvironmentTest extends TestCase
{
    public function test_application_runs_in_testing_environment(): void
    {
        $this->assertTrue(app()->environment('testing'));

        $this->assertFalse(config('app.debug'));
    }

    public function test_database_connection_is_isolated(): void
    {
        $identity = DB::selectOne(
            'SELECT current_database() AS database_name,
                    current_user AS username'
        );

        $this->assertSame(
            'db_usuarios_test',
            $identity->database_name
        );

        $this->assertSame(
            'usr_usuarios_test',
            $identity->username
        );

        $this->assertSame(
            '15433',
            (string) config('database.connections.pgsql.port')
        );
    }

    public function test_cache_and_session_are_isolated(): void
    {
        $this->assertSame('array', config('cache.default'));

        $this->assertSame('array', config('session.driver'));
    }

    public function test_testing_jwt_keys_are_available(): void
    {
        $this->assertSame(
            'storage/testing-keys/jwt-private.pem',
            config('jwt.private_key_path')
        );

        $this->assertSame(
            'storage/testing-keys/jwt-public.pem',
            config('jwt.public_key_path')
        );

        app(JwtService::class)->assertReady();

        $this->assertTrue(true);
    }

    public function test_database_has_no_administrative_privileges(): void
    {
        $role = DB::selectOne(
            'SELECT rolsuper,
                    rolcreatedb,
                    rolcreaterole,
                    rolreplication,
                    rolbypassrls
             FROM pg_roles
             WHERE rolname = current_user'
        );

        $this->assertFalse($role->rolsuper);
        $this->assertFalse($role->rolcreatedb);
        $this->assertFalse($role->rolcreaterole);
        $this->assertFalse($role->rolreplication);
        $this->assertFalse($role->rolbypassrls);
    }
}
