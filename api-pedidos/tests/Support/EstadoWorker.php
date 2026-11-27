<?php

// Ejecuta el PATCH mediante el kernel HTTP en una conexión PostgreSQL independiente.
use Illuminate\Contracts\Console\Kernel as ConsoleKernel;
use Illuminate\Contracts\Http\Kernel as HttpKernel;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

[, $id, $clave, $conexion] = $argv;

require __DIR__.'/../../vendor/autoload.php';
$app = require __DIR__.'/../../bootstrap/app.php';
$app->make(ConsoleKernel::class)->bootstrap();
DB::selectOne("SELECT set_config('application_name', ?, false)", [$conexion]);

$peticion = Request::create("/api/pedidos/$id/estado", 'PATCH', server: [
    'CONTENT_TYPE' => 'application/json',
    'HTTP_ACCEPT' => 'application/json',
    'HTTP_IDEMPOTENCY_KEY' => $clave,
    'HTTP_X_SERVICE_TOKEN' => getenv('SERVICE_TOKEN_ENVIOS_PEDIDOS'),
], content: '{"estado":"enviado"}');

$kernel = $app->make(HttpKernel::class);
$respuesta = $kernel->handle($peticion);
$kernel->terminate($peticion, $respuesta);
echo json_encode([
    'status' => $respuesta->getStatusCode(),
    'cuerpo' => json_decode($respuesta->getContent(), true, flags: JSON_THROW_ON_ERROR),
], JSON_THROW_ON_ERROR), "\n";
