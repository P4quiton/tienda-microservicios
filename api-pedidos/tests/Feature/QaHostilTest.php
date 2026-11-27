<?php

namespace Tests\Feature;

use App\Pedidos\Pedido;
use Firebase\JWT\JWT;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Str;
use Tests\Support\ServiciosFalsos;
use Tests\TestCase;

/**
 * Pruebas "QA hostil": entradas malformadas, JWT manipulados, tokens de servicio,
 * titularidad, inyección SQL, concurrencia/idempotencia, migraciones y caída de BD.
 * Las que tocan PostgreSQL exigen TEST_POSTGRES=1 (base exclusiva de pruebas).
 */
final class QaHostilTest extends TestCase
{
    private string $privada;
    private string $publica;
    private string $rutaPublica;

    protected function setUp(): void
    {
        parent::setUp();
        $clave = openssl_pkey_new(['private_key_bits' => 2048]);
        openssl_pkey_export($clave, $privada);
        $this->privada = $privada;
        $this->publica = openssl_pkey_get_details($clave)['key'];
        $this->rutaPublica = tempnam(sys_get_temp_dir(), 'pedidos-jwt-');
        file_put_contents($this->rutaPublica, $this->publica);
        config(['pedidos.jwt_public_key_path' => $this->rutaPublica]);
    }

    protected function tearDown(): void
    {
        @unlink($this->rutaPublica);
        parent::tearDown();
    }

    // ---------- utilidades ----------

    private function postgres(): void
    {
        if (getenv('TEST_POSTGRES') !== '1') {
            $this->markTestSkipped('Requiere PostgreSQL de pruebas y TEST_POSTGRES=1.');
        }
        $this->assertSame(0, Artisan::call('migrate'));
    }

    private function claims(array $cambios = [], ?string $sub = null): array
    {
        return array_replace([
            'sub' => $sub ?? (string) Str::uuid(),
            'role' => 'cliente',
            'iss' => 'api-usuarios',
            'aud' => 'tienda-microservicios',
            'iat' => time() - 5,
            'exp' => time() + 600,
        ], $cambios);
    }

    private function jwt(array $claims, ?string $clave = null, string $alg = 'RS256'): string
    {
        return JWT::encode($claims, $clave ?? $this->privada, $alg);
    }

    private function b64(string $datos): string
    {
        return rtrim(strtr(base64_encode($datos), '+/', '-_'), '=');
    }

    private function cuerpoValido(): array
    {
        return [
            'direccion' => ['codigo_postal' => '38000', 'calle' => 'Ejemplo', 'ciudad' => 'Celaya', 'estado' => 'Guanajuato'],
            'metodo_pago' => 'tarjeta_simulada',
        ];
    }

    private function crear(array|string $cuerpo, ?string $clave = null, ?string $token = null)
    {
        $token ??= $this->jwt($this->claims());
        $cabeceras = ['Authorization' => 'Bearer '.$token, 'Content-Type' => 'application/json', 'Accept' => 'application/json'];
        if ($clave !== '') {
            $cabeceras['Idempotency-Key'] = $clave ?? (string) Str::uuid();
        }

        return $this->call('POST', '/api/pedidos', [], [], [], $this->transformHeadersToServerVars($cabeceras), is_string($cuerpo) ? $cuerpo : json_encode($cuerpo));
    }

    // ---------- entrada ----------

    public function test_json_malformado_devuelve_400(): void
    {
        foreach (['{', '', '{"direccion":', "{'a':1}", "\xB1\x31"] as $cuerpo) {
            $this->crear($cuerpo)->assertStatus(400)->assertJsonPath('success', false);
        }
        $this->crear('{"a":'.str_repeat('[', 5000).str_repeat(']', 5000).'}')->assertStatus(400);
    }

    public function test_campos_extra_y_tipos_erroneos_devuelven_422(): void
    {
        $base = $this->cuerpoValido();
        $casos = [
            'extra raíz' => $base + ['usuario_id' => (string) Str::uuid()],
            'precio del cliente' => $base + ['total' => '1.00'],
            'extra dirección' => array_replace($base, ['direccion' => $base['direccion'] + ['pais' => 'MX']]),
            'cp numérico' => array_replace($base, ['direccion' => ['codigo_postal' => 38000] + $base['direccion']]),
            'cp con 6 dígitos' => array_replace($base, ['direccion' => ['codigo_postal' => '380000'] + $base['direccion']]),
            'cp con salto de línea' => array_replace($base, ['direccion' => ['codigo_postal' => "38000\n"] + $base['direccion']]),
            'calle null' => array_replace($base, ['direccion' => ['calle' => null] + $base['direccion']]),
            'calle arreglo' => array_replace($base, ['direccion' => ['calle' => ['x']] + $base['direccion']]),
            'dirección lista' => array_replace($base, ['direccion' => ['a', 'b']]),
            'método inválido' => array_replace($base, ['metodo_pago' => 'bitcoin']),
            'método entero' => array_replace($base, ['metodo_pago' => 0]),
            'método arreglo' => array_replace($base, ['metodo_pago' => ['tarjeta_simulada']]),
            'raíz lista' => [1, 2],
            'raíz vacía' => [],
        ];
        foreach ($casos as $nombre => $cuerpo) {
            $this->assertSame(422, $this->crear($cuerpo)->getStatusCode(), $nombre);
        }
        $this->crear('"texto"')->assertStatus(422);
        $this->crear('null')->assertStatus(422);
    }

    public function test_idempotency_key_debe_ser_uuid_v4(): void
    {
        foreach ([
            '', 'abc', '11111111-1111-1111-8111-111111111111', // v1
            '11111111-1111-4111-c111-111111111111',            // variante inválida
            (string) Str::uuid().' ', "x".(string) Str::uuid(), str_repeat('a', 5000),
        ] as $clave) {
            $this->assertSame(422, $this->crear($this->cuerpoValido(), $clave === '' ? '' : $clave)->getStatusCode(), $clave);
        }
    }

    public function test_cadenas_con_controles_o_demasiado_largas_se_rechazan_antes_de_persistir(): void
    {
        $base = $this->cuerpoValido();
        foreach ([
            "con\0nulo", "con\x07campana", "salto\ndeLinea", str_repeat('a', 201),
        ] as $valor) {
            $cuerpo = array_replace($base, ['direccion' => ['calle' => $valor] + $base['direccion']]);
            $this->assertSame(422, $this->crear($cuerpo)->getStatusCode(), json_encode($valor));
        }
    }

    public function test_cuerpo_enorme_se_rechaza(): void
    {
        $base = $this->cuerpoValido();
        $base['direccion']['calle'] = str_repeat('a', 2_000_000);
        // Cambio documentado: antes 422 (tope 16 KiB); ahora 413 (MAX_JSON_BYTES, 262144 por defecto).
        $this->assertSame(413, $this->crear($base)->getStatusCode());
        $this->crear('['.str_repeat('1,', 500_000).'1]')->assertStatus(413);
    }

    // ---------- JWT ----------

    private function rutaProtegida(?string $token)
    {
        $cabeceras = $token === null ? [] : ['Authorization' => 'Bearer '.$token];

        return $this->flushHeaders()->withHeaders($cabeceras)->getJson('/api/pedidos/usuario/'.Str::uuid());
    }

    public function test_jwt_manipulados_devuelven_401(): void
    {
        $sub = (string) Str::uuid();
        $valido = $this->jwt($this->claims([], $sub));
        [$h, $p, $s] = explode('.', $valido);
        $otra = openssl_pkey_new(['private_key_bits' => 2048]);
        openssl_pkey_export($otra, $privadaAjena);
        $payloadAdmin = $this->b64(json_encode($this->claims(['role' => 'admin'], $sub)));

        $casos = [
            'sin token' => null,
            'vacío' => '',
            'basura' => 'abc',
            'dos segmentos' => $h.'.'.$p,
            'firma truncada' => $h.'.'.$p.'.'.substr($s, 0, 20),
            'sin firma' => $h.'.'.$p.'.',
            'payload alterado' => $h.'.'.$payloadAdmin.'.'.$s,
            'alg none' => $this->b64('{"alg":"none","typ":"JWT"}').'.'.$p.'.',
            'alg None' => $this->b64('{"alg":"None","typ":"JWT"}').'.'.$p.'.',
            'confusión HS256 con la pública' => $this->jwt($this->claims([], $sub), $this->publica, 'HS256'),
            'firmado por otra clave' => $this->jwt($this->claims([], $sub), $privadaAjena),
            'expirado' => $this->jwt($this->claims(['exp' => time() - 10, 'iat' => time() - 700], $sub)),
            'exp igual a iat' => $this->jwt($this->claims(['exp' => time() - 5], $sub)),
            'iat futuro' => $this->jwt($this->claims(['iat' => time() + 300, 'exp' => time() + 900], $sub)),
            'vigencia de 2 h' => $this->jwt($this->claims(['exp' => time() + 7200], $sub)),
            'nbf futuro' => $this->jwt($this->claims(['nbf' => time() + 300], $sub)),
            'iss ajeno' => $this->jwt($this->claims(['iss' => 'otro'], $sub)),
            'aud ajena' => $this->jwt($this->claims(['aud' => 'otra'], $sub)),
            'sin aud' => $this->jwt(array_diff_key($this->claims([], $sub), ['aud' => 1])),
            'sin sub' => $this->jwt(array_diff_key($this->claims(), ['sub' => 1])),
            'sub no UUID' => $this->jwt($this->claims(['sub' => '1 OR 1=1'])),
            'sub UUID v1' => $this->jwt($this->claims(['sub' => '11111111-1111-1111-8111-111111111111'])),
            'rol desconocido' => $this->jwt($this->claims(['role' => 'superadmin'], $sub)),
            'sin rol' => $this->jwt(array_diff_key($this->claims([], $sub), ['role' => 1])),
            'sin exp' => $this->jwt(array_diff_key($this->claims([], $sub), ['exp' => 1])),
            'iat como cadena' => $this->jwt($this->claims(['iat' => (string) time()], $sub)),
        ];
        foreach ($casos as $nombre => $token) {
            $this->rutaProtegida($token)->assertStatus(401)->assertJsonPath('success', false);
        }
    }

    public function test_sin_clave_publica_legible_devuelve_401_y_no_500(): void
    {
        config(['pedidos.jwt_public_key_path' => '/no/existe.pem']);
        $this->rutaProtegida($this->jwt($this->claims()))->assertStatus(401);
        file_put_contents($this->rutaPublica, 'no es un PEM');
        config(['pedidos.jwt_public_key_path' => $this->rutaPublica]);
        $this->rutaProtegida($this->jwt($this->claims()))->assertStatus(401);
    }

    public function test_token_de_cliente_no_sirve_como_identidad_interna_ni_viceversa(): void
    {
        $id = (string) Str::uuid();
        $jwt = $this->jwt($this->claims(['role' => 'admin']));
        // PATCH sigue cerrado: ni cliente ni admin ni JWT en X-Service-Token.
        $this->withToken($jwt)->patchJson("/api/pedidos/$id/estado", ['estado' => 'pagado'])->assertStatus(401);
        $this->withHeader('X-Service-Token', $jwt)->patchJson("/api/pedidos/$id/estado", ['estado' => 'pagado'])->assertStatus(401);
        // Un token de servicio no abre rutas de usuario.
        $this->flushHeaders();
        config(['pedidos.tokens_entrantes.pagos' => 'a-'.bin2hex(random_bytes(16))]);
        $this->withHeader('X-Service-Token', config('pedidos.tokens_entrantes.pagos'))
            ->getJson('/api/pedidos/usuario/'.Str::uuid())->assertStatus(401);
        $this->withHeader('X-Service-Token', config('pedidos.tokens_entrantes.pagos'))
            ->postJson('/api/pedidos', $this->cuerpoValido(), ['Idempotency-Key' => (string) Str::uuid()])->assertStatus(401);
    }

    // ---------- X-Service-Token ----------

    public function test_x_service_token_ausente_vacio_equivocado_o_de_otro_par(): void
    {
        $id = (string) Str::uuid();
        config([
            'pedidos.tokens_entrantes' => ['pagos' => 'pagos-'.bin2hex(random_bytes(16)), 'envios' => 'envios-'.bin2hex(random_bytes(16))],
            'pedidos.tokens_salientes.carrito' => 'carrito-'.bin2hex(random_bytes(16)),
        ]);
        $pedido = fn (?string $token) => $this->flushHeaders()->withHeaders($token === null ? [] : ['X-Service-Token' => $token])->getJson("/api/pedidos/$id");

        $pedido(null)->assertStatus(401);                              // sin ningún credencial
        $pedido('')->assertStatus(401);
        $pedido('equivocado')->assertStatus(401);
        $pedido(config('pedidos.tokens_salientes.carrito'))->assertStatus(401); // secreto de otro par
        $pedido(strtoupper(config('pedidos.tokens_entrantes.pagos')))->assertStatus(401);
        $pedido(config('pedidos.tokens_entrantes.pagos').' ')->assertStatus(401);
    }

    public function test_servicios_sin_secreto_configurado_nunca_autentican(): void
    {
        config(['pedidos.tokens_entrantes' => ['pagos' => null, 'envios' => '']]);
        foreach (['', ' ', '0', 'null'] as $token) {
            $this->withHeader('X-Service-Token', $token)->getJson('/api/pedidos/'.Str::uuid())->assertStatus(401);
        }
    }

    public function test_patch_estado_solo_acepta_el_token_de_envios_y_otros_pares_son_403(): void
    {
        config(['pedidos.tokens_entrantes' => ['pagos' => 'p-'.bin2hex(random_bytes(16)), 'envios' => 'e-'.bin2hex(random_bytes(16))]]);
        $id = (string) Str::uuid();
        $cabeceras = ['Idempotency-Key' => (string) Str::uuid()];
        foreach ([['estado' => 'enviado'], ['estado' => 'pagado'], [], ['x' => 1]] as $cuerpo) {
            $this->withHeaders($cabeceras + ['X-Service-Token' => config('pedidos.tokens_entrantes.pagos')])
                ->patchJson("/api/pedidos/$id/estado", $cuerpo)->assertStatus(403);
            // Con el token de Envíos se llega a la validación: 422 si el cuerpo es inválido, nunca 401/403.
            $this->assertNotContains(
                $this->withHeaders($cabeceras + ['X-Service-Token' => config('pedidos.tokens_entrantes.envios')])
                    ->patchJson("/api/pedidos/$id/estado", $cuerpo)->getStatusCode(),
                [401, 403],
            );
        }
    }

    // ---------- titularidad ----------

    public function test_usuario_a_no_ve_historial_ni_pedido_de_b(): void
    {
        $this->postgres();
        $a = (string) Str::uuid();
        $b = (string) Str::uuid();
        $pedido = Pedido::create([
            'id' => (string) Str::uuid(), 'usuario_id' => $b, 'clave_idempotencia' => (string) Str::uuid(), 'huella' => str_repeat('0', 64),
            'items' => [], 'direccion' => [], 'metodo_pago' => 'tarjeta_simulada', 'costo_envio' => '1.00', 'total' => '2.00',
            'estado' => 'pendiente', 'paso' => 'terminado', 'carrito_id' => $b, 'carrito_version' => '1', 'creado_en' => now(),
        ]);
        try {
            $tokenA = $this->jwt($this->claims([], $a));
            $this->withToken($tokenA)->getJson("/api/pedidos/usuario/$b")->assertStatus(403);
            $this->withToken($tokenA)->getJson('/api/pedidos/'.$pedido->id)->assertStatus(403);
            // Mayúsculas en el UUID no deben saltarse la comparación de titular.
            $this->withToken($tokenA)->getJson('/api/pedidos/usuario/'.strtoupper($b))->assertStatus(403);
            // El titular y el admin sí.
            $this->withToken($this->jwt($this->claims([], $b)))->getJson('/api/pedidos/'.$pedido->id)->assertOk();
            $this->withToken($this->jwt($this->claims(['role' => 'admin'], $a)))->getJson("/api/pedidos/usuario/$b")->assertOk()->assertJsonCount(1, 'data');
            // Un sub en mayúsculas sigue siendo el mismo titular.
            $this->withToken($this->jwt($this->claims([], strtoupper($b))))->getJson("/api/pedidos/usuario/$b")->assertOk();
        } finally {
            $pedido->delete();
        }
    }

    // ---------- inyección SQL ----------

    public function test_inyeccion_sql_en_rutas_y_cuerpo(): void
    {
        $this->postgres();
        $token = $this->jwt($this->claims(['role' => 'admin']));
        foreach (["1' OR '1'='1", "x'; DROP TABLE pedidos;--", '1 UNION SELECT 1', '%27%20OR%201=1--'] as $carga) {
            $this->withToken($token)->getJson('/api/pedidos/usuario/'.rawurlencode($carga))->assertStatus(422);
            $this->withToken($token)->getJson('/api/pedidos/'.rawurlencode($carga))->assertStatus(422);
        }
        // Cadenas hostiles en la dirección se guardan literales, sin ejecutarse.
        $usuario = (string) Str::uuid();
        $this->flujoCompletoSimulado($usuario);
        $carga = "'); DROP TABLE pedidos;--";
        $cuerpo = $this->cuerpoValido();
        $cuerpo['direccion']['calle'] = $carga;
        try {
            $respuesta = $this->crear($cuerpo, null, $this->jwt($this->claims([], $usuario)));
            $respuesta->assertStatus(201)->assertJsonPath('data.direccion.calle', $carga);
            $this->assertSame(1, Pedido::where('usuario_id', $usuario)->count());
        } finally {
            Pedido::where('usuario_id', $usuario)->delete();
        }
    }

    /** Sustituye carrito y dependencias HTTP por dobles para completar una compra. */
    private function flujoCompletoSimulado(string $usuario): ServiciosFalsos
    {
        return ServiciosFalsos::nuevo($usuario)->instalar();
    }

    // ---------- idempotencia y concurrencia ----------

    public function test_misma_clave_repetida_no_duplica_efectos_y_otro_payload_da_409(): void
    {
        $this->postgres();
        $usuario = (string) Str::uuid();
        $servicios = $this->flujoCompletoSimulado($usuario);
        $token = $this->jwt($this->claims([], $usuario));
        $clave = (string) Str::uuid();
        try {
            $primera = $this->crear($this->cuerpoValido(), $clave, $token)->assertStatus(201);
            $primera->assertJsonPath('data.estado', 'pagado')
                ->assertJsonPath('data.guia', 'GUIA-FICTICIA')
                ->assertJsonPath('data.pago_id', $servicios->pagoId)
                ->assertJsonPath('data.metodo_pago', 'tarjeta_simulada');
            $segunda = $this->crear($this->cuerpoValido(), strtoupper($clave), $token)->assertStatus(201);
            $this->assertSame($primera->json('data.id'), $segunda->json('data.id'));
            $segunda->assertExactJson($primera->json());
            $id = $primera->json('data.id');
            $this->withToken($token)->getJson("/api/pedidos/$id")
                ->assertOk()->assertExactJson($primera->json());
            $this->withToken($token)->getJson("/api/pedidos/usuario/$usuario")
                ->assertOk()->assertExactJson(array_replace($primera->json(), ['data' => [$primera->json('data')]]));
            $otroToken = $this->jwt($this->claims());
            $this->withToken($otroToken)->getJson("/api/pedidos/$id")->assertStatus(403);
            $this->withToken($otroToken)->getJson("/api/pedidos/usuario/$usuario")->assertStatus(403);
            $this->assertSame(1, Pedido::where('usuario_id', $usuario)->count());
            $this->assertSame(1, $servicios->cuenta('pagos.procesar'));
            $this->assertSame(1, $servicios->cuenta('envios.generar'));
            $this->assertSame(1, $servicios->cuenta('carrito.finalizar'));
            $otro = $this->cuerpoValido();
            $otro['direccion']['calle'] = 'Otra';
            $this->crear($otro, $clave, $token)->assertStatus(409);
            $this->assertSame(1, Pedido::where('usuario_id', $usuario)->count());
        } finally {
            Pedido::where('usuario_id', $usuario)->delete();
        }
    }

    public function test_compras_paralelas_con_la_misma_clave_producen_un_solo_pedido_y_un_solo_cobro(): void
    {
        $this->postgres();
        $usuario = (string) Str::uuid();
        $clave = (string) Str::uuid();
        $archivo = tempnam(sys_get_temp_dir(), 'pedidos-calls-');
        $procesos = [];
        for ($i = 0; $i < 6; $i++) {
            $procesos[$i] = proc_open(
                [PHP_BINARY, base_path('tests/Support/CompraWorker.php'), $usuario, $clave, $archivo],
                [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
                $tuberias[$i],
            );
        }
        $resultados = [];
        foreach ($procesos as $i => $proceso) {
            $salida = stream_get_contents($tuberias[$i][1]);
            $error = stream_get_contents($tuberias[$i][2]);
            proc_close($proceso);
            $resultados[] = json_decode(trim($salida), true) ?? ['status' => 'fallo', 'salida' => $salida.$error];
        }
        $llamadas = array_filter(explode("\n", (string) file_get_contents($archivo)));
        @unlink($archivo);
        try {
            foreach ($resultados as $resultado) {
                $this->assertContains($resultado['status'], [201, 409], json_encode($resultado));
            }
            $this->assertNotEmpty(array_filter($resultados, fn ($r) => $r['status'] === 201));
            $this->assertSame(1, Pedido::where('usuario_id', $usuario)->count());
            $this->assertSame(1, count(array_keys($llamadas, 'pagos.procesar', true)), 'cobros');
            $this->assertSame(1, count(array_keys($llamadas, 'inventario.reservar', true)), 'reservas');
            $this->assertSame(1, count(array_keys($llamadas, 'envios.generar', true)), 'guías');
            $ids = array_unique(array_column(array_filter($resultados, fn ($r) => $r['status'] === 201), 'pedido'));
            $this->assertCount(1, $ids);
        } finally {
            Pedido::where('usuario_id', $usuario)->delete();
        }
    }

    public function test_claves_distintas_en_paralelo_para_el_mismo_usuario_no_duplican_compra(): void
    {
        $this->postgres();
        $usuario = (string) Str::uuid();
        $archivo = tempnam(sys_get_temp_dir(), 'pedidos-calls-');
        $procesos = [];
        for ($i = 0; $i < 4; $i++) {
            $procesos[$i] = proc_open(
                [PHP_BINARY, base_path('tests/Support/CompraWorker.php'), $usuario, (string) Str::uuid(), $archivo],
                [1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
                $tuberias[$i],
            );
        }
        $estados = [];
        foreach ($procesos as $i => $proceso) {
            $estados[] = json_decode(trim(stream_get_contents($tuberias[$i][1])), true)['status'] ?? 'fallo';
            stream_get_contents($tuberias[$i][2]);
            proc_close($proceso);
        }
        $llamadas = array_filter(explode("\n", (string) file_get_contents($archivo)));
        @unlink($archivo);
        try {
            $this->assertSame(1, count(array_keys($llamadas, 'pagos.procesar', true)), 'cobros '.json_encode($estados));
            $this->assertSame(1, Pedido::where('usuario_id', $usuario)->count(), json_encode($estados));
        } finally {
            Pedido::where('usuario_id', $usuario)->delete();
        }
    }


    // ---------- checkout por HTTP (contrato 1.1.0) ----------

    public function test_checkout_por_http_funciona_sin_habilitaciones_especiales_y_devuelve_201(): void
    {
        $this->postgres();
        $usuario = (string) Str::uuid();
        $servicios = $this->flujoCompletoSimulado($usuario);
        try {
            $this->crear($this->cuerpoValido(), null, $this->jwt($this->claims([], $usuario)))
                ->assertStatus(201)->assertJsonPath('data.estado', 'pagado')->assertJsonPath('data.total', '9.00');
            $this->assertSame(1, $servicios->cuenta('carrito.finalizar'));
        } finally {
            Pedido::where('usuario_id', $usuario)->delete();
        }
    }

    public function test_pago_rechazado_es_201_cancelado_y_resultado_incierto_es_503_recuperable_con_la_misma_clave(): void
    {
        $this->postgres();
        $usuario = (string) Str::uuid();
        $servicios = $this->flujoCompletoSimulado($usuario);
        $servicios->pago = 'rechazado';
        $token = $this->jwt($this->claims([], $usuario));
        try {
            $this->crear($this->cuerpoValido(), null, $token)
                ->assertStatus(201)->assertJsonPath('data.estado', 'cancelado')
                ->assertJsonStructure(['data' => ['guia']])
                ->assertJsonPath('data.pago_id', $servicios->pagoId)
                ->assertJsonPath('data.guia', null)
                ->assertJsonPath('data.metodo_pago', 'tarjeta_simulada');
            $this->assertSame(1, $servicios->cuenta('inventario.liberar'));
            $this->assertSame(1, $servicios->cuenta('carrito.liberar'));

            // Otro usuario: el cobro queda incierto -> 503 y la misma clave recupera el mismo pedido.
            $otro = (string) Str::uuid();
            $s2 = $this->flujoCompletoSimulado($otro);
            $s2->fallos['pagos.procesar'] = [503];
            $token2 = $this->jwt($this->claims([], $otro));
            $clave = (string) Str::uuid();
            $this->crear($this->cuerpoValido(), $clave, $token2)->assertStatus(503);
            $id = Pedido::where('usuario_id', $otro)->sole()->id;
            $this->crear($this->cuerpoValido(), $clave, $token2)->assertStatus(201)->assertJsonPath('data.id', $id);
            $this->assertSame(2, $s2->cuenta('pagos.procesar'));
        } finally {
            Pedido::whereIn('usuario_id', [$usuario, $otro ?? $usuario])->delete();
        }
    }

    public function test_conflictos_antes_del_pago_exponen_guia_y_pago_id_nulos(): void
    {
        $this->postgres();
        foreach (['sin_stock', 'carrito_desactualizado'] as $paso) {
            $servicios = ServiciosFalsos::nuevo()->instalar();
            $usuario = $servicios->usuario;
            $servicios->sinStock = $paso === 'sin_stock';
            if ($paso === 'carrito_desactualizado') {
                $servicios->antes['carrito.iniciar'] = fn () => $servicios->version++;
            }
            $token = $this->jwt($this->claims([], $usuario));
            $cuerpo = array_replace($this->cuerpoValido(), ['metodo_pago' => 'transferencia_simulada']);
            try {
                $this->crear($cuerpo, null, $token)->assertStatus(409);
                $pedido = Pedido::where('usuario_id', $usuario)->sole();
                $this->assertSame($paso, $pedido->paso);
                $detalle = $this->withToken($token)->getJson("/api/pedidos/{$pedido->id}")
                    ->assertOk()
                    ->assertJsonStructure(['data' => ['pago_id', 'guia']])
                    ->assertJsonPath('data.estado', 'cancelado')
                    ->assertJsonPath('data.pago_id', null)
                    ->assertJsonPath('data.guia', null)
                    ->assertJsonPath('data.metodo_pago', 'transferencia_simulada');
                $this->withToken($token)->getJson("/api/pedidos/usuario/$usuario")
                    ->assertOk()->assertExactJson(array_replace($detalle->json(), ['data' => [$detalle->json('data')]]));
            } finally {
                Pedido::where('usuario_id', $usuario)->delete();
            }
        }
    }

    public function test_pedido_pagado_antes_de_generar_guia_expone_el_pago_y_guia_nula(): void
    {
        $this->postgres();
        $servicios = ServiciosFalsos::nuevo()->instalar();
        $usuario = $servicios->usuario;
        $token = $this->jwt($this->claims([], $usuario));
        $servicios->fallos['envios.generar'] = [503];
        try {
            $this->crear($this->cuerpoValido(), null, $token)->assertStatus(503);
            $pedido = Pedido::where('usuario_id', $usuario)->sole();
            $this->assertSame('por_generar_guia', $pedido->paso);
            $this->withToken($token)->getJson("/api/pedidos/{$pedido->id}")
                ->assertOk()
                ->assertJsonStructure(['data' => ['guia']])
                ->assertJsonPath('data.estado', 'pagado')
                ->assertJsonPath('data.pago_id', $servicios->pagoId)
                ->assertJsonPath('data.guia', null)
                ->assertJsonPath('data.metodo_pago', 'tarjeta_simulada');
        } finally {
            Pedido::where('usuario_id', $usuario)->delete();
        }
    }

    // ---------- migraciones ----------

    public function test_migracion_de_pago_id_agrega_uuid_nulo_y_revierte_solo_la_columna(): void
    {
        $this->postgres();
        $columna = fn () => DB::table('information_schema.columns')
            ->whereRaw('table_schema = current_schema()')
            ->where('table_name', 'pedidos')
            ->where('column_name', 'pago_id')
            ->first(['data_type', 'is_nullable']);

        $definicion = $columna();
        $this->assertNotNull($definicion);
        $this->assertSame('uuid', $definicion->data_type);
        $this->assertSame('YES', $definicion->is_nullable);
        try {
            $this->assertSame(0, Artisan::call('migrate:rollback', ['--step' => 1]));
            $this->assertNull($columna());
            $this->assertTrue(Schema::hasColumn('pedidos', 'guia'));
            $this->assertTrue(Schema::hasColumn('pedidos', 'snapshot'));
        } finally {
            $this->assertSame(0, Artisan::call('migrate'));
        }
        $this->assertEquals($definicion, $columna());
    }

    public function test_migraciones_son_repetibles_y_reversibles(): void
    {
        $this->postgres();
        $this->assertSame(0, Artisan::call('migrate'));
        $this->assertSame(0, Artisan::call('migrate'));
        $this->assertTrue(\Illuminate\Support\Facades\Schema::hasTable('pedidos'));
        $this->assertSame(0, Artisan::call('migrate:reset'));
        $this->assertFalse(\Illuminate\Support\Facades\Schema::hasTable('pedidos'));
        $this->getJson('/ready')->assertStatus(503);
        $this->assertSame(0, Artisan::call('migrate'));
        $this->getJson('/ready')->assertOk();
    }

    // ---------- BD caída ----------

    private function baseCaida(): void
    {
        config(['database.connections.pgsql.host' => '127.0.0.1', 'database.connections.pgsql.port' => 1]);
        DB::purge();
    }

    public function test_bd_caida_health_vive_y_ready_falla(): void
    {
        $this->baseCaida();
        $this->getJson('/health')->assertOk()->assertExactJson(['status' => 'ok', 'service' => 'api-pedidos']);
        $this->getJson('/ready')->assertStatus(503)->assertExactJson(['status' => 'unavailable', 'service' => 'api-pedidos']);
    }

    public function test_bd_caida_las_rutas_de_negocio_responden_503_sin_filtrar_detalles(): void
    {
        $this->baseCaida();
        $token = $this->jwt($this->claims(['role' => 'admin']));
        config(['pedidos.tokens_entrantes.pagos' => 'p-'.bin2hex(random_bytes(8))]);
        $respuestas = [
            $this->crear($this->cuerpoValido(), null, $token),
            $this->withToken($token)->getJson('/api/pedidos/usuario/'.Str::uuid()),
            $this->withToken($token)->getJson('/api/pedidos/'.Str::uuid()),
            $this->withHeader('X-Service-Token', config('pedidos.tokens_entrantes.pagos'))->getJson('/api/pedidos/'.Str::uuid()),
        ];
        foreach ($respuestas as $respuesta) {
            $respuesta->assertStatus(503)->assertJsonPath('success', false);
            $this->assertStringNotContainsString('SQLSTATE', $respuesta->getContent());
            $this->assertStringNotContainsString('127.0.0.1', $respuesta->getContent());
        }
    }

    public function test_errores_internos_no_filtran_trazas(): void
    {
        $this->postgres();
        config(['app.debug' => true]);
        $token = $this->jwt($this->claims(['role' => 'admin']));
        $respuesta = $this->withToken($token)->getJson('/api/no-existe');
        $respuesta->assertStatus(404);
        $this->assertStringNotContainsString('vendor', $respuesta->getContent());
        $this->assertStringNotContainsString('trace', strtolower($respuesta->getContent()));
        $this->call('DELETE', '/api/pedidos/'.Str::uuid())->assertStatus(405)->assertJsonPath('success', false);
    }
}
