<?php

namespace App\Pedidos;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

final class ServiciosCompra
{
    public function consultar(string $servicio, string $ruta): array
    {
        return $this->enviar($servicio, 'GET', $ruta);
    }

    public function ejecutar(string $servicio, string $ruta, array $cuerpo, ?string $clave = null): array
    {
        return $this->enviar($servicio, 'POST', $ruta, $cuerpo, $clave);
    }

    private function enviar(string $servicio, string $metodo, string $ruta, array $cuerpo = [], ?string $clave = null): array
    {
        $cliente = Http::acceptJson()->connectTimeout(2)->timeout(5)->withoutRedirecting();
        if ($servicio !== 'productos') {
            $token = config("pedidos.tokens_salientes.$servicio");
            if (!is_string($token) || $token === '') {
                throw new ApiError(503, 'Dependencia no disponible');
            }
            $cliente->withHeader('X-Service-Token', $token);
        }
        if ($clave !== null) {
            $cliente->withHeader('Idempotency-Key', $clave);
        }

        try {
            $opciones = $metodo === 'POST' ? ['json' => $cuerpo] : [];
            $respuesta = $cliente->send($metodo, rtrim(config("pedidos.urls.$servicio"), '/').$ruta, $opciones);
        } catch (ConnectionException) {
            Log::warning('Fallo de conexión a dependencia', ['servicio' => $servicio, 'metodo' => $metodo, 'status' => null]);
            throw new ApiError(503, 'Resultado de dependencia incierto');
        }

        if (($servicio === 'inventario' && $ruta === '/api/inventario/reservar'
            || $servicio === 'carrito' && str_ends_with($ruta, '/preparar')) && $respuesta->conflict()) {
            throw new ApiError(409, 'Conflicto al preparar la compra');
        }

        $datos = $respuesta->json('data');
        if (!$respuesta->successful() || $respuesta->json('success') !== true || !is_array($datos)) {
            Log::warning('Respuesta inválida de dependencia', ['servicio' => $servicio, 'metodo' => $metodo, 'status' => $respuesta->status()]);
            throw new ApiError(503, 'Dependencia no disponible o resultado incierto');
        }

        return $datos;
    }
}
