<?php

declare(strict_types=1);

namespace App\Http\Middleware;

use App\Services\JwtService;
use App\Support\ApiResponse;
use Closure;
use DomainException;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use RuntimeException;
use Symfony\Component\HttpFoundation\Response;
use UnexpectedValueException;

class JwtAuthentication
{
    public function handle(
        Request $request,
        Closure $next
    ): Response {
        $authorization = $request->header('Authorization');

        if (
            ! is_string($authorization)
            || strlen($authorization) > 8200
            || preg_match(
                '/^Bearer ([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)$/iD',
                $authorization,
                $matches
            ) !== 1
        ) {
            return $this->unauthorized();
        }

        try {
            $jwt = app(JwtService::class);

            $claims = $jwt->verify($matches[1]);

        } catch (UnexpectedValueException | DomainException) {
            return $this->unauthorized();

        } catch (RuntimeException) {
            Log::error(
                'Servicio de verificacion JWT no disponible.'
            );

            return ApiResponse::error(
                'Servicio temporalmente no disponible.',
                503
            );
        }

        $request->attributes->set('jwt_claims', $claims);

        return $next($request);
    }

    private function unauthorized(): Response
    {
        return ApiResponse::error(
            'Token de autenticación inválido o ausente.',
            401,
            [],
            ['WWW-Authenticate' => 'Bearer']
        );
    }
}
