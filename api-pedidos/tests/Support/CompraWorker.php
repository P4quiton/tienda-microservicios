<?php

// Proceso auxiliar de las pruebas de concurrencia (no es una prueba PHPUnit).
// Uso: php tests/Support/CompraWorker.php <usuario> <clave> <archivo_llamadas>
// Ejecuta Compra::ejecutar con dependencias simuladas y escribe una línea JSON en stdout.

use App\Pedidos\ApiError;
use App\Pedidos\Compra;
use Illuminate\Contracts\Console\Kernel;

[, $usuario, $clave, $llamadas] = $argv;

require __DIR__.'/../../vendor/autoload.php';
$app = require __DIR__.'/../../bootstrap/app.php';
$app->make(Kernel::class)->bootstrap();

$servicios = Tests\Support\ServiciosFalsos::nuevo($usuario);
$servicios->archivo = $llamadas;
$servicios->retardo['pagos.procesar'] = 400_000; // ensancha la ventana de carrera
$servicios->instalar();

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
