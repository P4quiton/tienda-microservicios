<?php

use App\Pedidos\ApiError;
use App\Pedidos\BaseNoDisponible;
use App\Pedidos\LimitarSolicitudes;
use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use Symfony\Component\HttpKernel\Exception\HttpExceptionInterface;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        using: fn () => Route::middleware(['api', LimitarSolicitudes::class])->group(base_path('routes/web.php')),
        commands: __DIR__.'/../routes/console.php',
    )
    ->withMiddleware()
    ->withExceptions(function (Exceptions $exceptions): void {
        $exceptions->shouldRenderJsonWhen(
            fn (Request $request) => $request->is('api/*') || $request->expectsJson(),
        );
        $exceptions->render(function (Throwable $error, Request $request) {
            if (!$request->is('api/*')) {
                return null;
            }
            $baseCaida = BaseNoDisponible::causa($error);
            $status = match (true) {
                $error instanceof ApiError => $error->status,
                $baseCaida => 503,
                $error instanceof HttpExceptionInterface => $error->getStatusCode(),
                default => 500,
            };

            return response()->json([
                'success' => false,
                'message' => match (true) {
                    $error instanceof ApiError => $error->getMessage(),
                    $baseCaida => 'Dependencia no disponible',
                    default => 'Error al procesar la solicitud',
                },
                'errors' => (object) ($error instanceof ApiError ? $error->errors : []),
            ], $status);
        });
    })->create();
