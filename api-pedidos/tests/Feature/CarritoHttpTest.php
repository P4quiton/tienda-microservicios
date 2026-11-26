<?php

namespace Tests\Feature;

use App\Pedidos\ApiError;
use App\Pedidos\CarritoHttp;
use App\Pedidos\Pedido;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;
use Tests\Support\ServiciosFalsos;
use Tests\TestCase;

/** Adaptador de Pedidos hacia Carrito según carrito.yaml 1.1.0 (solo contra dobles HTTP). */
final class CarritoHttpTest extends TestCase
{
    private function pedido(ServiciosFalsos $s): Pedido
    {
        return new Pedido([
            'id' => (string) Str::uuid(), 'usuario_id' => $s->usuario, 'carrito_version' => '3',
            'snapshot' => $s->itemsSnapshot(),
        ]);
    }

    public function test_protocolo_iniciar_finalizar_liberar_con_token_idempotencia_y_linea_id(): void
    {
        $s = ServiciosFalsos::nuevo()->instalar();
        $carrito = $this->app->make(CarritoHttp::class);

        $lectura = $carrito->leer($s->usuario);
        $this->assertSame(3, $lectura['version']);
        $this->assertSame($s->itemsSnapshot(), $lectura['items']);

        $pedido = $this->pedido($s);
        $this->assertSame($s->itemsSnapshot(), $carrito->iniciar($pedido));
        $carrito->finalizar($pedido);
        $carrito->liberar($pedido);

        $base = "http://carrito/api/carrito/{$s->usuario}";
        Http::assertSent(fn (Request $r) => $r->method() === 'GET' && $r->url() === $base && $r->header('X-Service-Token') === ['tc']);
        Http::assertSent(fn (Request $r) => $r->url() === "$base/iniciar" && $r->header('X-Service-Token') === ['tc']
            && $r->header('Idempotency-Key') === [$pedido->clave('iniciar')]
            && $r->data() === ['pedido_id' => $pedido->id, 'version_original' => 3]);
        Http::assertSent(fn (Request $r) => $r->url() === "$base/finalizar" && $r->header('Idempotency-Key') === [$pedido->clave('finalizar')]
            && $r->data() === ['pedido_id' => $pedido->id, 'version_original' => 3, 'items' => $s->itemsSnapshot()]);
        Http::assertSent(fn (Request $r) => $r->url() === "$base/liberar" && $r->header('Idempotency-Key') === [$pedido->clave('liberar_carrito')]
            && $r->data() === ['pedido_id' => $pedido->id]);
        $this->assertTrue(Str::isUuid($pedido->clave('iniciar')));
        // Regresion E2E: Carrito/Envios/Inventario exigen Idempotency-Key UUID v4 (el v5 anterior daba 422).
        foreach (['iniciar', 'finalizar', 'liberar_carrito', 'liberar', 'confirmar', 'generar'] as $operacion) {
            $this->assertTrue(Str::isUuid($pedido->clave($operacion), 4), "clave($operacion) no es UUID v4");
        }
        $this->assertNotSame($pedido->clave('iniciar'), $pedido->clave('finalizar'));
        $this->assertSame($pedido->clave('iniciar'), $pedido->clave('iniciar'));
    }

    public function test_iniciar_traduce_409_a_conflicto_y_rechaza_snapshots_invalidos(): void
    {
        $s = ServiciosFalsos::nuevo()->instalar();
        $s->version = 9; // distinta de la versión_original del pedido
        $carrito = $this->app->make(CarritoHttp::class);
        try {
            $carrito->iniciar($this->pedido($s));
            $this->fail('Se esperaba conflicto');
        } catch (ApiError $error) {
            $this->assertSame(409, $error->status);
        }

        $casos = [
            'sin linea_id' => [['producto_id' => $s->producto, 'cantidad' => 1]],
            'linea repetida' => [['producto_id' => $s->producto, 'cantidad' => 1, 'linea_id' => $s->linea], ['producto_id' => $s->producto, 'cantidad' => 1, 'linea_id' => $s->linea]],
            'cantidad cero' => [['producto_id' => $s->producto, 'cantidad' => 0, 'linea_id' => $s->linea]],
        ];
        foreach ($casos as $nombre => $items) {
            Http::swap(new \Illuminate\Http\Client\Factory);
            Http::fake(['*' => Http::response(['success' => true, 'data' => ['usuario_id' => $s->usuario, 'version' => 3, 'items' => $items]])]);
            try {
                $carrito->leer($s->usuario);
                $this->fail("Debía rechazar: $nombre");
            } catch (ApiError $error) {
                $this->assertSame(503, $error->status, $nombre);
            }
        }
        // La versión debe ser entera.
        Http::swap(new \Illuminate\Http\Client\Factory);
        Http::fake(['*' => Http::response(['success' => true, 'data' => ['usuario_id' => $s->usuario, 'version' => 'v1', 'items' => []]])]);
        $this->expectException(ApiError::class);
        $carrito->leer($s->usuario);
    }

    public function test_sin_url_ni_token_el_fallo_es_controlado(): void
    {
        $s = ServiciosFalsos::nuevo()->instalar();
        config(['pedidos.tokens_salientes.carrito' => '']);
        try {
            $this->app->make(CarritoHttp::class)->leer($s->usuario);
            $this->fail('Se esperaba 503');
        } catch (ApiError $error) {
            $this->assertSame(503, $error->status);
        }
        config(['pedidos.tokens_salientes.carrito' => 'x', 'pedidos.urls.carrito' => null]);
        $this->expectException(ApiError::class);
        $this->app->make(CarritoHttp::class)->leer($s->usuario);
    }
}
