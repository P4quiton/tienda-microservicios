<?php

namespace Tests\Feature;

use App\Pedidos\Pedido;
use Firebase\JWT\JWT;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Str;
use Tests\TestCase;

/** PATCH /api/pedidos/{id}/estado: solo Envíos, pagado -> enviado (contrato 1.1.0). */
final class EstadoEnviadoTest extends TestCase
{
    private string $tokenEnvios;

    private string $rutaPublica = '';

    protected function setUp(): void
    {
        parent::setUp();
        $this->tokenEnvios = 'envios-'.bin2hex(random_bytes(16));
        config(['pedidos.tokens_entrantes' => ['pagos' => 'pagos-'.bin2hex(random_bytes(16)), 'envios' => $this->tokenEnvios]]);
    }

    protected function tearDown(): void
    {
        if ($this->rutaPublica !== '') {
            @unlink($this->rutaPublica);
        }
        parent::tearDown();
    }

    private function postgres(): void
    {
        if (getenv('TEST_POSTGRES') !== '1') {
            $this->markTestSkipped('Requiere PostgreSQL de pruebas y TEST_POSTGRES=1.');
        }
        $this->assertSame(0, Artisan::call('migrate'));
    }

    private function pedido(string $estado): Pedido
    {
        $usuario = (string) Str::uuid();

        return Pedido::create([
            'id' => (string) Str::uuid(), 'usuario_id' => $usuario, 'clave_idempotencia' => (string) Str::uuid(),
            'huella' => str_repeat('b', 64), 'items' => [['producto_id' => (string) Str::uuid(), 'cantidad' => 1, 'precio_unitario' => '5.00']],
            'direccion' => ['codigo_postal' => '38000', 'calle' => 'E', 'ciudad' => 'C', 'estado' => 'G'],
            'metodo_pago' => 'tarjeta_simulada', 'costo_envio' => '4.00', 'total' => '9.00', 'estado' => $estado,
            'paso' => 'terminado', 'carrito_id' => $usuario, 'carrito_version' => '1', 'creado_en' => now(),
        ]);
    }

    private function parchear(string $id, array $cuerpo, ?string $token, ?string $clave = null)
    {
        $cabeceras = $token === null ? [] : ['X-Service-Token' => $token];
        if ($clave !== '') {
            $cabeceras['Idempotency-Key'] = $clave ?? (string) Str::uuid();
        }

        return $this->flushHeaders()->withHeaders($cabeceras)->patchJson("/api/pedidos/$id/estado", $cuerpo);
    }

    public function test_envios_marca_enviado_un_pedido_pagado_y_repetir_es_idempotente(): void
    {
        $this->postgres();
        $pedido = $this->pedido('pagado');
        try {
            $clave = (string) Str::uuid();
            $this->parchear($pedido->id, ['estado' => 'enviado'], $this->tokenEnvios, $clave)
                ->assertOk()->assertJsonPath('data.estado', 'enviado')->assertJsonPath('data.id', $pedido->id);
            $this->assertSame('enviado', $pedido->fresh()->estado);
            // Misma clave y otra clave: 200 sin nuevo efecto.
            $this->parchear($pedido->id, ['estado' => 'enviado'], $this->tokenEnvios, $clave)->assertOk()->assertJsonPath('data.estado', 'enviado');
            $this->parchear($pedido->id, ['estado' => 'enviado'], $this->tokenEnvios)->assertOk()->assertJsonPath('data.estado', 'enviado');
        } finally {
            Pedido::whereKey($pedido->id)->delete();
        }
    }

    public function test_otras_transiciones_dan_409_y_no_cambian_el_pedido(): void
    {
        $this->postgres();
        foreach (['pendiente', 'cancelado'] as $estado) {
            $pedido = $this->pedido($estado);
            try {
                $this->parchear($pedido->id, ['estado' => 'enviado'], $this->tokenEnvios)->assertStatus(409);
                $this->assertSame($estado, $pedido->fresh()->estado);
            } finally {
                Pedido::whereKey($pedido->id)->delete();
            }
        }
        $pagado = $this->pedido('pagado');
        try {
            foreach (['pendiente', 'pagado', 'cancelado'] as $destino) {
                $this->parchear($pagado->id, ['estado' => $destino], $this->tokenEnvios)->assertStatus(409);
            }
            $this->assertSame('pagado', $pagado->fresh()->estado);
        } finally {
            Pedido::whereKey($pagado->id)->delete();
        }
    }

    public function test_clave_reutilizada_con_otro_pedido_da_409(): void
    {
        $this->postgres();
        $a = $this->pedido('pagado');
        $b = $this->pedido('pagado');
        try {
            $clave = (string) Str::uuid();
            $this->parchear($a->id, ['estado' => 'enviado'], $this->tokenEnvios, $clave)->assertOk();
            $this->parchear($b->id, ['estado' => 'enviado'], $this->tokenEnvios, $clave)->assertStatus(409);
            $this->assertSame('pagado', $b->fresh()->estado);
        } finally {
            Pedido::whereIn('id', [$a->id, $b->id])->delete();
        }
    }

    public function test_pedido_inexistente_da_404(): void
    {
        $this->postgres();
        $this->parchear((string) Str::uuid(), ['estado' => 'enviado'], $this->tokenEnvios)->assertStatus(404);
    }

    public function test_validacion_de_idempotency_key_id_y_cuerpo(): void
    {
        $id = (string) Str::uuid();
        $this->parchear($id, ['estado' => 'enviado'], $this->tokenEnvios, '')->assertStatus(422);
        $this->parchear($id, ['estado' => 'enviado'], $this->tokenEnvios, 'no-es-uuid')->assertStatus(422);
        $this->parchear('no-uuid', ['estado' => 'enviado'], $this->tokenEnvios)->assertStatus(422);
        $this->parchear($id, [], $this->tokenEnvios)->assertStatus(422);
        $this->parchear($id, ['estado' => 'enviado', 'x' => 1], $this->tokenEnvios)->assertStatus(422);
        $this->parchear($id, ['estado' => 'volando'], $this->tokenEnvios)->assertStatus(422);
        $this->parchear($id, ['estado' => ['enviado']], $this->tokenEnvios)->assertStatus(422);
    }

    public function test_solo_envios_con_su_token_especifico(): void
    {
        $id = (string) Str::uuid();
        $cuerpo = ['estado' => 'enviado'];
        $this->parchear($id, $cuerpo, null)->assertStatus(401);
        $this->parchear($id, $cuerpo, '')->assertStatus(401);
        $this->parchear($id, $cuerpo, 'equivocado')->assertStatus(401);
        $this->parchear($id, $cuerpo, strtoupper($this->tokenEnvios))->assertStatus(401);
        $this->parchear($id, $cuerpo, config('pedidos.tokens_entrantes.pagos'))->assertStatus(403); // otro par
        $this->parchear($id, $cuerpo, 'tc')->assertStatus(401); // token saliente de otro par
    }

    public function test_jwt_de_cliente_o_admin_no_puede_mutar_estados(): void
    {
        $clave = openssl_pkey_new(['private_key_bits' => 2048]);
        openssl_pkey_export($clave, $privada);
        $this->rutaPublica = tempnam(sys_get_temp_dir(), 'pedidos-jwt-');
        file_put_contents($this->rutaPublica, openssl_pkey_get_details($clave)['key']);
        config(['pedidos.jwt_public_key_path' => $this->rutaPublica]);
        $id = (string) Str::uuid();
        foreach (['cliente', 'admin'] as $rol) {
            $jwt = JWT::encode(['sub' => (string) Str::uuid(), 'role' => $rol, 'iss' => 'api-usuarios', 'aud' => 'tienda-microservicios',
                'iat' => time() - 5, 'exp' => time() + 600], $privada, 'RS256');
            $this->flushHeaders()->withToken($jwt)->withHeaders(['Idempotency-Key' => (string) Str::uuid()])
                ->patchJson("/api/pedidos/$id/estado", ['estado' => 'enviado'])->assertStatus(401);
            $this->parchear($id, ['estado' => 'enviado'], $jwt)->assertStatus(401); // JWT dentro de X-Service-Token
        }
    }

    public function test_secreto_de_envios_no_configurado_nunca_autentica(): void
    {
        config(['pedidos.tokens_entrantes.envios' => null]);
        $this->parchear((string) Str::uuid(), ['estado' => 'enviado'], '')->assertStatus(401);
        $this->parchear((string) Str::uuid(), ['estado' => 'enviado'], 'x')->assertStatus(401);
    }
}
