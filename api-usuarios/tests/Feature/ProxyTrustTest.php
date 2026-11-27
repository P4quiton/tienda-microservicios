<?php

declare(strict_types=1);

namespace Tests\Feature;

use Tests\TestCase;

// Frontera de confianza de X-Forwarded-For (TRUSTED_PROXIES). El login admite 5 intentos por minuto y por IP;
// cada intento usa un correo distinto para que solo cuente el cupo por IP.
class ProxyTrustTest extends TestCase
{
    private const LOGIN_LIMIT = 5;

    protected function tearDown(): void
    {
        putenv('TRUSTED_PROXIES');

        parent::tearDown();
    }

    public function test_direct_client_cannot_bypass_login_limit_with_forged_forwarded_for(): void
    {
        $this->arrancarCon(null);

        $codigos = $this->intentosLogin(
            fn (int $n): string => '198.51.100.'.$n,
            self::LOGIN_LIMIT + 1,
        );

        $this->assertBloqueoDesde($codigos, self::LOGIN_LIMIT + 1);
    }

    public function test_trusted_proxy_uses_forwarded_client_ip(): void
    {
        $this->arrancarCon('127.0.0.1');

        $codigos = $this->intentosLogin(
            fn (int $n): string => '198.51.100.'.$n,
            self::LOGIN_LIMIT + 1,
        );

        $this->assertSame([], array_filter($codigos, static fn (int $c): bool => $c === 429));
    }

    public function test_trusted_proxy_still_limits_the_same_forwarded_client_ip(): void
    {
        $this->arrancarCon('127.0.0.1');

        $codigos = $this->intentosLogin(
            fn (int $n): string => '198.51.100.7',
            self::LOGIN_LIMIT + 1,
        );

        $this->assertBloqueoDesde($codigos, self::LOGIN_LIMIT + 1);
    }

    public function test_proxy_not_listed_in_trusted_proxies_is_not_trusted(): void
    {
        $this->arrancarCon('10.99.0.0/16');

        $codigos = $this->intentosLogin(
            fn (int $n): string => '198.51.100.'.$n,
            self::LOGIN_LIMIT + 1,
        );

        $this->assertBloqueoDesde($codigos, self::LOGIN_LIMIT + 1);
    }

    // Los valores inválidos se descartan: si no queda ninguna entrada válida, no se confía en nadie.
    public function test_invalid_trusted_proxy_values_trust_nobody(): void
    {
        foreach (['*', '0.0.0.0/0', '::/0', 'loopback'] as $valor) {
            $this->arrancarCon($valor);

            $codigos = $this->intentosLogin(
                fn (int $n): string => '198.51.100.'.$n,
                self::LOGIN_LIMIT + 1,
            );

            $this->assertBloqueoDesde($codigos, self::LOGIN_LIMIT + 1);
        }
    }

    // Arranca la aplicación con TRUSTED_PROXIES del entorno del proceso (null = variable ausente).
    private function arrancarCon(?string $trustedProxies): void
    {
        if ($trustedProxies === null) {
            putenv('TRUSTED_PROXIES');
        } else {
            putenv('TRUSTED_PROXIES='.$trustedProxies);
        }

        $this->refreshApplication();
    }

    /**
     * @param  callable(int): string  $forwardedFor
     * @return list<int>
     */
    private function intentosLogin(callable $forwardedFor, int $intentos): array
    {
        $codigos = [];

        for ($n = 1; $n <= $intentos; $n++) {
            $codigos[] = $this->withHeader('X-Forwarded-For', $forwardedFor($n))
                ->postJson('/api/usuarios/login', [
                    'correo' => 'persona'.$n.'@example.test',
                    'contrasena' => 'clave-incorrecta-de-prueba',
                ])
                ->status();
        }

        return $codigos;
    }

    /** @param list<int> $codigos */
    private function assertBloqueoDesde(array $codigos, int $intento): void
    {
        $esperados = [];

        foreach (array_keys($codigos) as $indice) {
            $esperados[] = $indice + 1 >= $intento;
        }

        $this->assertSame(
            $esperados,
            array_map(static fn (int $c): bool => $c === 429, $codigos),
            'Códigos recibidos: '.implode(',', $codigos),
        );
    }
}
