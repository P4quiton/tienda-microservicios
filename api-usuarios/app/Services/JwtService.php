<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\User;
use Firebase\JWT\JWT;
use Firebase\JWT\Key;
use Illuminate\Support\Str;
use OpenSSLAsymmetricKey;
use RuntimeException;
use UnexpectedValueException;

class JwtService
{
    private const ALGORITHM = 'RS256';

    private const ROLES = ['cliente', 'admin'];

    public function issue(User $user): string
    {
        if (
            ! Str::isUuid((string) $user->id, 4)
            || ! in_array($user->role, self::ROLES, true)
        ) {
            throw new RuntimeException(
                'Identidad de usuario invalida.'
            );
        }

        $issuedAt = time();

        $payload = [
            'sub' => (string) $user->id,
            'role' => $user->role,
            'iss' => config('jwt.issuer'),
            'aud' => config('jwt.audience'),
            'iat' => $issuedAt,
            'exp' => $issuedAt + $this->ttl(),
        ];

        return JWT::encode(
            $payload,
            $this->privateKey(),
            self::ALGORITHM
        );
    }

    public function verify(string $token): array
    {
        if ($token === '' || strlen($token) > 8192) {
            throw new UnexpectedValueException(
                'Token invalido.'
            );
        }

        $key = new Key(
            $this->publicKey(),
            self::ALGORITHM
        );

        $claims = (array) JWT::decode($token, $key);

        $this->validateClaims($claims);

        return $claims;
    }

    public function ttl(): int
    {
        $ttl = config('jwt.ttl_seconds');

        if (! is_int($ttl) || $ttl !== 3600) {
            throw new RuntimeException(
                'Vigencia JWT incorrecta.'
            );
        }

        return $ttl;
    }

    public function assertReady(): void
    {
        if (
            config('jwt.algorithm') !== self::ALGORITHM
            || config('jwt.issuer') !== 'api-usuarios'
            || config('jwt.audience') !== 'tienda-microservicios'
        ) {
            throw new RuntimeException(
                'Configuracion JWT incorrecta.'
            );
        }

        $this->ttl();

        $private = openssl_pkey_get_details(
            $this->privateKey()
        );

        $public = openssl_pkey_get_details(
            $this->publicKey()
        );

        if (
            $private === false
            || $public === false
            || $private['key'] !== $public['key']
        ) {
            throw new RuntimeException(
                'Las claves JWT no corresponden.'
            );
        }
    }

    private function validateClaims(array $claims): void
    {
        $required = [
            'sub',
            'role',
            'iss',
            'aud',
            'iat',
            'exp',
        ];

        foreach ($required as $claim) {
            if (! array_key_exists($claim, $claims)) {
                throw new UnexpectedValueException(
                    'Token invalido.'
                );
            }
        }

        if (
            $claims['iss'] !== config('jwt.issuer')
            || $claims['aud'] !== config('jwt.audience')
        ) {
            throw new UnexpectedValueException(
                'Token invalido.'
            );
        }

        if (
            ! is_string($claims['sub'])
            || ! Str::isUuid($claims['sub'], 4)
        ) {
            throw new UnexpectedValueException(
                'Token invalido.'
            );
        }

        if (! in_array($claims['role'], self::ROLES, true)) {
            throw new UnexpectedValueException(
                'Token invalido.'
            );
        }

        if (
            ! is_int($claims['iat'])
            || ! is_int($claims['exp'])
        ) {
            throw new UnexpectedValueException(
                'Token invalido.'
            );
        }

        $now = time();

        if (
            $claims['iat'] < 0
            || $claims['iat'] > $now
            || $claims['exp'] <= $now
            || $claims['exp'] <= $claims['iat']
            || $claims['exp'] - $claims['iat'] !== $this->ttl()
        ) {
            throw new UnexpectedValueException(
                'Token invalido.'
            );
        }
    }

    private function privateKey(): OpenSSLAsymmetricKey
    {
        $key = openssl_pkey_get_private(
            $this->readKey('jwt.private_key_path')
        );

        return $this->validateRsaKey($key);
    }

    private function publicKey(): OpenSSLAsymmetricKey
    {
        $key = openssl_pkey_get_public(
            $this->readKey('jwt.public_key_path')
        );

        return $this->validateRsaKey($key);
    }

    private function validateRsaKey(
        OpenSSLAsymmetricKey|false $key
    ): OpenSSLAsymmetricKey {
        if ($key === false) {
            throw new RuntimeException(
                'Clave JWT invalida.'
            );
        }

        $details = openssl_pkey_get_details($key);

        if (
            $details === false
            || $details['type'] !== OPENSSL_KEYTYPE_RSA
            || $details['bits'] < 3072
        ) {
            throw new RuntimeException(
                'Configuracion RSA invalida.'
            );
        }

        return $key;
    }

    private function readKey(string $configName): string
    {
        $path = config($configName);

        if (! is_string($path) || $path === '') {
            throw new RuntimeException(
                'Ruta de clave JWT no configurada.'
            );
        }

        $absolutePath =
            str_starts_with($path, '/')
            || str_starts_with($path, '\\')
            || preg_match('/^[A-Za-z]:[\\\\\/]/', $path) === 1;

        if (! $absolutePath) {
            $path = base_path($path);
        }

        if (! is_file($path) || ! is_readable($path)) {
            throw new RuntimeException(
                'Clave JWT no disponible.'
            );
        }

        $contents = @file_get_contents($path);

        if ($contents === false || trim($contents) === '') {
            throw new RuntimeException(
                'No se pudo cargar la clave JWT.'
            );
        }

        return $contents;
    }
}
