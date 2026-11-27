<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use Symfony\Component\HttpFoundation\Response;

class VerifyAdminJwt
{
    /**
     * Handle an incoming request.
     *
     * @param  Closure(Request): (Response)  $next
     */
    public function handle(Request $request, Closure $next): Response
    {
        $unauthorized = fn (): Response => response()->json([
            'success' => false,
            'message' => 'Credencial inválida.',
            'errors' => (object) [],
        ], 401);

        $token = $request->bearerToken();
        $parts = $token === null ? [] : explode('.', $token);

        if (count($parts) !== 3) {
            return $unauthorized();
        }

        try {
            $header = json_decode($this->decodeSegment($parts[0]), true, flags: JSON_THROW_ON_ERROR);
            $claims = json_decode($this->decodeSegment($parts[1]), true, flags: JSON_THROW_ON_ERROR);
            $signature = $this->decodeSegment($parts[2]);
        } catch (\Throwable) {
            return $unauthorized();
        }

        if (! is_array($header) || ($header['alg'] ?? null) !== 'RS256' || ! is_array($claims)) {
            return $unauthorized();
        }

        $keyPath = config('services.jwt.public_key_path');
        $publicKey = is_string($keyPath) && $keyPath !== '' ? @file_get_contents($keyPath) : false;

        if ($publicKey === false || trim($publicKey) === '') {
            Log::error('La clave pública JWT no está configurada para api-productos.');

            return response()->json([
                'success' => false,
                'message' => 'Servicio temporalmente no disponible.',
                'errors' => (object) [],
            ], 503);
        }

        $key = openssl_pkey_get_public($publicKey);
        $validSignature = $key !== false && openssl_verify(
            $parts[0].'.'.$parts[1],
            $signature,
            $key,
            OPENSSL_ALGO_SHA256,
        ) === 1;

        if (! $validSignature) {
            return $unauthorized();
        }

        $now = time();
        $audience = $claims['aud'] ?? null;
        $audiences = is_array($audience) ? $audience : [$audience];
        $subject = $claims['sub'] ?? null;
        $validSubject = is_string($subject) && preg_match(
            '/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i',
            $subject,
        ) === 1;

        if (
            ($claims['iss'] ?? null) !== config('services.jwt.issuer')
            || ! in_array(config('services.jwt.audience'), $audiences, true)
            || ! $validSubject
            || ! is_int($claims['iat'] ?? null)
            || ! is_int($claims['exp'] ?? null)
            || $claims['iat'] > $now + 30
            || $claims['exp'] <= $now
        ) {
            return $unauthorized();
        }

        if (($claims['role'] ?? null) !== 'admin') {
            return response()->json([
                'success' => false,
                'message' => 'Permiso insuficiente.',
                'errors' => (object) [],
            ], 403);
        }

        return $next($request);
    }

    private function decodeSegment(string $segment): string
    {
        $decoded = base64_decode(strtr($segment, '-_', '+/'), true);

        if ($decoded === false) {
            throw new \UnexpectedValueException('Segmento JWT inválido.');
        }

        return $decoded;
    }
}
