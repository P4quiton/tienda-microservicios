<?php

// Proceso auxiliar de las pruebas de concurrencia (no es una prueba PHPUnit).
// Uso: php tests/Support/CompraWorker.php <usuario> <clave> <archivo_llamadas>
// Ejecuta Compra::ejecutar con dependencias simuladas y escribe una línea JSON en stdout.

use App\Pedidos\ApiError;
use App\Pedidos\CarritoCheckout;
use App\Pedidos\Compra;
use App\Pedidos\Pedido;
use Illuminate\Contracts\Console\Kernel;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;

[, $usuario, $clave, $llamadas] = $argv;

require __DIR__.'/../../vendor/autoload.php';
$app = require __DIR__.'/../../bootstrap/app.php';
$app->make(Kernel::class)->bootstrap();

$producto = '11111111-1111-4111-8111-111111111111';
$app->instance(CarritoCheckout::class, new class($producto) implements CarritoCheckout {
    public function __construct(private string $producto) {}

    public function leer(string $usuarioId): array
    {
        return ['carrito_id' => $usuarioId, 'version' => '1', 'items' => [['producto_id' => $this->producto, 'cantidad' => 1]]];
    }

    public function preparar(Pedido $pedido): void {}

    public function cancelar(Pedido $pedido): void {}

    public function confirmar(Pedido $pedido): void {}
});

config(['pedidos.tokens_salientes' => ['inventario' => 't', 'pagos' => 't', 'envios' => 't']]);
Http::fake(function (Request $peticion) use ($llamadas) {
    $ruta = basename(parse_url($peticion->url(), PHP_URL_PATH));
    file_put_contents($llamadas, $ruta."\n", FILE_APPEND | LOCK_EX);
    $id = ['pedido_id' => $peticion->data()['pedido_id'] ?? null];
    if ($ruta === 'procesar') {
        usleep(400_000); // ensancha la ventana de carrera
    }
    $datos = match ($ruta) {
        'cotizar' => ['costo_envio' => '4.00'],
        'reservar' => $id + ['estado' => 'reservada'],
        'procesar' => $id + ['estado' => 'aprobado', 'monto' => '9.00'],
        'confirmar' => $id + ['estado' => 'confirmada'],
        'generar' => $id + ['guia' => 'GUIA-FICTICIA'],
        default => ['precio' => '5.00'],
    };

    return Http::response(['success' => true, 'data' => $datos]);
});

$entrada = [
    'direccion' => ['codigo_postal' => '38000', 'calle' => 'Ejemplo', 'ciudad' => 'Celaya', 'estado' => 'Guanajuato'],
    'metodo_pago' => 'tarjeta_simulada',
];
try {
    $pedido = $app->make(Compra::class)->ejecutar($usuario, $clave, $entrada);
    echo json_encode(['status' => 201, 'pedido' => $pedido->id, 'estado' => $pedido->estado]), "\n";
} catch (ApiError $error) {
    echo json_encode(['status' => $error->status]), "\n";
}
