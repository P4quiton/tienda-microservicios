
<?php

use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use App\Exceptions\ApiExceptionHandler;
use Illuminate\Support\Facades\Log;
use App\Http\Middleware\LimitRequestSize;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        then: function (): void {
            Route::middleware('api')
                ->group(__DIR__.'/../routes/health.php');
        },
    )
    ->withMiddleware(function (Middleware $middleware): void {
        // Solo se lee X-Forwarded-For si el socket pertenece a un proxy listado en TRUSTED_PROXIES.
        $trustedProxies = require __DIR__.'/../config/trustedproxy.php';
        $middleware->trustProxies(
            at: $trustedProxies['proxies'],
            headers: Request::HEADER_X_FORWARDED_FOR,
        );
        $middleware->prepend(LimitRequestSize::class);
        $middleware->trimStrings(except: [
            'contrasena',
        ]);
    })
    ->withExceptions(function (Exceptions $exceptions): void {
        $exceptions->shouldRenderJsonWhen(
            fn (Request $request) => true,
        );

        $exceptions->dontFlash([
            'contrasena',
            'password',
            'password_confirmation',
            'current_password',
        ]);

        $exceptions->render(
            function (\Throwable $exception, Request $request) {
                return app(ApiExceptionHandler::class)
                    ->render($exception);
            }
        );

        $exceptions->report(
            function (\Throwable $exception) {
                $context = [
                    'exception_type' => get_class($exception),
                ];

                if (
                    $exception instanceof
                    \Illuminate\Database\QueryException
                ) {
                    $context['sqlstate'] = (string) (
                        $exception->errorInfo[0]
                        ?? $exception->getCode()
                    );
                }

                Log::error(
                    'Excepcion interna en api-usuarios.',
                    $context
                );

                return false;
            }
        );
    })

    ->create();
