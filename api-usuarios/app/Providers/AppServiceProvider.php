<?php

namespace App\Providers;

use App\Support\ApiResponse;
use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\ServiceProvider;
use Illuminate\Support\Str;

class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        //
    }

    public function boot(): void
    {
        $tooManyRequests = function (
            Request $request,
            array $headers
        ) {
            return ApiResponse::error(
                'Demasiadas solicitudes. Intenta más tarde.',
                429,
                [],
                $headers
            );
        };

        RateLimiter::for(
            'usuarios-registro',
            function (Request $request) use ($tooManyRequests) {
                return Limit::perMinute(5)
                    ->by('registro-ip:'.$request->ip())
                    ->response($tooManyRequests);
            }
        );

        RateLimiter::for(
            'usuarios-login',
            function (Request $request) use ($tooManyRequests) {
                $limits = [
                    Limit::perMinute(5)
                        ->by('login-ip:'.$request->ip())
                        ->response($tooManyRequests),
                ];

                $correo = $request->json('correo');

                if (
                    is_string($correo)
                    && strlen($correo) <= 1024
                    && trim($correo) !== ''
                ) {
                    $normalized = Str::lower(trim($correo));

                    $limits[] = Limit::perMinute(5)
                        ->by(
                            'login-correo:'.hash(
                                'sha256',
                                $normalized
                            )
                        )
                        ->response($tooManyRequests);
                }

                return $limits;
            }
        );

        RateLimiter::for(
            'usuarios-perfil-ip',
            function (Request $request) use ($tooManyRequests) {
                return Limit::perMinute(300)
                    ->by('perfil-ip:'.$request->ip())
                    ->response($tooManyRequests);
            }
        );
    }
}
