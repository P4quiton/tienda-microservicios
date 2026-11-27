<?php

declare(strict_types=1);

namespace App\Http\Middleware;

use App\Support\ApiResponse;
use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\RateLimiter;
use Symfony\Component\HttpFoundation\Response;

class AuthenticatedRateLimit
{
    private const MAX_ATTEMPTS = 120;

    private const DECAY_SECONDS = 60;

    public function handle(
        Request $request,
        Closure $next
    ): Response {
        $claims = $request->attributes->get('jwt_claims');

        if (
            ! is_array($claims)
            || ! isset($claims['sub'])
            || ! is_string($claims['sub'])
        ) {
            return ApiResponse::error(
                'Token de autenticación inválido o ausente.',
                401,
                [],
                ['WWW-Authenticate' => 'Bearer']
            );
        }

        $key = 'usuarios-perfil:'.strtolower($claims['sub']);

        if (
            RateLimiter::tooManyAttempts(
                $key,
                self::MAX_ATTEMPTS
            )
        ) {
            return ApiResponse::error(
                'Demasiadas solicitudes. Intenta más tarde.',
                429,
                [],
                [
                    'Retry-After' => (string)
                        RateLimiter::availableIn($key),

                    'X-RateLimit-Limit' => (string)
                        self::MAX_ATTEMPTS,

                    'X-RateLimit-Remaining' => '0',
                ]
            );
        }

        RateLimiter::hit(
            $key,
            self::DECAY_SECONDS
        );

        $response = $next($request);

        $response->headers->set(
            'X-RateLimit-Limit',
            (string) self::MAX_ATTEMPTS
        );

        $response->headers->set(
            'X-RateLimit-Remaining',
            (string) RateLimiter::remaining(
                $key,
                self::MAX_ATTEMPTS
            )
        );

        return $response;
    }
}
