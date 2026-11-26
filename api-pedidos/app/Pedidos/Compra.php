<?php

namespace App\Pedidos;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

final class Compra
{
    public function __construct(private CarritoCheckout $carrito, private ServiciosCompra $servicios) {}

    public function ejecutar(string $usuarioId, string $clave, array $entrada): Pedido
    {
        // Exclusión con alcance de sesión, mientras cada paso se confirma por separado.
        $bloqueo = DB::selectOne(
            'select pg_try_advisory_lock(hashtextextended(?, 0)) as adquirido',
            [$usuarioId],
            useReadPdo: false,
        );
        if (!$bloqueo->adquirido) {
            throw new ApiError(409, 'Hay una compra en curso');
        }

        try {
            $huella = hash('sha256', json_encode($entrada, JSON_THROW_ON_ERROR));
            $pedido = Pedido::where('usuario_id', $usuarioId)->where('clave_idempotencia', $clave)->first();
            if ($pedido !== null && $pedido->huella !== $huella) {
                throw new ApiError(409, 'La clave ya se utilizó con otros datos');
            }

            if ($pedido === null) {
                if (Pedido::where('usuario_id', $usuarioId)->whereNotIn('paso', ['terminado', 'sin_stock', 'carrito_desactualizado'])->exists()) {
                    throw new ApiError(409, 'Reintenta la compra en curso con su clave anterior');
                }
                $pedido = $this->crear($usuarioId, $clave, $huella, $entrada);
            }

            return $this->continuar($pedido);
        } finally {
            DB::selectOne('select pg_advisory_unlock(hashtextextended(?, 0))', [$usuarioId], useReadPdo: false);
        }
    }

    private function crear(string $usuarioId, string $clave, string $huella, array $entrada): Pedido
    {
        $snapshot = $this->carrito->leer($usuarioId);
        if ($snapshot['items'] === []) {
            throw new ApiError(409, 'El carrito está vacío');
        }

        $subtotal = 0;
        $cantidad = 0;
        $items = [];
        foreach ($snapshot['items'] as $item) {
            $productoId = $item['producto_id'] ?? null;
            if (!is_string($productoId) || !Str::isUuid($productoId, 4)) {
                throw new ApiError(503, 'Producto inválido en el snapshot del carrito');
            }
            $producto = $this->servicios->consultar('productos', '/api/productos/'.$productoId);
            $precio = $this->centavos($producto['precio'] ?? null);
            $unidades = $item['cantidad'] ?? null;
            if (!is_int($unidades) || $unidades < 1 || $unidades > 2147483647 - $cantidad
                || $precio > intdiv(999999999999 - $subtotal, $unidades)) {
                throw new ApiError(422, 'Cantidad o importe fuera del rango admitido');
            }

            $cantidad += $unidades;
            $subtotal += $precio * $unidades;
            $items[] = [
                'producto_id' => $item['producto_id'],
                'cantidad' => $unidades,
                'precio_unitario' => $this->decimal($precio),
            ];
        }

        $envio = $this->servicios->ejecutar('envios', '/api/envios/cotizar', [
            'codigo_postal' => $entrada['direccion']['codigo_postal'],
            'cantidad' => $cantidad,
        ]);
        $costoEnvio = $this->centavos($envio['costo_envio'] ?? null);
        $total = $subtotal + $costoEnvio;
        if ($total < 1 || $total > 999999999999) {
            throw new ApiError(422, 'Importe fuera del rango admitido');
        }

        return Pedido::create([
            'id' => (string) Str::uuid(),
            'usuario_id' => $usuarioId,
            'clave_idempotencia' => $clave,
            'huella' => $huella,
            'items' => $items,
            'direccion' => $entrada['direccion'],
            'metodo_pago' => $entrada['metodo_pago'],
            'costo_envio' => $this->decimal($costoEnvio),
            'total' => $this->decimal($total),
            'estado' => 'pendiente',
            'paso' => 'por_preparar_carrito',
            'carrito_id' => $snapshot['carrito_id'],
            'carrito_version' => $snapshot['version'],
            'creado_en' => now(),
        ]);
    }

    private function continuar(Pedido $pedido): Pedido
    {
        $id = ['pedido_id' => $pedido->id];
        if ($pedido->paso === 'por_preparar_carrito') {
            try {
                $this->carrito->preparar($pedido);
            } catch (ApiError $error) {
                if ($error->status === 409) {
                    $this->avanzar($pedido, ['paso' => 'carrito_desactualizado', 'estado' => 'cancelado']);
                }
                throw $error;
            }
            $this->avanzar($pedido, ['paso' => 'por_reservar']);
        }

        if ($pedido->paso === 'carrito_desactualizado') {
            throw new ApiError(409, 'El carrito cambió antes de preparar la compra');
        }

        if ($pedido->paso === 'por_reservar') {
            $articulos = array_map(
                fn (array $item) => ['producto_id' => $item['producto_id'], 'cantidad' => $item['cantidad']],
                $pedido->items,
            );
            try {
                $reserva = $this->servicios->ejecutar('inventario', '/api/inventario/reservar', $id + ['items' => $articulos], $pedido->id);
            } catch (ApiError $error) {
                if ($error->status === 409) {
                    $this->avanzar($pedido, ['paso' => 'por_cancelar_carrito_sin_stock', 'estado' => 'cancelado']);
                }
                if ($error->status !== 409) {
                    throw $error;
                }
                $this->carrito->cancelar($pedido);
                $this->avanzar($pedido, ['paso' => 'sin_stock']);
                throw $error;
            }
            $this->comprobarResultado($reserva, $pedido->id, 'reservada');
            $this->avanzar($pedido, ['paso' => 'por_pagar']);
        }

        if ($pedido->paso === 'por_cancelar_carrito_sin_stock') {
            $this->carrito->cancelar($pedido);
            $this->avanzar($pedido, ['paso' => 'sin_stock']);
        }

        if ($pedido->paso === 'sin_stock') {
            throw new ApiError(409, 'Inventario insuficiente o reserva en conflicto');
        }

        if ($pedido->paso === 'por_pagar') {
            // El mismo ID se usa como clave estable incluso si la respuesta se pierde.
            $pago = $this->servicios->ejecutar('pagos', '/api/pagos/procesar', $id + [
                'monto' => $pedido->total,
                'metodo_pago' => $pedido->metodo_pago,
            ], $pedido->id);
            $estado = $pago['estado'] ?? null;
            if (($pago['pedido_id'] ?? null) !== $pedido->id || ($pago['monto'] ?? null) !== $pedido->total
                || !in_array($estado, ['aprobado', 'rechazado'], true)) {
                throw new ApiError(503, 'Resultado de pago incierto');
            }
            $this->avanzar($pedido, ['paso' => $estado === 'aprobado' ? 'por_confirmar_reserva' : 'por_liberar']);
        }

        if ($pedido->paso === 'por_liberar') {
            $reserva = $this->servicios->ejecutar('inventario', '/api/inventario/liberar', $id);
            $this->comprobarResultado($reserva, $pedido->id, 'liberada');
            $this->avanzar($pedido, ['paso' => 'por_cancelar_carrito_pago', 'estado' => 'cancelado']);
        }

        if ($pedido->paso === 'por_cancelar_carrito_pago') {
            $this->carrito->cancelar($pedido);
            $this->avanzar($pedido, ['paso' => 'terminado']);
        }

        if ($pedido->paso === 'por_confirmar_reserva') {
            $reserva = $this->servicios->ejecutar('inventario', '/api/inventario/confirmar', $id);
            $this->comprobarResultado($reserva, $pedido->id, 'confirmada');
            $this->avanzar($pedido, ['paso' => 'por_generar_guia', 'estado' => 'pagado']);
        }

        if ($pedido->paso === 'por_generar_guia') {
            $envio = $this->servicios->ejecutar('envios', '/api/envios/generar', $id + [
                'direccion' => $pedido->direccion,
            ], $pedido->id);
            if (($envio['pedido_id'] ?? null) !== $pedido->id || !is_string($envio['guia'] ?? null)) {
                throw new ApiError(503, 'Resultado de envío incierto');
            }
            $this->avanzar($pedido, ['paso' => 'por_confirmar_carrito', 'guia' => $envio['guia']]);
        }

        if ($pedido->paso === 'por_confirmar_carrito') {
            $this->carrito->confirmar($pedido);
            $this->avanzar($pedido, ['paso' => 'terminado']);
        }

        return $pedido;
    }

    private function avanzar(Pedido $pedido, array $cambios): void
    {
        $actualizados = Pedido::whereKey($pedido->id)
            ->where('paso', $pedido->paso)
            ->update($cambios);

        if ($actualizados !== 1) {
            throw new ApiError(409, 'La compra avanzó en otro proceso. Reintenta con la misma clave');
        }
        $pedido->forceFill($cambios);
    }

    private function comprobarResultado(array $datos, string $pedidoId, string $estado): void
    {
        if (($datos['estado'] ?? null) !== $estado || ($datos['pedido_id'] ?? null) !== $pedidoId) {
            throw new ApiError(503, 'Resultado de inventario incierto');
        }
    }

    private function centavos(mixed $importe): int
    {
        if (!is_string($importe) || !preg_match('/^\d{1,10}\.\d{2}$/D', $importe)) {
            throw new ApiError(503, 'Importe inválido de la dependencia');
        }

        return (int) str_replace('.', '', $importe);
    }

    private function decimal(int $centavos): string
    {
        return sprintf('%d.%02d', intdiv($centavos, 100), $centavos % 100);
    }
}
