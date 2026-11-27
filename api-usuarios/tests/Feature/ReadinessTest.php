<?php

declare(strict_types=1);

namespace Tests\Feature;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class ReadinessTest extends TestCase
{
    use RefreshDatabase;

    private string $privateKeyPath;
    private string $publicKeyPath;

    protected function setUp(): void
    {
        parent::setUp();

        $key = openssl_pkey_new([
            'private_key_type' => OPENSSL_KEYTYPE_RSA,
            'private_key_bits' => 3072,
        ]);
        $details = openssl_pkey_get_details($key);
        $this->privateKeyPath = tempnam(sys_get_temp_dir(), 'usuarios-jwt-private-');
        $this->publicKeyPath = tempnam(sys_get_temp_dir(), 'usuarios-jwt-public-');
        openssl_pkey_export($key, $privateKey);
        file_put_contents($this->privateKeyPath, $privateKey);
        file_put_contents($this->publicKeyPath, $details['key']);
        config()->set('jwt.private_key_path', $this->privateKeyPath);
        config()->set('jwt.public_key_path', $this->publicKeyPath);
    }

    protected function tearDown(): void
    {
        @unlink($this->privateKeyPath);
        @unlink($this->publicKeyPath);

        parent::tearDown();
    }

    public function test_readiness_requires_the_users_migration_record(): void
    {
        $this->getJson('/ready')->assertOk()
            ->assertExactJson(['status' => 'ok', 'service' => 'api-usuarios']);

        DB::table('migrations')
            ->where('migration', '0001_01_01_000000_create_usuarios_table')
            ->delete();

        $this->getJson('/ready')->assertServiceUnavailable()
            ->assertExactJson(['status' => 'unavailable', 'service' => 'api-usuarios']);
    }
}
