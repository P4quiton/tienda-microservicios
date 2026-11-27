<?php

declare(strict_types=1);

namespace App\Http\Middleware;

use App\Support\ApiResponse;
use Closure;
use Illuminate\Http\Request;
use JsonException;
use stdClass;
use Symfony\Component\HttpFoundation\Response;

class RequireJson
{
    public function handle(
        Request $request,
        Closure $next
    ): Response {
        if (! $request->isJson()) {
            return ApiResponse::error(
                'La petición debe contener JSON.',
                400
            );
        }

        try {
            $decoded = json_decode(
                $request->getContent(),
                false,
                512,
                JSON_THROW_ON_ERROR
            );
        } catch (JsonException) {
            return ApiResponse::error(
                'El JSON proporcionado no es válido.',
                400
            );
        }

        if (! $decoded instanceof stdClass) {
            return ApiResponse::error(
                'El cuerpo debe ser un objeto JSON.',
                400
            );
        }

        return $next($request);
    }
}