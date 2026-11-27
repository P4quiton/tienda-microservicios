
<?php

use App\Http\Controllers\UsuarioController;
use App\Http\Middleware\AuthenticatedRateLimit;
use App\Http\Middleware\JwtAuthentication;
use App\Http\Middleware\RequireJson;
use Illuminate\Support\Facades\Route;

Route::prefix('usuarios')->group(function (): void {
    Route::post(
        '/registro',
        [UsuarioController::class, 'register']
    )->middleware([
        'throttle:usuarios-registro',
        RequireJson::class,
    ]);

    Route::post(
        '/login',
        [UsuarioController::class, 'login']
    )->middleware([
        'throttle:usuarios-login',
        RequireJson::class,
    ]);

    Route::get(
        '/{id}',
        [UsuarioController::class, 'show']
    )->middleware([
        'throttle:usuarios-perfil-ip',
        JwtAuthentication::class,
        AuthenticatedRateLimit::class,
    ]);
});
