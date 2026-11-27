<?php

namespace Tests\Feature;

use PHPUnit\Framework\Attributes\BackupGlobals;
use Tests\TestCase;

final class CorsTest extends TestCase
{
    #[BackupGlobals(true)]
    public function test_cors_aplica_los_origenes_explicitos_del_entorno(): void
    {
        $_SERVER['CORS_ALLOWED_ORIGINS'] = $_ENV['CORS_ALLOWED_ORIGINS'] =
            ' https://tienda.example.test, http://localhost:4200, *, https://*.externo.test, ';
        $this->refreshApplication();

        foreach (['https://tienda.example.test', 'http://localhost:4200'] as $origen) {
            $respuesta = $this->options('/api/pedidos', [], [
                'Origin' => $origen,
                'Access-Control-Request-Method' => 'POST',
                'Access-Control-Request-Headers' => 'Authorization, Content-Type, Idempotency-Key',
            ])->assertNoContent()
                ->assertHeader('Access-Control-Allow-Origin', $origen)
                ->assertHeaderMissing('Access-Control-Allow-Credentials');
            $cabeceras = explode(', ', strtolower($respuesta->headers->get('Access-Control-Allow-Headers', '')));
            foreach (['authorization', 'content-type', 'idempotency-key'] as $cabecera) {
                $this->assertContains($cabecera, $cabeceras);
            }
        }

        foreach (['https://externo.test', 'https://subdominio.externo.test'] as $origen) {
            $this->options('/api/pedidos', [], [
                'Origin' => $origen,
                'Access-Control-Request-Method' => 'POST',
            ])->assertHeaderMissing('Access-Control-Allow-Origin');
        }

        $this->getJson('/api/pedidos/00000000-0000-4000-8000-000000000001', [
            'Origin' => 'https://tienda.example.test',
        ])->assertUnauthorized()->assertHeader('Access-Control-Allow-Origin', 'https://tienda.example.test');
    }

    #[BackupGlobals(true)]
    public function test_comodin_asterisco_no_permite_ningun_origen(): void
    {
        $_SERVER['CORS_ALLOWED_ORIGINS'] = $_ENV['CORS_ALLOWED_ORIGINS'] = '*';
        $this->refreshApplication();

        $this->options('/api/pedidos', [], [
            'Origin' => 'https://cualquiera.example',
            'Access-Control-Request-Method' => 'POST',
        ])->assertHeaderMissing('Access-Control-Allow-Origin');

        $this->getJson('/api/pedidos/00000000-0000-4000-8000-000000000001', [
            'Origin' => 'https://cualquiera.example',
        ])->assertUnauthorized()->assertHeaderMissing('Access-Control-Allow-Origin');
    }

    #[BackupGlobals(true)]
    public function test_un_unico_origen_permitido_no_se_refleja_a_origenes_ajenos(): void
    {
        $_SERVER['CORS_ALLOWED_ORIGINS'] = $_ENV['CORS_ALLOWED_ORIGINS'] = 'http://localhost:4200';
        $this->refreshApplication();

        $this->options('/api/pedidos', [], [
            'Origin' => 'http://localhost:4200',
            'Access-Control-Request-Method' => 'POST',
        ])->assertNoContent()->assertHeader('Access-Control-Allow-Origin', 'http://localhost:4200');

        $this->options('/api/pedidos', [], [
            'Origin' => 'https://externo.test',
            'Access-Control-Request-Method' => 'POST',
        ])->assertNoContent()->assertHeaderMissing('Access-Control-Allow-Origin');

        $this->getJson('/api/pedidos/00000000-0000-4000-8000-000000000001', [
            'Origin' => 'https://externo.test',
        ])->assertUnauthorized()->assertHeaderMissing('Access-Control-Allow-Origin');
    }

    #[BackupGlobals(true)]
    public function test_sin_variable_de_entorno_no_se_permite_ningun_origen_cruzado(): void
    {
        $_SERVER['CORS_ALLOWED_ORIGINS'] = $_ENV['CORS_ALLOWED_ORIGINS'] = '';
        $this->refreshApplication();

        $this->options('/api/pedidos', [], [
            'Origin' => 'http://localhost:4200',
            'Access-Control-Request-Method' => 'POST',
        ])->assertHeaderMissing('Access-Control-Allow-Origin');
    }
}
