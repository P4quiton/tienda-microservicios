<?php

namespace App\Pedidos;

use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\RateLimiter;
use Symfony\Component\HttpFoundation\Response;

/**
 * Rate limiting por identidad. Primero se identifica (JWT válido o X-Service-Token válido); lo que no
 * se pueda autenticar se limita por IP y el controlador sigue respondiendo 401. Cada petición cuenta
 * una vez (incluida una repetición con la misma Idempotency-Key) y el 429 se emite antes de cualquier
 * efecto, así que nunca deja pedidos a medias. Ventana fija de 60 s en la caché del proceso: con varias
 * réplicas el límite es por instancia. /health y /ready están exentos.
 */
final class LimitarSolicitudes
{
    private const VENTANA = 60;

    public function __construct(private Identidad $identidad) {}

    public function handle(Request $request, Closure $next): Response
    {
        if ($request->is('health', 'ready')) {
            return $next($request);
        }

        [$cubo, $identidad] = $this->clasificar($request);
        $clave = "pedidos:limite:$cubo:$identidad";
        $maximo = (int) config("pedidos.limites.$cubo");

        if (RateLimiter::tooManyAttempts($clave, $maximo)) {
            return response()->json([
                'success' => false,
                'message' => 'Demasiadas solicitudes',
                'errors' => (object) [],
            ], 429, ['Retry-After' => max(1, RateLimiter::availableIn($clave))]);
        }
        RateLimiter::hit($clave, self::VENTANA);

        return $next($request);
    }

    /** @return array{0: string, 1: string} cubo de límite e identidad */
    private function clasificar(Request $request): array
    {
        $lectura = in_array($request->method(), ['GET', 'HEAD', 'OPTIONS'], true);

        $servicio = $this->identidad->nombreServicio($request);
        if ($servicio !== null) {
            return ['interna', "servicio:$servicio"];
        }

        $usuario = $this->identidad->usuarioOrNull($request);
        if ($usuario !== null) {
            if ($lectura) {
                return ['consulta', $usuario['id']];
            }

            return [$request->isMethod('POST') && $request->is('api/pedidos') ? 'checkout' : 'mutacion', $usuario['id']];
        }

        return [$lectura ? 'consulta' : 'mutacion', 'ip:'.$request->ip()];
    }
}
