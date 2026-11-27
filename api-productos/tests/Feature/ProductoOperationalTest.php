<?php

namespace Tests\Feature;

use App\Models\Producto;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use PHPUnit\Framework\Attributes\DataProvider;
use Tests\TestCase;

class ProductoOperationalTest extends TestCase
{
    use RefreshDatabase;

    private ?string $keyPath = null;

    protected function tearDown(): void
    {
        if ($this->keyPath !== null) {
            unlink($this->keyPath);
        }

        parent::tearDown();
    }

    public function test_readiness_fails_without_product_table(): void
    {
        Schema::dropIfExists('productos');

        $this->getJson('/ready')
            ->assertServiceUnavailable()
            ->assertExactJson(['status' => 'unavailable', 'service' => 'api-productos']);

        $this->getJson('/health')->assertOk();
    }

    public function test_readiness_requires_the_product_migration_record(): void
    {
        $key = openssl_pkey_new(['private_key_type' => OPENSSL_KEYTYPE_RSA, 'private_key_bits' => 3072]);
        $details = openssl_pkey_get_details($key);
        $this->keyPath = tempnam(sys_get_temp_dir(), 'productos-jwt-ready-');
        file_put_contents($this->keyPath, $details['key']);
        config()->set('services.jwt.public_key_path', $this->keyPath);

        $this->getJson('/ready')->assertOk()
            ->assertExactJson(['status' => 'ok', 'service' => 'api-productos']);

        DB::table('migrations')
            ->where('migration', '2026_11_26_042306_create_productos_table')
            ->delete();

        $this->getJson('/ready')->assertServiceUnavailable()
            ->assertExactJson(['status' => 'unavailable', 'service' => 'api-productos']);
    }

    public function test_readiness_fails_without_public_key(): void
    {
        config()->set('services.jwt.public_key_path', null);
        $this->getJson('/ready')
            ->assertServiceUnavailable()
            ->assertExactJson(['status' => 'unavailable', 'service' => 'api-productos']);

        config()->set('services.jwt.public_key_path', __FILE__.'.inexistente');
        $this->getJson('/ready')->assertServiceUnavailable();
    }

    public function test_readiness_fails_without_a_database_connection(): void
    {
        $defaultConnection = config('database.default');
        config()->set('database.default', 'productos-inexistente');

        try {
            $this->getJson('/ready')
                ->assertServiceUnavailable()
                ->assertExactJson(['status' => 'unavailable', 'service' => 'api-productos']);
            $this->getJson('/health')->assertOk();
        } finally {
            config()->set('database.default', $defaultConnection);
        }
    }

    public static function invalidPublicKeys(): array
    {
        return [
            'contenido ilegible por OpenSSL' => [null],
            'RSA de 2048 bits' => [['private_key_type' => OPENSSL_KEYTYPE_RSA, 'private_key_bits' => 2048]],
            'curva elíptica' => [['private_key_type' => OPENSSL_KEYTYPE_EC, 'curve_name' => 'prime256v1']],
        ];
    }

    #[DataProvider('invalidPublicKeys')]
    public function test_readiness_rejects_invalid_public_keys(?array $options): void
    {
        $contents = $options === null
            ? 'No es una clave pública'
            : openssl_pkey_get_details(openssl_pkey_new($options))['key'];
        $this->keyPath = tempnam(sys_get_temp_dir(), 'productos-jwt-invalid-');
        file_put_contents($this->keyPath, $contents);
        config()->set('services.jwt.public_key_path', $this->keyPath);

        $this->getJson('/ready')->assertServiceUnavailable();
    }

    public function test_catalog_and_mutation_limits_are_separate_and_return_retry_after(): void
    {
        $producto = Producto::factory()->create();
        $origin = 'https://tienda.example';
        config()->set('cors.allowed_origins', [$origin]);

        for ($request = 0; $request < 119; $request++) {
            $this->getJson('/api/productos')->assertOk();
        }

        $this->getJson('/api/productos/'.$producto->id)->assertOk();

        $limited = $this->get('/api/productos', [
            'Origin' => $origin,
            'X-Forwarded-For' => '198.51.100.77',
        ]);
        $limited
            ->assertTooManyRequests()
            ->assertHeader('Content-Type', 'application/json')
            ->assertHeader('Access-Control-Allow-Origin', $origin)
            ->assertJsonPath('success', false)
            ->assertHeader('Retry-After');
        $this->assertContains((int) $limited->headers->get('Retry-After'), range(1, 60));

        $this->withServerVariables(['REMOTE_ADDR' => '192.0.2.42']);
        $this->getJson('/api/productos', ['X-Forwarded-For' => '127.0.0.1'])
            ->assertTooManyRequests();
        $this->getJson('/api/productos', ['X-Forwarded-For' => '198.51.100.77'])
            ->assertOk();
        $this->withServerVariables(['REMOTE_ADDR' => '127.0.0.1']);

        for ($request = 0; $request < 30; $request++) {
            $this->postJson('/api/productos', [])->assertUnauthorized();
        }

        $this->postJson('/api/productos', [])
            ->assertTooManyRequests()
            ->assertJsonPath('success', false)
            ->assertHeader('Retry-After');
    }

    #[\PHPUnit\Framework\Attributes\BackupGlobals(true)]
    public function test_cors_responds_only_to_configured_origin(): void
    {
        $origin = 'http://localhost:4200';
        $_SERVER['CORS_ALLOWED_ORIGINS'] = $_ENV['CORS_ALLOWED_ORIGINS'] = $origin;
        $this->refreshApplication();
        $this->assertSame(0, \Illuminate\Support\Facades\Artisan::call('migrate'));
        config()->set('cors.allowed_origins_patterns', config('cors.allowed_origins_patterns'));

        $this->options('/api/productos', headers: [
            'Origin' => $origin,
            'Access-Control-Request-Method' => 'POST',
            'Access-Control-Request-Headers' => 'Authorization, Content-Type',
        ])->assertNoContent()->assertHeader('Access-Control-Allow-Origin', $origin);

        $this->getJson('/api/productos', ['Origin' => 'https://ajeno.example'])
            ->assertOk()
            ->assertHeaderMissing('Access-Control-Allow-Origin');

        $this->getJson('/api/productos', ['Origin' => $origin])
            ->assertOk()
            ->assertHeader('Access-Control-Allow-Origin', $origin);
    }

    public function test_request_over_php_body_limit_returns_json_413(): void
    {
        $this->call('POST', '/api/productos', server: ['CONTENT_LENGTH' => PHP_INT_MAX])
            ->assertStatus(413)
            ->assertHeader('Content-Type', 'application/json')
            ->assertJsonPath('success', false);
    }
}
