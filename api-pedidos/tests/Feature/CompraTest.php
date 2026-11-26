<?php

namespace Tests\Feature;

use App\Pedidos\ApiError;
use App\Pedidos\Compra;
use App\Pedidos\Pedido;
use Illuminate\Database\UniqueConstraintViolationException;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Str;
use Tests\Support\ServiciosFalsos;
use Tests\TestCase;

/**
 * Saga de checkout del contrato 1.1.0 contra dobles HTTP (Http::fake) y PostgreSQL de pruebas.
 */
final class CompraTest extends TestCase
{
    private const ENTRADA = [
        'direccion' => ['codigo_postal' => '38000', 'calle' => 'Ejemplo', 'ciudad' => 'Celaya', 'estado' => 'Guanajuato'],
        'metodo_pago' => 'tarjeta_simulada',
    ];

    private function servicios(): ServiciosFalsos
    {
        if (getenv('TEST_POSTGRES') !== '1') {
            $this->markTestSkipped('Requiere PostgreSQL de pruebas y TEST_POSTGRES=1.');
        }
        $this->assertSame(0, Artisan::call('migrate'));

        return ServiciosFalsos::nuevo()->instalar();
    }

    private function ejecutar(ServiciosFalsos $s, ?string $clave = null): Pedido
    {
        return $this->app->make(Compra::class)->ejecutar($s->usuario, $clave ?? $this->clave, self::ENTRADA);
    }

    private function esperar503(callable $accion): void
    {
        try {
            $accion();
            $this->fail('Se esperaba 503');
        } catch (ApiError $error) {
            $this->assertSame(503, $error->status);
        }
    }

    private string $clave;

    protected function setUp(): void
    {
        parent::setUp();
        $this->clave = (string) Str::uuid();
    }

    public function test_reintenta_un_pago_incierto_con_el_mismo_id_y_finaliza_una_vez(): void
    {
        $s = $this->servicios();
        $s->fallos['pagos.procesar'] = [503];
        try {
            $this->esperar503(fn () => $this->ejecutar($s));
            $this->assertSame('por_pagar', Pedido::where('usuario_id', $s->usuario)->sole()->paso);
            $this->assertSame(0, $s->cuenta('carrito.liberar'));
            $this->assertSame(0, $s->cuenta('inventario.liberar'));

            $pedido = $this->ejecutar($s);
            $repetido = $this->ejecutar($s);
            $claves = array_column($s->de('pagos.procesar'), 'idempotencia');
            $this->assertSame([$pedido->id, $pedido->id], $claves);
            $this->assertSame($pedido->id, $repetido->id);
            $this->assertSame('pagado', $pedido->estado);
            $this->assertSame(1, $s->cuenta('carrito.finalizar'));
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_pedido_y_clave_se_persisten_antes_de_cualquier_efecto_externo(): void
    {
        $s = $this->servicios();
        $comprobado = [];
        foreach (['carrito.iniciar', 'inventario.reservar', 'pagos.procesar', 'envios.generar'] as $efecto) {
            $s->antes[$efecto] = function (array $cuerpo) use ($s, $efecto, &$comprobado) {
                $pedido = Pedido::where('usuario_id', $s->usuario)->sole();
                $this->assertSame($this->clave, $pedido->clave_idempotencia, $efecto);
                $this->assertSame($pedido->id, $cuerpo['pedido_id']);
                $this->assertSame('3', $pedido->carrito_version);
                $comprobado[] = $efecto;
            };
        }
        $s->antes['carrito.iniciar'] = function (array $cuerpo) use ($s, &$comprobado) {
            $pedido = Pedido::where('usuario_id', $s->usuario)->sole();
            $this->assertSame('pendiente', $pedido->estado);
            $this->assertSame('por_iniciar_carrito', $pedido->paso);
            $this->assertSame($this->clave, $pedido->clave_idempotencia);
            $this->assertNull($pedido->snapshot);
            $comprobado[] = 'carrito.iniciar';
        };
        try {
            $this->ejecutar($s);
            $this->assertSame(['carrito.iniciar', 'inventario.reservar', 'pagos.procesar', 'envios.generar'], $comprobado);
            // La lectura del carrito y la cotización no cambian estado: la primera mutación es iniciar.
            $this->assertSame('carrito.leer', $s->claves()[0]);
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_protocolo_de_carrito_snapshot_versionado_e_idempotency_key_en_mutaciones(): void
    {
        $s = $this->servicios();
        try {
            $pedido = $this->ejecutar($s);
            $this->assertSame('pagado', $pedido->estado);
            $this->assertSame('terminado', $pedido->paso);
            $this->assertEquals(['pedido_id' => $pedido->id, 'version_original' => 3], $s->de('carrito.iniciar')[0]['cuerpo']);
            $this->assertEquals([
                'pedido_id' => $pedido->id,
                'version_original' => 3,
                'items' => [['producto_id' => $s->producto, 'cantidad' => 2, 'linea_id' => $s->linea]],
            ], $s->de('carrito.finalizar')[0]['cuerpo']);
            $this->assertSame(
                ['carrito.leer', 'carrito.iniciar', 'productos.leer', 'envios.cotizar', 'inventario.reservar', 'pagos.procesar',
                    'inventario.confirmar', 'envios.generar', 'carrito.finalizar'],
                $this->orden($s),
            );
            $tokens = ['carrito' => 'tc', 'inventario' => 'ti', 'pagos' => 'tp', 'envios' => 'te'];
            foreach ($s->llamadas as $llamada) {
                [$servicio, $operacion] = explode('.', $llamada['clave']);
                if ($servicio === 'productos') {
                    $this->assertNull($llamada['token']);
                    continue;
                }
                $this->assertSame($tokens[$servicio], $llamada['token'], $llamada['clave']);
                $mutacion = !in_array($operacion, ['leer', 'consultar', 'cotizar'], true);
                if ($mutacion) {
                    $this->assertTrue(Str::isUuid((string) $llamada['idempotencia']), 'Idempotency-Key en '.$llamada['clave']);
                }
            }
            $this->assertEquals([$pedido->id], array_unique(array_column(array_column($s->de('inventario.confirmar'), 'cuerpo'), 'pedido_id')));
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    /** Orden de primera aparición de cada operación. */
    private function orden(ServiciosFalsos $s): array
    {
        return array_values(array_unique($s->claves()));
    }

    public function test_carrito_cambiado_antes_de_iniciar_da_409_sin_cobrar_ni_reservar(): void
    {
        $s = $this->servicios();
        $s->antes['carrito.iniciar'] = fn () => $s->version = 4; // alguien agregó tras la lectura
        try {
            try {
                $this->ejecutar($s);
                $this->fail('Se esperaba 409');
            } catch (ApiError $error) {
                $this->assertSame(409, $error->status);
            }
            $pedido = Pedido::where('usuario_id', $s->usuario)->sole();
            $this->assertSame('cancelado', $pedido->estado);
            $this->assertSame('carrito_desactualizado', $pedido->paso);
            foreach (['inventario.reservar', 'pagos.procesar', 'envios.generar', 'carrito.finalizar'] as $efecto) {
                $this->assertSame(0, $s->cuenta($efecto), $efecto);
            }
            // Repetir la misma clave devuelve el mismo resultado sin nuevas llamadas.
            $antes = count($s->llamadas);
            try {
                $this->ejecutar($s);
            } catch (ApiError $error) {
                $this->assertSame(409, $error->status);
            }
            $this->assertCount($antes, $s->llamadas);
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_un_checkout_activo_por_usuario_responde_409_con_otra_clave(): void
    {
        $s = $this->servicios();
        $s->fallos['pagos.procesar'] = [503, 503];
        $s->pagoConsultable = null;
        try {
            $this->esperar503(fn () => $this->ejecutar($s));
            $llamadas = count($s->llamadas);
            try {
                $this->ejecutar($s, (string) Str::uuid());
                $this->fail('Se esperaba 409');
            } catch (ApiError $error) {
                $this->assertSame(409, $error->status);
            }
            $this->assertCount($llamadas, $s->llamadas);
            $this->assertSame(1, Pedido::where('usuario_id', $s->usuario)->count());
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_la_base_impide_dos_checkouts_activos_del_mismo_usuario(): void
    {
        $this->servicios();
        $usuario = (string) Str::uuid();
        $fila = fn (string $paso) => [
            'id' => (string) Str::uuid(), 'usuario_id' => $usuario, 'clave_idempotencia' => (string) Str::uuid(),
            'huella' => str_repeat('a', 64), 'direccion' => self::ENTRADA['direccion'], 'metodo_pago' => 'tarjeta_simulada',
            'estado' => 'pendiente', 'paso' => $paso, 'carrito_id' => $usuario, 'carrito_version' => '1', 'creado_en' => now(),
        ];
        try {
            Pedido::create($fila('terminado'));
            Pedido::create($fila('sin_stock'));
            Pedido::create($fila('por_reservar'));
            try {
                Pedido::create($fila('por_pagar'));
                $this->fail('La base debía rechazar el segundo checkout activo');
            } catch (UniqueConstraintViolationException) {
                $this->addToAssertionCount(1);
            }
        } finally {
            Pedido::where('usuario_id', $usuario)->delete();
        }
    }

    public function test_stock_insuficiente_libera_el_carrito_sin_cobrar_y_reanuda(): void
    {
        $s = $this->servicios();
        $s->sinStock = true;
        $s->fallos['carrito.liberar'] = [503];
        try {
            $this->esperar503(fn () => $this->ejecutar($s));
            $pedido = Pedido::where('usuario_id', $s->usuario)->sole();
            $this->assertSame('cancelado', $pedido->estado);
            $this->assertSame('por_liberar_carrito_sin_stock', $pedido->paso);
            try {
                $this->ejecutar($s);
                $this->fail('Se esperaba 409');
            } catch (ApiError $error) {
                $this->assertSame(409, $error->status);
            }
            $this->assertSame('sin_stock', $pedido->fresh()->paso);
            $this->assertSame(2, $s->cuenta('carrito.liberar'));
            $this->assertSame(1, $s->cuenta('inventario.reservar'));
            $this->assertSame(0, $s->cuenta('pagos.procesar'));
            $claves = array_column($s->de('carrito.liberar'), 'idempotencia');
            $this->assertSame($claves[0], $claves[1]);
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_pago_rechazado_devuelve_pedido_cancelado_y_libera_reserva_y_carrito(): void
    {
        $s = $this->servicios();
        $s->pago = 'rechazado';
        try {
            $pedido = $this->ejecutar($s);
            $this->assertSame('cancelado', $pedido->estado);
            $this->assertSame('terminado', $pedido->paso);
            $this->assertSame(1, $s->cuenta('inventario.liberar'));
            $this->assertSame(1, $s->cuenta('carrito.liberar'));
            $this->assertSame(['pedido_id' => $pedido->id], $s->de('carrito.liberar')[0]['cuerpo']);
            foreach (['inventario.confirmar', 'envios.generar', 'carrito.finalizar'] as $efecto) {
                $this->assertSame(0, $s->cuenta($efecto), $efecto);
            }
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_liberacion_pendiente_tras_rechazo_se_completa_con_el_comando_sin_cliente(): void
    {
        $s = $this->servicios();
        $s->pago = 'rechazado';
        $s->fallos['carrito.liberar'] = [503];
        $s->fallos['inventario.liberar'] = [503];
        try {
            $this->esperar503(fn () => $this->ejecutar($s));
            $pedido = Pedido::where('usuario_id', $s->usuario)->sole();
            $this->assertSame('cancelado', $pedido->estado);
            $this->assertSame('por_liberar_reserva', $pedido->paso);
            $this->assertSame(1, $pedido->intentos);
            $this->assertNotNull($pedido->proximo_intento);

            $this->vencer($pedido);
            $this->assertSame(0, Artisan::call('pedidos:recuperar')); // libera inventario; el carrito falla una vez
            $pedido = $pedido->fresh();
            $this->assertSame('por_liberar_carrito_pago', $pedido->paso);
            $this->vencer($pedido);
            Artisan::call('pedidos:recuperar');
            $pedido = $pedido->fresh();
            $this->assertSame('terminado', $pedido->paso);
            $this->assertSame('cancelado', $pedido->estado);
            $this->assertSame(2, $s->cuenta('inventario.liberar'));
            $this->assertSame(2, $s->cuenta('carrito.liberar'));
            $this->assertSame(1, $s->cuenta('pagos.procesar'));
            $this->assertSame(0, $pedido->intentos);
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    private function vencer(Pedido $pedido): void
    {
        Pedido::whereKey($pedido->id)->update(['proximo_intento' => now()->subSecond()]);
    }

    public function test_pago_ambiguo_se_resuelve_consultando_pagos_sin_repetir_el_cobro(): void
    {
        $s = $this->servicios();
        $s->fallos['pagos.procesar'] = ['timeout'];
        $s->pagoConsultable = 'aprobado';
        try {
            $pedido = $this->ejecutar($s);
            $this->assertSame('pagado', $pedido->estado);
            $this->assertSame(1, $s->cuenta('pagos.procesar'));
            $this->assertSame(1, $s->cuenta('pagos.consultar'));
            $this->assertSame(0, $s->cuenta('inventario.liberar'));
            $this->assertSame(1, $s->cuenta('envios.generar'));
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_pago_ambiguo_sin_comprobante_no_cancela_ni_libera_y_reintenta_la_misma_clave(): void
    {
        $s = $this->servicios();
        $s->fallos['pagos.procesar'] = [503];
        $s->pagoConsultable = null; // 404 no prueba que no haya operación en curso
        try {
            $this->esperar503(fn () => $this->ejecutar($s));
            $pedido = Pedido::where('usuario_id', $s->usuario)->sole();
            $this->assertSame('pendiente', $pedido->estado);
            $this->assertSame('por_pagar', $pedido->paso);
            foreach (['inventario.liberar', 'carrito.liberar'] as $efecto) {
                $this->assertSame(0, $s->cuenta($efecto), $efecto);
            }
            $this->vencer($pedido);
            Artisan::call('pedidos:recuperar');
            $pedido = $pedido->fresh();
            $this->assertSame('pagado', $pedido->estado);
            $this->assertSame('terminado', $pedido->paso);
            $claves = array_column($s->de('pagos.procesar'), 'idempotencia');
            $this->assertCount(2, $claves);
            $this->assertSame($claves[0], $claves[1]);
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_finalizacion_pendiente_da_503_nunca_cancela_un_pedido_cobrado_y_el_comando_recupera(): void
    {
        $s = $this->servicios();
        $s->fallos['carrito.finalizar'] = [503];
        try {
            $this->esperar503(fn () => $this->ejecutar($s));
            $pedido = Pedido::where('usuario_id', $s->usuario)->sole();
            $this->assertSame('pagado', $pedido->estado);
            $this->assertSame('por_finalizar_carrito', $pedido->paso);
            $this->assertNotNull($pedido->ultimo_error);

            // El backoff aún no vence: el comando no toca el pedido.
            Artisan::call('pedidos:recuperar');
            $this->assertSame(1, $s->cuenta('carrito.finalizar'));

            $this->vencer($pedido);
            $this->assertSame(0, Artisan::call('pedidos:recuperar'));
            $pedido = $pedido->fresh();
            $this->assertSame('terminado', $pedido->paso);
            $this->assertSame('pagado', $pedido->estado);
            $this->assertSame(2, $s->cuenta('carrito.finalizar'));
            $this->assertSame(1, $s->cuenta('pagos.procesar'));
            $this->assertSame(1, $s->cuenta('envios.generar'));
            $claves = array_column($s->de('carrito.finalizar'), 'idempotencia');
            $this->assertSame($claves[0], $claves[1]);

            // Repetir la misma clave devuelve el mismo pedido terminado.
            $repetido = $this->ejecutar($s);
            $this->assertSame($pedido->id, $repetido->id);
            $this->assertSame(2, $s->cuenta('carrito.finalizar'));
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_comando_registrado_en_el_scheduler(): void
    {
        $this->servicios();
        Artisan::call('schedule:list');
        $this->assertStringContainsString('pedidos:recuperar', Artisan::output());
    }

    public function test_falta_de_url_o_token_de_un_servicio_falla_de_forma_controlada(): void
    {
        $s = $this->servicios();
        config(['pedidos.tokens_salientes.inventario' => null]);
        try {
            $this->esperar503(fn () => $this->ejecutar($s));
            $this->assertSame('por_reservar', Pedido::where('usuario_id', $s->usuario)->sole()->paso);
            $this->assertSame(0, $s->cuenta('inventario.reservar'));

            config(['pedidos.tokens_salientes.inventario' => 'ti', 'pedidos.urls.pagos' => '']);
            $this->esperar503(fn () => $this->ejecutar($s));
            $this->assertSame('por_pagar', Pedido::where('usuario_id', $s->usuario)->sole()->paso);
            $this->assertSame(0, $s->cuenta('pagos.procesar'));
        } finally {
            Pedido::where('usuario_id', $s->usuario)->delete();
        }
    }

    public function test_sin_token_de_carrito_no_se_persiste_nada(): void
    {
        $s = $this->servicios();
        config(['pedidos.tokens_salientes.carrito' => null]);
        $this->esperar503(fn () => $this->ejecutar($s));
        $this->assertSame(0, Pedido::where('usuario_id', $s->usuario)->count());
    }
}
