<?php

namespace Tests\Feature;

use Firebase\JWT\JWT;
use Illuminate\Support\Str;
use Tests\TestCase;

final class PedidosTest extends TestCase
{
    public function test_health_y_rechazo_de_credenciales(): void
    {
        $this->getJson('/health')
            ->assertOk()
            ->assertExactJson(['status' => 'ok', 'service' => 'api-pedidos']);
        $this->postJson('/api/pedidos', [])->assertUnauthorized()->assertJsonPath('success', false);
        $this->patchJson('/api/pedidos/'.Str::uuid().'/estado', ['estado' => 'pagado'])
            ->assertUnauthorized();

        config(['pedidos.tokens_entrantes.pagos' => bin2hex(random_bytes(32))]);
        $this->withHeader('X-Service-Token', config('pedidos.tokens_entrantes.pagos'))
            ->patchJson('/api/pedidos/'.Str::uuid().'/estado', ['estado' => 'pagado'])
            ->assertForbidden();
    }

    public function test_otro_usuario_no_puede_consultar_el_historial(): void
    {
        $clave = openssl_pkey_new(['private_key_bits' => 2048]);
        openssl_pkey_export($clave, $privada);
        $ruta = tempnam(sys_get_temp_dir(), 'pedidos-jwt-');
        file_put_contents($ruta, openssl_pkey_get_details($clave)['key']);

        try {
            config(['pedidos.jwt_public_key_path' => $ruta]);
            $token = JWT::encode([
                'sub' => (string) Str::uuid(),
                'role' => 'cliente',
                'iss' => 'api-usuarios',
                'aud' => 'tienda-microservicios',
                'iat' => time(),
                'exp' => time() + 600,
            ], $privada, 'RS256');

            $this->withToken($token)
                ->getJson('/api/pedidos/usuario/'.Str::uuid())
                ->assertForbidden();
        } finally {
            unlink($ruta);
        }
    }
}
