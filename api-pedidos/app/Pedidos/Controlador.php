<?php

namespace App\Pedidos;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use JsonException;

final class Controlador
{
    /** Tope del cuerpo JSON en bytes: el contrato solo admite una dirección y un método de pago. */
    private const MAX_CUERPO = 16384;

    /** Tope de caracteres por campo de dirección. */
    private const MAX_CAMPO = 200;

    public function __construct(private Identidad $identidad) {}

    public function crear(Request $request, Compra $compra): JsonResponse
    {
        $usuario = $this->identidad->usuario($request);
        $clave = $this->uuid($request->header('Idempotency-Key'), 'Idempotency-Key');
        $datos = $this->json($request);
        $direccion = $datos['direccion'] ?? null;
        $metodo = $datos['metodo_pago'] ?? null;

        if (array_diff(array_keys($datos), ['direccion', 'metodo_pago'])
            || !is_array($direccion)
            || !in_array($metodo, ['tarjeta_simulada', 'transferencia_simulada'], true)) {
            throw new ApiError(422, 'Dirección o método de pago inválido');
        }

        $campos = ['codigo_postal', 'calle', 'ciudad', 'estado'];
        if (array_diff(array_keys($direccion), $campos)) {
            throw new ApiError(422, 'Dirección inválida');
        }
        $direccionOrdenada = [];
        foreach ($campos as $campo) {
            $valor = $direccion[$campo] ?? null;
            // Sin caracteres de control (p. ej. NUL, que jsonb no admite) ni longitudes abusivas.
            if (!is_string($valor) || trim($valor) === '' || mb_strlen($valor) > self::MAX_CAMPO
                || preg_match('/[\p{Cc}\p{Zl}\p{Zp}]/u', $valor)
                || ($campo === 'codigo_postal' && !preg_match('/^[0-9]{5}$/D', $valor))) {
                throw new ApiError(422, 'Dirección inválida', [$campo => ['Campo inválido']]);
            }
            $direccionOrdenada[$campo] = $valor;
        }

        $pedido = $compra->ejecutar($usuario['id'], $clave, [
            'direccion' => $direccionOrdenada,
            'metodo_pago' => $metodo,
        ]);

        return $this->respuesta($pedido->respuesta(), 201);
    }

    public function historial(Request $request, string $usuario_id): JsonResponse
    {
        $usuario = $this->identidad->usuario($request);
        $titular = $this->uuid($usuario_id, 'usuario_id');
        $this->identidad->comprobarTitular($usuario, $titular);

        return $this->respuesta(Pedido::where('usuario_id', $titular)
            ->orderByDesc('creado_en')
            ->get()
            ->map(fn (Pedido $pedido) => $pedido->respuesta())
            ->all());
    }

    public function consultar(Request $request, string $id): JsonResponse
    {
        $usuario = null;
        if ($request->hasHeader('X-Service-Token')) {
            $this->identidad->servicio($request, ['pagos', 'envios']);
        } else {
            $usuario = $this->identidad->usuario($request);
        }

        $pedido = Pedido::find($this->uuid($id, 'id'));
        if ($pedido === null) {
            throw new ApiError(404, 'Pedido no encontrado');
        }
        if ($usuario !== null) {
            $this->identidad->comprobarTitular($usuario, $pedido->usuario_id);
        }

        return $this->respuesta($pedido->respuesta());
    }

    /**
     * PATCH /api/pedidos/{id}/estado: exclusivo de Envíos (SERVICE_TOKEN_ENVIOS_PEDIDOS), solo pagado -> enviado.
     * Orden: credencial (401/403), Idempotency-Key y cuerpo (422), pedido (404), transición (409).
     * Repetir "enviado" sobre un pedido ya enviado es idempotente (200). La clave se registra solo si la
     * operación se resuelve, de modo que Envíos puede reintentar la misma clave tras un 409 transitorio.
     */
    public function cambiarEstado(Request $request, string $id): JsonResponse
    {
        $this->identidad->servicio($request, ['envios']);
        $clave = $this->uuid($request->header('Idempotency-Key'), 'Idempotency-Key');
        $pedidoId = $this->uuid($id, 'id');
        $datos = $this->json($request);
        $estado = $datos['estado'] ?? null;
        if (array_diff(array_keys($datos), ['estado']) || !is_string($estado)
            || !in_array($estado, ['pendiente', 'pagado', 'enviado', 'cancelado'], true)) {
            throw new ApiError(422, 'Estado inválido', ['estado' => ['Se esperaba un estado conocido']]);
        }

        $pedido = DB::transaction(function () use ($clave, $pedidoId, $estado) {
            $pedido = Pedido::whereKey($pedidoId)->lockForUpdate()->first();
            if ($pedido === null) {
                throw new ApiError(404, 'Pedido no encontrado');
            }
            $previo = DB::table('pedidos_cambios_estado')->where('clave', $clave)->first();
            if ($previo !== null) {
                if ($previo->pedido_id !== $pedidoId || $previo->estado !== $estado) {
                    throw new ApiError(409, 'La clave ya se utilizó con otros datos');
                }

                return $pedido;
            }
            if ($estado !== 'enviado' || !in_array($pedido->estado, ['pagado', 'enviado'], true)) {
                throw new ApiError(409, 'Transición de estado no permitida');
            }
            if ($pedido->estado === 'pagado') {
                $pedido->estado = 'enviado';
                $pedido->save();
            }
            DB::table('pedidos_cambios_estado')->insert(['clave' => $clave, 'pedido_id' => $pedidoId, 'estado' => $estado, 'creado_en' => now()]);

            return $pedido;
        });

        return $this->respuesta($pedido->respuesta());
    }

    private function json(Request $request): array
    {
        if ((int) $request->header('Content-Length', 0) > self::MAX_CUERPO
            || strlen($request->getContent()) > self::MAX_CUERPO) {
            throw new ApiError(422, 'Cuerpo demasiado grande');
        }

        try {
            $datos = json_decode($request->getContent(), true, flags: JSON_THROW_ON_ERROR);
        } catch (JsonException) {
            throw new ApiError(400, 'JSON incorrecto');
        }

        if (!is_array($datos)) {
            throw new ApiError(422, 'Se esperaba un objeto JSON');
        }

        return $datos;
    }

    private function uuid(?string $valor, string $campo): string
    {
        if ($valor === null || !Str::isUuid($valor, 4)) {
            throw new ApiError(422, 'Identificador inválido', [$campo => ['Se requiere UUID v4']]);
        }

        return strtolower($valor);
    }

    private function respuesta(array $datos, int $status = 200): JsonResponse
    {
        return response()->json(['success' => true, 'message' => 'OK', 'data' => $datos], $status);
    }
}
