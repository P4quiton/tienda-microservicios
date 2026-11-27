<?php

use App\Http\Controllers\Api\ProductoController;
use Illuminate\Support\Facades\Route;

Route::get('/productos', [ProductoController::class, 'index'])->name('productos.index');
Route::get('/productos/{id}', [ProductoController::class, 'show'])
    ->whereUuid('id')
    ->name('productos.show');
Route::post('/productos', [ProductoController::class, 'store'])
    ->middleware('admin.jwt')
    ->name('productos.store');
