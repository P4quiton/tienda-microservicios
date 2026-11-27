<?php

namespace Tests\Feature;

use App\Pedidos\Pedido;
use Firebase\JWT\JWT;
use Illuminate\Console\Scheduling\Schedule;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;
use Tests\TestCase;

/**
 * Rate limiting, tamaño de cuerpo y scheduler (decisiones del equipo).
 * phpunit.xml fija límites altos para el resto de suites; aquí se bajan con config().
 */
final class LimitesTest extends TestCase
{
    private string $privada;
    private string $rutaPublica;
    private string $tokenEnvios;
    private string $tokenPagos;

    protected function setUp(): void
    {
        parent::setUp();
        $clave = openssl_pkey_new(['private_key_bits' => 2048]);
        openssl_pkey_export($clave, $privada);
        $this->privada = $privada;
        $this->rutaPublica = tempnam(sys_get_temp_dir(), 'pedidos-jwt-');
        file_put_contents($this->rutaPublica, openssl_pkey_get_details($clave)['key']);
        $this->tokenEnvios = 'envios-'.bin2hex(random_bytes(16));
        $this->tokenPagos = 'pagos-'.bin2hex(random_bytes(16));
        config([
            'pedidos.jwt_public_key_path' => $this->rutaPublica,
            'pedidos.tokens_entrantes' => ['pagos' => $this->tokenPagos, 'envios' => $this->tokenEnvios],
        ]);
    }

    protected function tearDown(): void
    {
        @unlink($this->rutaPublica);
        parent::tearDown();
    }

    private function jwt(?string $sub = null): string
    {
        return JWT::encode([
            'sub' => $sub ?? (string) Str::uuid(), 'role' => 'cliente', 'iss' => 'api-usuarios',
            'aud' => 'tienda-microservicios', 'iat' => time() - 5, 'exp' => time() + 600,
        ], $this->privada, 'RS256');
    }

    private function peticion(string $metodo, string $ruta, array $cabeceras = [], string $cuerpo = '', array $server = [])
    {
        $cabeceras += ['Accept' => 'application/json', 'Content-Type' => 'application/json'];

        return $this->call($metodo, $ruta, [], [], [], $this->transformHeadersToServerVars($cabeceras) + $server, $cuerpo);
    }

    /** GET que no toca la BD: historial ajeno (403 tras autenticar). */
    private function consulta(string $token, array $server = [])
    {
        return $this->peticion('GET', '/api/pedidos/usuario/'.Str::uuid(), ['Authorization' => 'Bearer '.$token], '', $server);
    }

    private function checkoutInvalido(string $token, string $clave)
    {
        return $this->peticion('POST', '/api/pedidos', ['Authorization' => 'Bearer '.$token, 'Idempotency-Key' => $clave], '{"x":1}');
    }

    private function envios(string $token, array $cuerpo = ['estado' => 'x'])
    {
        return $this->peticion('PATCH', '/api/pedidos/'.Str::uuid().'/estado',
            ['X-Service-Token' => $token, 'Idempotency-Key' => (string) Str::uuid()], json_encode($cuerpo));
    }

    private function assert429($respuesta): void
    {
        $respuesta->assertStatus(429)
            ->assertJsonPath('success', false)
            ->assertJsonStructure(['success', 'message', 'errors']);
        $espera = $respuesta->headers->get('Retry-After');
        $this->assertMatchesRegularExpression('/^[0-9]+$/', (string) $espera);
        $this->assertGreaterThanOrEqual(1, (int) $espera);
        $this->assertLessThanOrEqual(60, (int) $espera);
    }

    public function test_consulta_se_limita_por_usuario_autenticado(): void
    {
        config(['pedidos.limites.consulta' => 2]);
        $a = $this->jwt();
        $this->consulta($a)->assertStatus(403);
        $this->consulta($a)->assertStatus(403);
        $this->assert429($this->consulta($a));
        $this->consulta($this->jwt())->assertStatus(403); // otro sub: cubo propio
    }

    public function test_mutacion_con_jwt_tiene_su_propio_cubo(): void
    {
        config(['pedidos.limites.mutacion' => 2, 'pedidos.limites.consulta' => 100]);
        $a = $this->jwt();
        $patch = fn () => $this->peticion('PATCH', '/api/pedidos/'.Str::uuid().'/estado', ['Authorization' => 'Bearer '.$a], '{}');
        $patch()->assertStatus(401);
        $patch()->assertStatus(401);
        $this->assert429($patch());
        $this->consulta($a)->assertStatus(403); // la consulta no se ve afectada
    }

    public function test_checkout_cuenta_cada_peticion_una_sola_vez_incluida_la_misma_clave(): void
    {
        config(['pedidos.limites.checkout' => 2, 'pedidos.limites.mutacion' => 1]);
        $a = $this->jwt();
        $clave = (string) Str::uuid();
        $this->checkoutInvalido($a, $clave)->assertStatus(422);
        $this->checkoutInvalido($a, $clave)->assertStatus(422); // repetición con la misma clave: cuenta 1, no 2
        $this->assert429($this->checkoutInvalido($a, $clave));
        $this->checkoutInvalido($this->jwt(), $clave)->assertStatus(422); // otro usuario
    }

    public function test_429_de_checkout_no_deja_pedidos_a_medias_ni_llama_a_servicios(): void
    {
        if (getenv('TEST_POSTGRES') !== '1') {
            $this->markTestSkipped('Requiere PostgreSQL de pruebas y TEST_POSTGRES=1.');
        }
        $this->assertSame(0, Artisan::call('migrate'));
        Http::fake();
        config(['pedidos.limites.checkout' => 1]);
        $a = $this->jwt();
        $this->checkoutInvalido($a, (string) Str::uuid())->assertStatus(422);

        $clave = (string) Str::uuid();
        $valido = json_encode(['direccion' => ['codigo_postal' => '38000', 'calle' => 'E', 'ciudad' => 'C', 'estado' => 'G'], 'metodo_pago' => 'tarjeta_simulada']);
        $r = $this->peticion('POST', '/api/pedidos', ['Authorization' => 'Bearer '.$a, 'Idempotency-Key' => $clave], $valido);
        $this->assert429($r);
        $this->assertFalse(Pedido::where('clave_idempotencia', $clave)->exists());
        Http::assertNothingSent();
    }

    public function test_acceso_interno_se_limita_por_identidad_de_servicio(): void
    {
        config(['pedidos.limites.interna' => 2, 'pedidos.limites.mutacion' => 1, 'pedidos.limites.consulta' => 1]);
        $this->envios($this->tokenEnvios)->assertStatus(422);
        $this->envios($this->tokenEnvios)->assertStatus(422);
        $this->assert429($this->envios($this->tokenEnvios));
        // Otra identidad de servicio tiene cubo propio; Pagos 403 en PATCH.
        $this->envios($this->tokenPagos)->assertStatus(403);
    }

    public function test_sin_credencial_sigue_401_y_se_limita_por_ip(): void
    {
        config(['pedidos.limites.consulta' => 2]);
        $ruta = '/api/pedidos/usuario/'.Str::uuid();
        $ip = fn (string $ip) => $this->peticion('GET', $ruta, [], '', ['REMOTE_ADDR' => $ip]);
        $ip('10.0.0.1')->assertStatus(401);
        $ip('10.0.0.1')->assertStatus(401);
        $this->assert429($ip('10.0.0.1'));
        $ip('10.0.0.2')->assertStatus(401);
        // Las peticiones sin credencial no consumen el cubo de un usuario legítimo.
        $this->consulta($this->jwt(), ['REMOTE_ADDR' => '10.0.0.1'])->assertStatus(403);
    }

    public function test_health_y_ready_estan_exentos(): void
    {
        config(['pedidos.limites' => ['consulta' => 1, 'mutacion' => 1, 'checkout' => 1, 'interna' => 1]]);
        for ($i = 0; $i < 4; $i++) {
            $this->getJson('/health')->assertOk();
            $this->assertNotSame(429, $this->getJson('/ready')->getStatusCode());
        }
    }

    public function test_cuerpo_mayor_al_maximo_devuelve_413_por_content_length_y_por_cuerpo_real(): void
    {
        config(['pedidos.max_json_bytes' => 1000]);
        $token = $this->jwt();
        $cab = ['Authorization' => 'Bearer '.$token, 'Idempotency-Key' => (string) Str::uuid()];

        // Cuerpo real mayor.
        $this->peticion('POST', '/api/pedidos', $cab, str_repeat('a', 1001))
            ->assertStatus(413)->assertJsonPath('success', false)->assertJsonStructure(['success', 'message', 'errors']);
        // Content-Length declarado mayor con cuerpo pequeño.
        $this->peticion('POST', '/api/pedidos', $cab, '{}', ['CONTENT_LENGTH' => 5000, 'HTTP_CONTENT_LENGTH' => 5000])->assertStatus(413);
        // Justo en el límite no es 413.
        $this->assertSame(400, $this->peticion('POST', '/api/pedidos', $cab, str_repeat('a', 1000))->getStatusCode());
        // PATCH de Envíos también.
        $this->peticion('PATCH', '/api/pedidos/'.Str::uuid().'/estado',
            ['X-Service-Token' => $this->tokenEnvios, 'Idempotency-Key' => (string) Str::uuid()], str_repeat('a', 1001))
            ->assertStatus(413);
        // Sin credencial sigue 401 aunque el cuerpo sea enorme.
        $this->peticion('POST', '/api/pedidos', [], str_repeat('a', 5000))->assertStatus(401);
    }

    public function test_limite_de_cuerpo_por_defecto_es_262144(): void
    {
        $this->assertSame(262144, config('pedidos.max_json_bytes'));
        $this->assertSame(['consulta' => 100000, 'mutacion' => 100000, 'checkout' => 100000, 'interna' => 100000], config('pedidos.limites'));
    }

    public function test_scheduler_registra_pedidos_recuperar_cada_minuto_y_es_seguro_con_replicas(): void
    {
        $this->assertSame(0, Artisan::call('schedule:list'));
        $salida = Artisan::output();
        $this->assertStringContainsString('pedidos:recuperar', $salida);
        $this->assertMatchesRegularExpression('/\*\s+\*\s+\*\s+\*\s+\*\s+.*pedidos:recuperar/', $salida);

        $eventos = array_values(array_filter(
            app(Schedule::class)->events(),
            fn ($evento) => str_contains($evento->command ?? '', 'pedidos:recuperar'),
        ));
        $this->assertCount(1, $eventos);
        $this->assertSame('* * * * *', $eventos[0]->expression);
        $this->assertTrue($eventos[0]->withoutOverlapping);
        $this->assertTrue($eventos[0]->onOneServer);
    }
}
