<?php

namespace Tests\Feature;

use Illuminate\Support\Facades\Artisan;
use PHPUnit\Framework\Attributes\BackupGlobals;
use Tests\TestCase;

final class CorsTest extends TestCase
{
    private const ORIGEN_PERMITIDO = 'https://tienda.example.test';

    #[BackupGlobals(true)]
    public function test_cors_aplica_solo_los_origenes_explicitos_del_entorno(): void
    {
        $this->fijarOrigenesPermitidos(' https://tienda.example.test, http://localhost:4200, *, https://*.externo.test, ');

        foreach (['https://tienda.example.test', 'http://localhost:4200'] as $origen) {
            $respuesta = $this->options('/api/productos', [], [
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

        foreach (['https://externo.test', 'https://subdominio.externo.test', 'https://cualquiera.example'] as $origen) {
            $this->options('/api/productos', [], [
                'Origin' => $origen,
                'Access-Control-Request-Method' => 'POST',
            ])->assertHeaderMissing('Access-Control-Allow-Origin');
        }

        $this->getJson('/api/productos', ['Origin' => self::ORIGEN_PERMITIDO])
            ->assertOk()
            ->assertHeader('Access-Control-Allow-Origin', self::ORIGEN_PERMITIDO);
    }

    #[BackupGlobals(true)]
    public function test_comodin_asterisco_no_permite_ningun_origen(): void
    {
        $this->fijarOrigenesPermitidos('*');

        $this->options('/api/productos', [], [
            'Origin' => 'https://cualquiera.example',
            'Access-Control-Request-Method' => 'GET',
        ])->assertHeaderMissing('Access-Control-Allow-Origin');

        $this->getJson('/api/productos', ['Origin' => 'https://cualquiera.example'])
            ->assertOk()
            ->assertHeaderMissing('Access-Control-Allow-Origin');
    }

    #[BackupGlobals(true)]
    public function test_un_unico_origen_permitido_no_se_refleja_a_origenes_ajenos(): void
    {
        $this->fijarOrigenesPermitidos('http://localhost:4200');

        $this->options('/api/productos', [], [
            'Origin' => 'http://localhost:4200',
            'Access-Control-Request-Method' => 'POST',
        ])->assertNoContent()->assertHeader('Access-Control-Allow-Origin', 'http://localhost:4200');

        $this->options('/api/productos', [], [
            'Origin' => 'https://externo.test',
            'Access-Control-Request-Method' => 'POST',
        ])->assertNoContent()->assertHeaderMissing('Access-Control-Allow-Origin');

        $this->getJson('/api/productos', ['Origin' => 'https://externo.test'])
            ->assertOk()
            ->assertHeaderMissing('Access-Control-Allow-Origin');
    }

    #[BackupGlobals(true)]
    public function test_sin_variable_de_entorno_no_se_permite_ningun_origen_cruzado(): void
    {
        $this->fijarOrigenesPermitidos('');

        $this->options('/api/productos', [], [
            'Origin' => 'http://localhost:4200',
            'Access-Control-Request-Method' => 'GET',
        ])->assertHeaderMissing('Access-Control-Allow-Origin');

        $this->getJson('/api/productos', ['Origin' => 'http://localhost:4200'])
            ->assertOk()
            ->assertHeaderMissing('Access-Control-Allow-Origin');
    }

    private function fijarOrigenesPermitidos(string $valor): void
    {
        $_SERVER['CORS_ALLOWED_ORIGINS'] = $_ENV['CORS_ALLOWED_ORIGINS'] = $valor;
        // Una aplicación nueva usa otra base SQLite en memoria: hay que migrar de nuevo.
        $this->refreshApplication();
        $this->assertSame(0, Artisan::call('migrate'));
    }
}
