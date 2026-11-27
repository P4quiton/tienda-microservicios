<?php

use App\Http\Controllers\Api\ProductoController;
use Illuminate\Support\Facades\Route;

Route::get('/productos', [ProductoController::class, 'index'])
    ->middleware('throttle:productos-consultas')
    ->name('productos.index');
Route::get('/productos/{id}', [ProductoController::class, 'show'])
    ->whereUuid('id')
    ->middleware('throttle:productos-consultas')
    ->name('productos.show');
Route::post('/productos', [ProductoController::class, 'store'])
    ->middleware('throttle:productos-mutaciones')
    ->middleware('admin.jwt')
    ->name('productos.store');
