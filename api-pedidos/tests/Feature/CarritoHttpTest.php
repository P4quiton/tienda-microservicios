<?php

namespace Tests\Feature;

use App\Pedidos\ApiError;
use App\Pedidos\CarritoCheckout;
use App\Pedidos\CarritoHttp;
use App\Pedidos\CarritoSinContrato;
use App\Pedidos\Pedido;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;
use Tests\TestCase;

final class CarritoHttpTest extends TestCase
{
    public function test_protocolo_y_autenticacion_del_carrito(): void
    {
        $usuario = (string) Str::uuid();
        $producto = (string) Str::uuid();
        $id = (string) Str::uuid();
        config(['pedidos.urls.carrito' => 'http://carrito', 'pedidos.tokens_salientes.carrito' => 'secreto']);
        Http::fake(function (Request $request) use ($usuario, $producto) {
            $this->assertSame(['secreto'], $request->header('X-Service-Token'));
            return Http::response(['success' => true, 'data' => strtoupper($request->method()) === 'GET'
                ? ['carrito_id' => $usuario, 'version' => 'v1', 'items' => [['producto_id' => $producto, 'cantidad' => 2]]]
                : ['ok' => true]]);
        });
        $carrito = $this->app->make(CarritoHttp::class);
        $this->assertSame('v1', $carrito->leer($usuario)['version']);
        $pedido = new Pedido(['id' => $id, 'usuario_id' => $usuario, 'carrito_version' => 'v1',
            'items' => [['producto_id' => $producto, 'cantidad' => 2, 'precio_unitario' => '5.00']]]);
        $carrito->preparar($pedido);
        $carrito->confirmar($pedido);
        $carrito->cancelar($pedido);
        foreach (['preparar', 'confirmar', 'cancelar'] as $accion) {
            Http::assertSent(fn (Request $request) => $request->url() === "http://carrito/api/carrito/$usuario/checkout/$accion"
                && $request->data() === ['pedido_id' => $id, 'version' => 'v1', 'items' => [['producto_id' => $producto, 'cantidad' => 2]]]);
        }
    }

    public function test_preparar_rechaza_conflicto_y_por_defecto_puerto_desactivado(): void
    {
        $this->assertInstanceOf(CarritoSinContrato::class, $this->app->make(CarritoCheckout::class));
        config(['pedidos.urls.carrito' => 'http://carrito', 'pedidos.tokens_salientes.carrito' => 'secreto']);
        Http::fake(['*' => Http::response([], 409)]);
        $pedido = new Pedido(['id' => (string) Str::uuid(), 'usuario_id' => (string) Str::uuid(), 'carrito_version' => '1', 'items' => []]);
        try {
            $this->app->make(CarritoHttp::class)->preparar($pedido);
            $this->fail('Se esperaba conflicto');
        } catch (ApiError $error) {
            $this->assertSame(409, $error->status);
        }
    }
}
