<?php

use App\Http\Middleware\VerifyAdminJwt;
use Illuminate\Database\Eloquent\ModelNotFoundException;
use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use Illuminate\Http\Request;
use Illuminate\Validation\ValidationException;
use Symfony\Component\HttpKernel\Exception\HttpExceptionInterface;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        api: __DIR__.'/../routes/api.php',
        web: __DIR__.'/../routes/web.php',
        commands: __DIR__.'/../routes/console.php',
        health: '/up',
        then: function (): void {
            require __DIR__.'/../routes/health.php';
        },
    )
    ->withMiddleware(function (Middleware $middleware): void {
        $trustedProxies = require __DIR__.'/../config/trustedproxy.php';
        $middleware->trustProxies(
            at: $trustedProxies['proxies'],
            headers: Request::HEADER_X_FORWARDED_FOR,
        );
        $middleware->alias([
            'admin.jwt' => VerifyAdminJwt::class,
        ]);
    })
    ->withExceptions(function (Exceptions $exceptions): void {
        $exceptions->shouldRenderJsonWhen(
            fn (Request $request) => $request->is('api/*') || $request->expectsJson(),
        );

        $exceptions->render(function (ValidationException $exception, Request $request) {
            if (! $request->is('api/*')) {
                return null;
            }

            return response()->json([
                'success' => false,
                'message' => 'Los datos enviados no son válidos.',
                'errors' => $exception->errors(),
            ], 422);
        });

        $exceptions->render(function (HttpExceptionInterface $exception, Request $request) {
            if (! $request->is('api/*')) {
                return null;
            }

            $status = $exception->getStatusCode();
            $message = match ($status) {
                404 => 'Recurso no encontrado.',
                405 => 'Método no permitido.',
                429 => 'Demasiadas solicitudes. Intenta más tarde.',
                default => $status >= 500 ? 'Error interno.' : 'Solicitud no válida.',
            };

            return response()->json([
                'success' => false,
                'message' => $message,
                'errors' => (object) [],
            ], $status, $exception->getHeaders());
        });

        $exceptions->render(function (ModelNotFoundException $exception, Request $request) {
            if (! $request->is('api/*')) {
                return null;
            }

            return response()->json([
                'success' => false,
                'message' => 'Recurso no encontrado.',
                'errors' => (object) [],
            ], 404);
        });

        $exceptions->render(function (Throwable $exception, Request $request) {
            if (! $request->is('api/*')) {
                return null;
            }

            return response()->json([
                'success' => false,
                'message' => 'Error interno.',
                'errors' => (object) [],
            ], 500);
        });
    })->create();
