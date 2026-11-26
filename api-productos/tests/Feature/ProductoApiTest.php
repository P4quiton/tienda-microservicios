<?php

namespace Tests\Feature;

use App\Models\Producto;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Tests\TestCase;

class ProductoApiTest extends TestCase
{
    use RefreshDatabase;

    private ?\OpenSSLAsymmetricKey $privateKey = null;

    private ?string $publicKeyPath = null;

    protected function setUp(): void
    {
        parent::setUp();

        $this->privateKey = openssl_pkey_new([
            'private_key_type' => OPENSSL_KEYTYPE_RSA,
            'private_key_bits' => 2048,
        ]);

        $keyDetails = openssl_pkey_get_details($this->privateKey);
        $this->publicKeyPath = tempnam(sys_get_temp_dir(), 'productos-jwt-public-');
        file_put_contents($this->publicKeyPath, $keyDetails['key']);

        config()->set('services.jwt.public_key_path', $this->publicKeyPath);
        config()->set('services.jwt.issuer', 'api-usuarios');
        config()->set('services.jwt.audience', 'tienda-microservicios');
    }

    protected function tearDown(): void
    {
        if ($this->publicKeyPath !== null && file_exists($this->publicKeyPath)) {
            unlink($this->publicKeyPath);
        }

        parent::tearDown();
    }

    public function test_health_and_readiness_return_service_status(): void
    {
        $this->getJson('/health')
            ->assertOk()
            ->assertExactJson(['status' => 'ok', 'service' => 'api-productos']);

        $this->getJson('/ready')
            ->assertOk()
            ->assertExactJson(['status' => 'ok', 'service' => 'api-productos']);
    }

    public function test_catalog_supports_search_category_and_pagination(): void
    {
        Producto::factory()->create([
            'nombre' => 'Cámara compacta',
            'categoria' => 'Electrónica',
            'precio' => '1200.00',
        ]);
        Producto::factory()->create([
            'nombre' => 'Audífonos inalámbricos',
            'categoria' => 'Electrónica',
            'precio' => '899.99',
        ]);
        Producto::factory()->create([
            'nombre' => 'Lámpara de escritorio',
            'categoria' => 'Hogar',
            'precio' => '549.00',
        ]);

        $this->getJson('/api/productos?q=aud%C3%ADfonos&categoria=electr%C3%B3nica&pagina=1&limite=1')
            ->assertOk()
            ->assertJsonPath('success', true)
            ->assertJsonPath('data.total', 1)
            ->assertJsonPath('data.pagina', 1)
            ->assertJsonPath('data.limite', 1)
            ->assertJsonPath('data.items.0.nombre', 'Audífonos inalámbricos')
            ->assertJsonPath('data.items.0.precio', '899.99');
    }

    public function test_detail_returns_product_and_unknown_uuid_returns_contract_error(): void
    {
        $producto = Producto::factory()->create(['precio' => '25.00']);

        $this->getJson('/api/productos/'.$producto->id)
            ->assertOk()
            ->assertJsonPath('data.id', $producto->id)
            ->assertJsonPath('data.precio', '25.00');

        $this->getJson('/api/productos/'.Str::uuid())
            ->assertNotFound()
            ->assertJsonPath('success', false)
            ->assertJsonStructure(['success', 'message', 'errors']);
    }

    public function test_only_admin_jwt_can_create_products(): void
    {
        $payload = [
            'nombre' => 'Producto protegido',
            'descripcion' => 'Descripción de prueba.',
            'precio' => '10.00',
            'categoria' => 'Hogar',
            'imagen_url' => 'https://example.com/imagen.jpg',
        ];

        $this->postJson('/api/productos', $payload)
            ->assertUnauthorized()
            ->assertJsonPath('success', false);

        $this->withToken($this->makeToken('cliente'))
            ->postJson('/api/productos', $payload)
            ->assertForbidden()
            ->assertJsonPath('success', false);

        $this->withToken($this->makeToken('admin'))
            ->postJson('/api/productos', $payload)
            ->assertCreated()
            ->assertJsonPath('success', true)
            ->assertJsonPath('data.nombre', 'Producto protegido')
            ->assertJsonPath('data.precio', '10.00');

        $this->assertDatabaseCount('productos', 1);
    }

    public function test_create_rejects_invalid_price_and_undeclared_fields(): void
    {
        $token = $this->makeToken('admin');
        $payload = [
            'nombre' => 'Producto protegido',
            'descripcion' => 'Descripción de prueba.',
            'precio' => '0.00',
            'categoria' => 'Hogar',
            'imagen_url' => 'https://example.com/imagen.jpg',
        ];

        $this->withToken($token)
            ->postJson('/api/productos', $payload)
            ->assertUnprocessable()
            ->assertJsonValidationErrors('precio');

        $payload['precio'] = '10.00';
        $payload['stock'] = 5;

        $this->withToken($token)
            ->postJson('/api/productos', $payload)
            ->assertUnprocessable()
            ->assertJsonValidationErrors('body');

        $this->assertDatabaseCount('productos', 0);
    }

    private function makeToken(string $role): string
    {
        $issuedAt = time();
        $header = ['alg' => 'RS256', 'typ' => 'JWT'];
        $claims = [
            'sub' => (string) Str::uuid(),
            'role' => $role,
            'iss' => 'api-usuarios',
            'aud' => 'tienda-microservicios',
            'iat' => $issuedAt,
            'exp' => $issuedAt + 3600,
        ];

        $unsignedToken = $this->base64UrlEncode(json_encode($header, JSON_THROW_ON_ERROR))
            .'.'.$this->base64UrlEncode(json_encode($claims, JSON_THROW_ON_ERROR));

        openssl_sign($unsignedToken, $signature, $this->privateKey, OPENSSL_ALGO_SHA256);

        return $unsignedToken.'.'.$this->base64UrlEncode($signature);
    }

    private function base64UrlEncode(string $value): string
    {
        return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
    }
}
