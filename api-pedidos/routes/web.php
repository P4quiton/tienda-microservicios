<?php

use App\Pedidos\Controlador;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Route;

Route::get('/health', fn () => response()->json(['status' => 'ok', 'service' => 'api-pedidos']));

Route::get('/ready', function () {
    try {
        DB::selectOne('select 1 from pedidos limit 1');
    } catch (Throwable) {
        return response()->json(['status' => 'unavailable', 'service' => 'api-pedidos'], 503);
    }

    return response()->json(['status' => 'ok', 'service' => 'api-pedidos']);
});

Route::post('/api/pedidos', [Controlador::class, 'crear']);
Route::get('/api/pedidos/usuario/{usuario_id}', [Controlador::class, 'historial']);
Route::get('/api/pedidos/{id}', [Controlador::class, 'consultar']);
Route::patch('/api/pedidos/{id}/estado', [Controlador::class, 'cambiarEstado']);
