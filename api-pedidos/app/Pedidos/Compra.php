<?php

namespace App\Pedidos;

use Illuminate\Database\UniqueConstraintViolationException;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Str;
use Throwable;

/**
 * Saga de checkout coordinada por Pedidos (docs/flujo-compra.md, contrato 1.1.0).
 *
 * Origen: POST /api/pedidos (ejecutar) y el comando pedidos:recuperar (recuperar).
 * Transformación: máquina de pasos persistida en PostgreSQL. Cada paso guarda su resultado ANTES de
 * pasar al siguiente (avanzar) y las llamadas externas usan Pedido::clave(), estable entre reintentos.
 * Destino: Carrito, Productos, Inventario, Pagos y Envíos (HTTP) y la tabla pedidos.
 *
 * Pasos: por_iniciar_carrito -> por_cotizar -> por_reservar -> por_pagar
 *   aprobado:  por_confirmar_reserva -> por_generar_guia -> por_finalizar_carrito -> terminado
 *   rechazado: por_liberar_reserva -> por_liberar_carrito_pago -> terminado (estado cancelado)
 *   sin stock: por_liberar_carrito_sin_stock -> sin_stock; importes fuera de rango: ... -> rango_invalido
 *   carrito cambiado al iniciar: carrito_desactualizado.
 * Regla: tras un cobro aprobado el pedido nunca se cancela; los fallos quedan pendientes (503) y se reanudan.
 * Un resultado incierto nunca se interpreta como rechazo ni libera recursos.
 */
final class Compra
{
    /** Techo de espera entre reintentos automáticos, en segundos. */
    private const ESPERA_MAXIMA = 300;

    public function __construct(private CarritoHttp $carrito, private ServiciosCompra $servicios) {}

    public function ejecutar(string $usuarioId, string $clave, array $entrada): Pedido
    {
        if (!$this->bloquear($usuarioId)) {
            throw new ApiError(409, 'Hay una compra en curso');
        }

        try {
            $huella = hash('sha256', json_encode($entrada, JSON_THROW_ON_ERROR));
            $pedido = Pedido::where('usuario_id', $usuarioId)->where('clave_idempotencia', $clave)->first();
            if ($pedido !== null && $pedido->huella !== $huella) {
                throw new ApiError(409, 'La clave ya se utilizó con otros datos');
            }

            if ($pedido === null) {
                if (Pedido::where('usuario_id', $usuarioId)->whereNotIn('paso', Pedido::TERMINALES)->exists()) {
                    throw new ApiError(409, 'Reintenta la compra en curso con su clave anterior');
                }
                $pedido = $this->crear($usuarioId, $clave, $huella, $entrada);
            }

            return $this->reanudar($pedido);
        } finally {
            $this->desbloquear($usuarioId);
        }
    }

    /**
     * Reanuda un pedido pendiente sin petición del cliente. Respeta el próximo intento programado.
     *
     * @return 'completado'|'pendiente'|'ocupado'|'omitido'
     */
    public function recuperar(string $pedidoId, bool $ignorarEspera = false): string
    {
        $pedido = Pedido::find($pedidoId);
        if ($pedido === null || in_array($pedido->paso, Pedido::TERMINALES, true)) {
            return 'omitido';
        }
        $usuarioId = $pedido->usuario_id;
        if (!$this->bloquear($usuarioId)) {
            return 'ocupado';
        }

        try {
            $pedido = Pedido::find($pedidoId); // estado leído ya con el bloqueo
            if ($pedido === null || in_array($pedido->paso, Pedido::TERMINALES, true)) {
                return 'omitido';
            }
            if (!$ignorarEspera && $pedido->proximo_intento !== null && $pedido->proximo_intento->isFuture()) {
                return 'omitido';
            }
            try {
                $this->reanudar($pedido);
            } catch (ApiError) {
                // Ya quedó registrado en el pedido (intentos, próximo intento, último error).
            }

            return in_array($pedido->paso, Pedido::TERMINALES, true) ? 'completado' : 'pendiente';
        } finally {
            $this->desbloquear($usuarioId);
        }
    }

    /** Exclusión por usuario con alcance de sesión, mientras cada paso se confirma por separado. */
    private function bloquear(string $usuarioId): bool
    {
        return (bool) DB::selectOne(
            'select pg_try_advisory_lock(hashtextextended(?, 0)) as adquirido',
            [$usuarioId],
            useReadPdo: false,
        )->adquirido;
    }

    private function desbloquear(string $usuarioId): void
    {
        DB::selectOne('select pg_advisory_unlock(hashtextextended(?, 0))', [$usuarioId], useReadPdo: false);
    }

    /**
     * Lee el carrito (sin efectos) y persiste el pedido pendiente con su clave y la versión observada,
     * antes de iniciar el checkout del carrito o invocar cualquier otro efecto externo.
     */
    private function crear(string $usuarioId, string $clave, string $huella, array $entrada): Pedido
    {
        $lectura = $this->carrito->leer($usuarioId);
        if ($lectura['items'] === []) {
            throw new ApiError(409, 'El carrito está vacío');
        }

        try {
            return Pedido::create([
                'id' => (string) Str::uuid(),
                'usuario_id' => $usuarioId,
                'clave_idempotencia' => $clave,
                'huella' => $huella,
                'direccion' => $entrada['direccion'],
                'metodo_pago' => $entrada['metodo_pago'],
                'estado' => 'pendiente',
                'paso' => 'por_iniciar_carrito',
                'carrito_id' => $lectura['carrito_id'],
                'carrito_version' => (string) $lectura['version'],
                'creado_en' => now(),
            ]);
        } catch (UniqueConstraintViolationException) {
            throw new ApiError(409, 'Reintenta la compra en curso con su clave anterior');
        }
    }

    /** Ejecuta los pasos pendientes y registra el fallo (intentos, backoff, último error) si algo queda incierto. */
    private function reanudar(Pedido $pedido): Pedido
    {
        try {
            return $this->continuar($pedido);
        } catch (ApiError $error) {
            if ($error->status >= 500) {
                $this->registrarFallo($pedido, $error->getMessage());
            }
            throw $error;
        } catch (Throwable $error) {
            $this->registrarFallo($pedido, 'Error interno');
            throw $error;
        }
    }

    private function continuar(Pedido $pedido): Pedido
    {
        if ($pedido->paso === 'por_iniciar_carrito') {
            try {
                $snapshot = $this->carrito->iniciar($pedido);
            } catch (ApiError $error) {
                if ($error->status === 409) {
                    // Carrito cambiado u otro checkout activo: cancelar sin cobrar ni reservar.
                    $this->avanzar($pedido, ['paso' => 'carrito_desactualizado', 'estado' => 'cancelado']);
                }
                throw $error;
            }
            $this->avanzar($pedido, ['paso' => 'por_cotizar', 'snapshot' => $snapshot]);
        }

        if ($pedido->paso === 'carrito_desactualizado') {
            throw new ApiError(409, 'El carrito cambió antes de iniciar la compra');
        }

        if ($pedido->paso === 'por_cotizar') {
            try {
                $importes = $this->calcular($pedido);
            } catch (ApiError $error) {
                if ($error->status !== 422) {
                    throw $error;
                }
                $this->avanzar($pedido, ['paso' => 'por_liberar_carrito_rango', 'estado' => 'cancelado']);
            }
            if (isset($importes)) {
                $this->avanzar($pedido, $importes + ['paso' => 'por_reservar']);
            }
        }

        if ($pedido->paso === 'por_liberar_carrito_rango') {
            $this->carrito->liberar($pedido);
            $this->avanzar($pedido, ['paso' => 'rango_invalido']);
        }

        if ($pedido->paso === 'rango_invalido') {
            throw new ApiError(422, 'Cantidad o importe fuera del rango admitido');
        }

        if ($pedido->paso === 'por_reservar') {
            $articulos = array_map(
                fn (array $item) => ['producto_id' => $item['producto_id'], 'cantidad' => $item['cantidad']],
                $pedido->items,
            );
            try {
                $reserva = $this->servicios->ejecutar('inventario', '/api/inventario/reservar',
                    ['pedido_id' => $pedido->id, 'items' => $articulos], $pedido->clave('reservar'));
            } catch (ApiError $error) {
                if ($error->status === 409) {
                    $this->avanzar($pedido, ['paso' => 'por_liberar_carrito_sin_stock', 'estado' => 'cancelado']);
                } else {
                    throw $error;
                }
            }
            if ($pedido->paso === 'por_reservar') {
                $this->comprobarReserva($reserva, $pedido->id, 'reservada');
                $this->avanzar($pedido, ['paso' => 'por_pagar']);
            }
        }

        if ($pedido->paso === 'por_liberar_carrito_sin_stock') {
            $this->carrito->liberar($pedido);
            $this->avanzar($pedido, ['paso' => 'sin_stock']);
        }

        if ($pedido->paso === 'sin_stock') {
            throw new ApiError(409, 'Inventario insuficiente o reserva en conflicto');
        }

        if ($pedido->paso === 'por_pagar') {
            // Paso persistido = intención de pago; la clave (id del pedido) es estable aunque se pierda la respuesta.
            $pago = $this->resolverPago($pedido);
            if ($pago['estado'] === 'aprobado') {
                // Desde aquí el pedido está cobrado: nunca se cancela.
                $this->avanzar($pedido, ['paso' => 'por_confirmar_reserva', 'estado' => 'pagado']);
            } else {
                $this->avanzar($pedido, ['paso' => 'por_liberar_reserva', 'estado' => 'cancelado']);
            }
        }

        if ($pedido->paso === 'por_liberar_reserva') {
            $reserva = $this->servicios->ejecutar('inventario', '/api/inventario/liberar',
                ['pedido_id' => $pedido->id], $pedido->clave('liberar'));
            $this->comprobarReserva($reserva, $pedido->id, 'liberada');
            $this->avanzar($pedido, ['paso' => 'por_liberar_carrito_pago']);
        }

        if ($pedido->paso === 'por_liberar_carrito_pago') {
            $this->carrito->liberar($pedido);
            $this->avanzar($pedido, ['paso' => 'terminado']);
        }

        if ($pedido->paso === 'por_confirmar_reserva') {
            $reserva = $this->servicios->ejecutar('inventario', '/api/inventario/confirmar',
                ['pedido_id' => $pedido->id], $pedido->clave('confirmar'));
            $this->comprobarReserva($reserva, $pedido->id, 'confirmada');
            $this->avanzar($pedido, ['paso' => 'por_generar_guia']);
        }

        if ($pedido->paso === 'por_generar_guia') {
            $envio = $this->servicios->ejecutar('envios', '/api/envios/generar', [
                'pedido_id' => $pedido->id,
                'direccion' => $pedido->direccion,
            ], $pedido->clave('generar'));
            if (($envio['pedido_id'] ?? null) !== $pedido->id || !is_string($envio['guia'] ?? null)) {
                throw new ApiError(503, 'Resultado de envío incierto');
            }
            $this->avanzar($pedido, ['paso' => 'por_finalizar_carrito', 'guia' => $envio['guia']]);
        }

        if ($pedido->paso === 'por_finalizar_carrito') {
            $this->carrito->finalizar($pedido);
            $this->avanzar($pedido, ['paso' => 'terminado']);
        }

        return $pedido;
    }

    /**
     * Recalcula importes con Productos y Envíos a partir del snapshot (agrupado por producto).
     * Importes fuera de rango => 422 (cancelación definitiva); dependencias caídas => 503 (reintento).
     */
    private function calcular(Pedido $pedido): array
    {
        $porProducto = [];
        $cantidad = 0;
        foreach ($pedido->snapshot as $linea) {
            if ($linea['cantidad'] > 2147483647 - $cantidad) {
                throw new ApiError(422, 'Cantidad o importe fuera del rango admitido');
            }
            $cantidad += $linea['cantidad'];
            $porProducto[$linea['producto_id']] = ($porProducto[$linea['producto_id']] ?? 0) + $linea['cantidad'];
        }

        $subtotal = 0;
        $items = [];
        foreach ($porProducto as $productoId => $unidades) {
            $producto = $this->servicios->consultar('productos', '/api/productos/'.$productoId);
            $precio = $this->centavos($producto['precio'] ?? null);
            if ($precio > intdiv(999999999999 - $subtotal, $unidades)) {
                throw new ApiError(422, 'Cantidad o importe fuera del rango admitido');
            }
            $subtotal += $precio * $unidades;
            $items[] = ['producto_id' => $productoId, 'cantidad' => $unidades, 'precio_unitario' => $this->decimal($precio)];
        }

        $envio = $this->servicios->ejecutar('envios', '/api/envios/cotizar', [
            'codigo_postal' => $pedido->direccion['codigo_postal'],
            'cantidad' => $cantidad,
        ]);
        $costoEnvio = $this->centavos($envio['costo_envio'] ?? null);
        $total = $subtotal + $costoEnvio;
        if ($total < 1 || $total > 999999999999) {
            throw new ApiError(422, 'Importe fuera del rango admitido');
        }

        return ['items' => $items, 'costo_envio' => $this->decimal($costoEnvio), 'total' => $this->decimal($total)];
    }

    /**
     * Procesa el pago con clave estable. Ante un resultado ambiguo consulta GET /api/pagos/pedido/{id};
     * si tampoco hay comprobante, se conserva 503 (404 no prueba que no haya operación en curso) y se
     * reintenta después con la misma clave y payload. Jamás se asume rechazo.
     *
     * @return array{estado: string}
     */
    private function resolverPago(Pedido $pedido): array
    {
        try {
            $pago = $this->servicios->ejecutar('pagos', '/api/pagos/procesar', [
                'pedido_id' => $pedido->id,
                'monto' => $pedido->total,
                'metodo_pago' => $pedido->metodo_pago,
            ], $pedido->clave('pagar'));

            return $this->pagoValido($pago, $pedido);
        } catch (ApiError $error) {
            if ($error->status !== 503) {
                throw $error;
            }
            try {
                $comprobante = $this->servicios->consultar('pagos', '/api/pagos/pedido/'.$pedido->id);

                return $this->pagoValido($comprobante, $pedido);
            } catch (ApiError) {
                throw $error;
            }
        }
    }

    private function pagoValido(array $pago, Pedido $pedido): array
    {
        if (($pago['pedido_id'] ?? null) !== $pedido->id || ($pago['monto'] ?? null) !== $pedido->total
            || !in_array($pago['estado'] ?? null, ['aprobado', 'rechazado'], true)) {
            throw new ApiError(503, 'Resultado de pago incierto');
        }

        return $pago;
    }

    /** Persiste el avance con comparación del paso previo y limpia el rastro de fallos. */
    private function avanzar(Pedido $pedido, array $cambios): void
    {
        $cambios += ['intentos' => 0, 'ultimo_error' => null, 'proximo_intento' => null];
        // El constructor de consultas no aplica los casts: las columnas jsonb se serializan aquí.
        $columnas = array_map(fn ($valor) => is_array($valor) ? json_encode($valor, JSON_THROW_ON_ERROR) : $valor, $cambios);
        $actualizados = Pedido::whereKey($pedido->id)
            ->where('paso', $pedido->paso)
            ->update($columnas);

        if ($actualizados !== 1) {
            throw new ApiError(409, 'La compra avanzó en otro proceso. Reintenta con la misma clave');
        }
        $pedido->forceFill($cambios)->syncOriginal();
    }

    /** Intentos, próximo intento con backoff exponencial y último error sin secretos. */
    private function registrarFallo(Pedido $pedido, string $mensaje): void
    {
        try {
            $intentos = ((int) Pedido::whereKey($pedido->id)->value('intentos')) + 1;
            Pedido::whereKey($pedido->id)->update([
                'intentos' => $intentos,
                'ultimo_error' => mb_substr($mensaje, 0, 200),
                'proximo_intento' => now()->addSeconds(min(self::ESPERA_MAXIMA, 5 * (2 ** min($intentos - 1, 6)))),
            ]);
        } catch (Throwable $error) {
            Log::warning('No se pudo registrar el fallo del pedido', ['pedido' => $pedido->id]);
        }
    }

    private function comprobarReserva(array $datos, string $pedidoId, string $estado): void
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
