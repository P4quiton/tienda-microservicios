<?php

namespace Tests\Feature;

use App\Pedidos\ApiError;
use App\Pedidos\CarritoCheckout;
use App\Pedidos\Compra;
use App\Pedidos\Pedido;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;
use Tests\TestCase;

final class CompraTest extends TestCase
{
    public function test_reintenta_un_pago_incierto_con_el_mismo_id_y_finaliza_una_vez(): void
    {
        if (getenv('TEST_POSTGRES') !== '1') {
            $this->markTestSkipped('Requiere PostgreSQL de pruebas y TEST_POSTGRES=1.');
        }

        $this->assertSame(0, Artisan::call('migrate'));
        $this->getJson('/ready')->assertOk()->assertJsonPath('status', 'ok');
        $usuario = (string) Str::uuid();
        $producto = (string) Str::uuid();
        $clave = (string) Str::uuid();
        $carrito = new class($producto) implements CarritoCheckout {
            public int $confirmaciones = 0;
            public int $cancelaciones = 0;

            public function __construct(private string $producto) {}

            public function leer(string $usuarioId): array
            {
                return [
                    'carrito_id' => $usuarioId,
                    'version' => '3',
                    'items' => [['producto_id' => $this->producto, 'cantidad' => 2]],
                ];
            }

            public function preparar(Pedido $pedido): void {}

            public function cancelar(Pedido $pedido): void { $this->cancelaciones++; }

            public function confirmar(Pedido $pedido): void
            {
                $this->confirmaciones++;
            }
        };
        $this->app->instance(CarritoCheckout::class, $carrito);

        config(['pedidos.tokens_salientes' => ['inventario' => 'test', 'pagos' => 'test', 'envios' => 'test']]);
        $clavesPago = [];
        Http::fake(function (Request $request) use (&$clavesPago) {
            $datos = $request->data();
            $id = ['pedido_id' => $datos['pedido_id'] ?? null];
            $ruta = basename(parse_url($request->url(), PHP_URL_PATH));
            if ($ruta === 'procesar') {
                $clavesPago[] = $request->header('Idempotency-Key')[0];
                if (count($clavesPago) === 1) {
                    return Http::response([], 503);
                }
            }
            $respuesta = match ($ruta) {
                'cotizar' => ['costo_envio' => '4.00'],
                'reservar' => $id + ['estado' => 'reservada'],
                'procesar' => $id + ['estado' => 'aprobado', 'monto' => '9.00'],
                'confirmar' => $id + ['estado' => 'confirmada'],
                'generar' => $id + ['guia' => 'GUIA-FICTICIA'],
                default => ['precio' => '2.50'],
            };

            return Http::response(['success' => true, 'data' => $respuesta]);
        });

        $entrada = [
            'direccion' => ['codigo_postal' => '38000', 'calle' => 'Ejemplo', 'ciudad' => 'Celaya', 'estado' => 'Guanajuato'],
            'metodo_pago' => 'tarjeta_simulada',
        ];
        $compra = $this->app->make(Compra::class);

        try {
            try {
                $compra->ejecutar($usuario, $clave, $entrada);
                $this->fail('Se esperaba indicar resultado incierto');
            } catch (ApiError $error) {
                $this->assertSame(503, $error->status);
            }
            $this->assertSame('por_pagar', Pedido::where('usuario_id', $usuario)->sole()->paso);
            $this->assertSame(0, $carrito->cancelaciones);

            $pedido = $compra->ejecutar($usuario, $clave, $entrada);
            $repetido = $compra->ejecutar($usuario, $clave, $entrada);
            $this->assertSame([$pedido->id, $pedido->id], $clavesPago);
            $this->assertSame($pedido->id, $repetido->id);
            $this->assertSame('pagado', $pedido->estado);
            $this->assertSame(1, $carrito->confirmaciones);
        } finally {
            Pedido::where('usuario_id', $usuario)->delete();
        }
    }
    public function test_conflicto_del_carrito_y_cancelaciones_reanudables(): void
    {
        if (getenv('TEST_POSTGRES') !== '1') {
            $this->markTestSkipped('Requiere PostgreSQL de pruebas y TEST_POSTGRES=1.');
        }
        $this->assertSame(0, Artisan::call('migrate'));
        config(['pedidos.tokens_salientes' => ['carrito' => 'test', 'inventario' => 'test', 'pagos' => 'test', 'envios' => 'test']]);
        config(['pedidos.urls.carrito' => 'http://carrito']);
        $this->app->bind(CarritoCheckout::class, \App\Pedidos\CarritoHttp::class);
        $entrada = ['direccion' => ['codigo_postal' => '38000', 'calle' => 'Ejemplo', 'ciudad' => 'Celaya', 'estado' => 'Guanajuato'], 'metodo_pago' => 'tarjeta_simulada'];

        foreach (['desactualizado', 'sin_stock', 'rechazado'] as $caso) {
            $usuario = (string) Str::uuid();
            $producto = (string) Str::uuid();
            $clave = (string) Str::uuid();
            $rutas = [];
            $cancelaciones = 0;
            Http::swap(new \Illuminate\Http\Client\Factory);
            Http::fake(function (Request $request) use ($usuario, $producto, $caso, &$rutas, &$cancelaciones) {
                $ruta = basename(parse_url($request->url(), PHP_URL_PATH));
                $rutas[] = $ruta;
                $datos = $request->data();
                $id = ['pedido_id' => $datos['pedido_id'] ?? null];
                if ($ruta === 'preparar') {
                    $this->assertSame('por_preparar_carrito', Pedido::findOrFail($datos['pedido_id'])->paso);
                    if ($caso === 'desactualizado') return Http::response([], 409);
                }
                if ($ruta === 'reservar' && $caso === 'sin_stock') return Http::response([], 409);
                if ($ruta === 'cancelar' && ++$cancelaciones === 1) return Http::response([], 503);
                $respuesta = match ($ruta) {
                    'checkout' => ['carrito_id' => $usuario, 'version' => 'v1', 'items' => [['producto_id' => $producto, 'cantidad' => 2]]],
                    'cotizar' => ['costo_envio' => '4.00'],
                    'reservar' => $id + ['estado' => 'reservada'],
                    'procesar' => $id + ['estado' => 'rechazado', 'monto' => '9.00'],
                    'liberar' => $id + ['estado' => 'liberada'],
                    'preparar', 'cancelar' => ['ok' => true],
                    default => ['precio' => '2.50'],
                };
                return Http::response(['success' => true, 'data' => $respuesta]);
            });
            try {
                $compra = $this->app->make(Compra::class);
                try {
                    $compra->ejecutar($usuario, $clave, $entrada);
                    $this->fail('Se esperaba error');
                } catch (ApiError $error) {
                    $this->assertSame($caso === 'desactualizado' ? 409 : 503, $error->status);
                }
                $esperado = match ($caso) {
                    'desactualizado' => 'carrito_desactualizado',
                    'sin_stock' => 'por_cancelar_carrito_sin_stock',
                    default => 'por_cancelar_carrito_pago',
                };
                $this->assertSame($esperado, Pedido::where('usuario_id', $usuario)->sole()->paso);
                if ($caso === 'desactualizado') {
                    $this->assertNotContains('reservar', $rutas);
                    $this->assertNotContains('procesar', $rutas);
                } else {
                    try { $compra->ejecutar($usuario, $clave, $entrada); } catch (ApiError $error) {
                        $this->assertSame(409, $error->status);
                    }
                    $this->assertSame(2, $cancelaciones);
                    $this->assertSame($caso === 'sin_stock' ? 'sin_stock' : 'terminado', Pedido::where('usuario_id', $usuario)->sole()->paso);
                    $this->assertSame(1, count(array_filter($rutas, fn ($ruta) => $ruta === 'reservar')));
                }
            } finally {
                Pedido::where('usuario_id', $usuario)->delete();
            }
        }
    }

}
