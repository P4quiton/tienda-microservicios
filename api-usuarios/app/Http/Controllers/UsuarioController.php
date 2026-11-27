<?php

declare(strict_types=1);

namespace App\Http\Controllers;

use App\Exceptions\CorreoDuplicadoException;
use App\Exceptions\CredencialesInvalidasException;
use App\Http\Requests\LoginRequest;
use App\Http\Requests\RegistroRequest;
use App\Http\Resources\UsuarioResource;
use App\Services\JwtService;
use App\Services\UsuarioService;
use App\Support\ApiResponse;
use Illuminate\Database\QueryException;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Log;
use RuntimeException;
use Illuminate\Http\Request;
use Illuminate\Support\Str;

class UsuarioController extends Controller
{
    public function register(
        RegistroRequest $request,
        UsuarioService $service
    ): JsonResponse {
        try {
            $user = $service->register(
                $request->validated()
            );

            return ApiResponse::success(
                'Usuario registrado correctamente.',
                (new UsuarioResource($user))->resolve($request),
                201
            );
        } catch (CorreoDuplicadoException) {
            return ApiResponse::error(
                'El correo ya está registrado.',
                409,
                [
                    'correo' => [
                        'El correo ya está registrado.',
                    ],
                ]
            );
        } catch (QueryException $exception) {
            return $this->databaseError($exception);
        }
    }

    public function login(
        LoginRequest $request,
        UsuarioService $service,
        JwtService $jwt
    ): JsonResponse {
        try {
            $user = $service->authenticate(
                $request->validated()
            );

            $jwt->assertReady();

            $token = $jwt->issue($user);

            $response = ApiResponse::success(
                'Inicio de sesión correcto.',
                [
                    'access_token' => $token,
                    'token_type' => 'Bearer',
                    'expires_in' => $jwt->ttl(),
                    'usuario' => (new UsuarioResource($user))
                        ->resolve($request),
                ]
            );

            $response->headers->set(
                'Cache-Control',
                'no-store'
            );

            $response->headers->set(
                'Pragma',
                'no-cache'
            );

            return $response;

        } catch (CredencialesInvalidasException) {
            return ApiResponse::error(
                'Credenciales inválidas.',
                401
            );
        } catch (QueryException $exception) {
            return $this->databaseError($exception);
        } catch (RuntimeException) {
            Log::error(
                'Fallo interno durante la autenticación.'
            );

            return ApiResponse::error(
                'Servicio temporalmente no disponible.',
                503
            );
        }
    }


    public function show(
        Request $request,
        UsuarioService $service,
        string $id
    ): JsonResponse {
        $claims = $request->attributes->get('jwt_claims');

        if (! is_array($claims)) {
            return ApiResponse::error(
                'Token de autenticación inválido o ausente.',
                401,
                [],
                ['WWW-Authenticate' => 'Bearer']
            );
        }

        if (! Str::isUuid($id, 4)) {
            return ApiResponse::error(
                'Identificador de usuario inválido.',
                422,
                [
                    'id' => [
                        'El identificador debe ser un UUID v4.',
                    ],
                ]
            );
        }

        $id = Str::lower($id);
        $authenticatedId = Str::lower($claims['sub']);

        try {
            $authenticatedUser = $service->findById(
                $authenticatedId
            );

            if (
                $authenticatedUser === null
                || $authenticatedUser->role !== $claims['role']
            ) {
                return ApiResponse::error(
                    'Token de autenticación inválido.',
                    401,
                    [],
                    ['WWW-Authenticate' => 'Bearer']
                );
            }

            if (
                $authenticatedId !== $id
                && $authenticatedUser->role !== 'admin'
            ) {
                return ApiResponse::error(
                    'No tienes permiso para consultar este usuario.',
                    403
                );
            }

            $user = $authenticatedId === $id
                ? $authenticatedUser
                : $service->findById($id);

            if ($user === null) {
                return ApiResponse::error(
                    'Usuario no encontrado.',
                    404
                );
            }

            $response = ApiResponse::success(
                'Usuario consultado correctamente.',
                (new UsuarioResource($user))->resolve($request)
            );

            $response->headers->set(
                'Cache-Control',
                'no-store'
            );

            return $response;

        } catch (QueryException $exception) {
            return $this->databaseError($exception);
        }
    }


    private function databaseError(
        QueryException $exception
    ): JsonResponse {
        $sqlState = (string) (
            $exception->errorInfo[0]
            ?? $exception->getCode()
        );

        Log::error('Fallo de persistencia en Usuarios.', [
            'sqlstate' => $sqlState,
        ]);

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
            'No se pudo completar la operación.',
            500
        );
    }
}
