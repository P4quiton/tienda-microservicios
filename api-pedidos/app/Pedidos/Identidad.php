<?php

namespace App\Pedidos;

use Firebase\JWT\JWT;
use Firebase\JWT\Key;
use Illuminate\Http\Request;
use Illuminate\Support\Str;
use Throwable;

final class Identidad
{
    public function usuario(Request $request): array
    {
        $token = $request->bearerToken();
        $ruta = config('pedidos.jwt_public_key_path');

        if ($token === null || !$ruta || !is_readable($ruta)) {
            throw new ApiError(401, 'Credencial inválida');
        }

        try {
            $clave = file_get_contents($ruta);
            $claims = JWT::decode($token, new Key($clave, 'RS256'));
        } catch (Throwable) {
            throw new ApiError(401, 'Credencial inválida');
        }

        if (($claims->iss ?? null) !== 'api-usuarios'
            || !in_array('tienda-microservicios', (array) ($claims->aud ?? []), true)
            || !is_string($claims->sub ?? null)
            || !Str::isUuid($claims->sub, 4)
            || !in_array($claims->role ?? null, ['cliente', 'admin'], true)
            || !is_int($claims->iat ?? null)
            || !is_int($claims->exp ?? null)
            || $claims->iat > time()
            || $claims->exp <= $claims->iat
            || $claims->exp - $claims->iat > 3600) {
            throw new ApiError(401, 'Credencial inválida');
        }

        return ['id' => strtolower($claims->sub), 'rol' => $claims->role];
    }

    public function comprobarTitular(array $usuario, string $titular): void
    {
        if ($usuario['id'] !== $titular && $usuario['rol'] !== 'admin') {
            throw new ApiError(403, 'Permiso insuficiente');
        }
    }

    public function servicio(Request $request, array $permitidos): void
    {
        $token = $request->header('X-Service-Token');
        if (!is_string($token) || $token === '') {
            throw new ApiError(401, 'Credencial inválida');
        }

        foreach (config('pedidos.tokens_entrantes') as $servicio => $secreto) {
            if (is_string($secreto) && $secreto !== '' && hash_equals($secreto, $token)) {
                if (in_array($servicio, $permitidos, true)) {
                    return;
                }
                throw new ApiError(403, 'Permiso insuficiente');
            }
        }
        throw new ApiError(401, 'Credencial inválida');
    }
}
