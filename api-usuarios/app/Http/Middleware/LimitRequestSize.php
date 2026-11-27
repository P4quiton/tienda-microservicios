<?php

declare(strict_types=1);

namespace App\Http\Middleware;

use App\Support\ApiResponse;
use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class LimitRequestSize
{
    private const MAX_BYTES = 262144;

    public function handle(
        Request $request,
        Closure $next
    ): Response {
        $contentLength = $request->headers->get(
            'Content-Length'
        );

        if (
            $contentLength !== null
            && ctype_digit($contentLength)
            && (int) $contentLength > self::MAX_BYTES
        ) {
            return $this->payloadTooLarge();
        }

        if (
            strlen($request->getContent())
            > self::MAX_BYTES
        ) {
            return $this->payloadTooLarge();
        }

        return $next($request);
    }

    private function payloadTooLarge(): Response
    {
        return ApiResponse::error(
            'El cuerpo de la petición no puede superar 256 KiB.',
            413
        );
    }
}
