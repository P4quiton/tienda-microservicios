<?php

declare(strict_types=1);

namespace App\Exceptions;

use App\Support\ApiResponse;
use Illuminate\Auth\Access\AuthorizationException;
use Illuminate\Auth\AuthenticationException;
use Illuminate\Database\Eloquent\ModelNotFoundException;
use Illuminate\Database\QueryException;
use Illuminate\Http\Exceptions\HttpResponseException;
use Illuminate\Http\JsonResponse;
use Illuminate\Validation\ValidationException;
use Symfony\Component\HttpKernel\Exception\HttpExceptionInterface;
use Throwable;

class ApiExceptionHandler
{
    public function render(Throwable $exception): JsonResponse
    {
        if ($exception instanceof HttpResponseException) {
            $response = $exception->getResponse();

            if ($response instanceof JsonResponse) {
                return $response;
            }
        }

        if ($exception instanceof ValidationException) {
            return ApiResponse::error(
                'Error de validación.',
                422,
                $exception->errors()
            );
        }

        if ($exception instanceof AuthenticationException) {
            return ApiResponse::error(
                'Autenticación requerida.',
                401,
                [],
                ['WWW-Authenticate' => 'Bearer']
            );
        }

        if ($exception instanceof AuthorizationException) {
            return ApiResponse::error(
                'No tienes permiso para realizar esta operación.',
                403
            );
        }

        if ($exception instanceof ModelNotFoundException) {
            return ApiResponse::error(
                'Recurso no encontrado.',
                404
            );
        }

        if ($exception instanceof QueryException) {
            $sqlState = (string) (
                $exception->errorInfo[0]
                ?? $exception->getCode()
            );

            if (
                str_starts_with($sqlState, '08')
                || in_array(
                    $sqlState,
                    ['57P01', '57P02', '57P03', '53300'],
                    true
                )
            ) {
                return ApiResponse::error(
                    'Servicio temporalmente no disponible.',
                    503
                );
            }

            return ApiResponse::error(
                'Error interno del servidor.',
                500
            );
        }

        if ($exception instanceof HttpExceptionInterface) {
            $status = $exception->getStatusCode();

            $message = match ($status) {
                400 => 'Petición inválida.',
                401 => 'Autenticación requerida.',
                403 => 'Acceso denegado.',
                404 => 'Recurso no encontrado.',
                405 => 'Método HTTP no permitido.',
                409 => 'Conflicto con el estado del recurso.',
                413 => 'El cuerpo de la petición es demasiado grande.',
                415 => 'Tipo de contenido no permitido.',
                422 => 'Error de validación.',
                429 => 'Demasiadas solicitudes. Intenta más tarde.',
                503 => 'Servicio temporalmente no disponible.',
                default => $status >= 500
                    ? 'Error interno del servidor.'
                    : 'No se pudo completar la petición.',
            };

            $headers = array_intersect_key(
                $exception->getHeaders(),
                array_flip([
                    'Allow',
                    'Retry-After',
                    'WWW-Authenticate',
                ])
            );

            return ApiResponse::error(
                $message,
                $status,
                [],
                $headers
            );
        }

        return ApiResponse::error(
            'Error interno del servidor.',
            500
        );
    }
}
