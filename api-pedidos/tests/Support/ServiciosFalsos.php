<?php

namespace Tests\Support;

use GuzzleHttp\Promise\PromiseInterface;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;

/**
 * Doble HTTP de Carrito, Productos, Inventario, Pagos y Envíos según el contrato 1.1.0.
 * Origen: peticiones salientes de Pedidos (Http::fake). Destino: respuestas del contrato.
 * Cada llamada se registra como "<servicio>.<operación>" (p. ej. "pagos.procesar").
 * `fallos['pagos.procesar'] = [503, 'timeout']` hace fallar las primeras llamadas, en orden.
 */
final class ServiciosFalsos
{
    /** @var list<array{clave: string, cuerpo: array, idempotencia: ?string, token: ?string}> */
    public array $llamadas = [];

    /** @var array<string, list<int|string>> */
    public array $fallos = [];

    /** @var array<string, callable(array): void> Gancho previo a responder (p. ej. para comprobar la BD). */
    public array $antes = [];

    /** @var array<string, int> Microsegundos de retardo por operación. */
    public array $retardo = [];

    public int $version = 3;

    public int $cantidad = 2;

    public string $pago = 'aprobado';

    public string $pagoId;

    public bool $sinStock = false;

    /** Si no es null, GET /api/pagos/pedido/{id} devuelve este estado; si es null, 404. */
    public ?string $pagoConsultable = null;
    public ?string $pagoIdConsultable = null;
    public string $metodoConsultable = 'tarjeta_simulada';

    public ?string $archivo = null;

    private array $reservas = [];

    private array $resultadosInventario = [];

    public function __construct(public string $usuario, public string $producto, public string $linea)
    {
        $this->pagoId = (string) Str::uuid();
    }

    public static function nuevo(?string $usuario = null): self
    {
        return new self($usuario ?? (string) Str::uuid(), (string) Str::uuid(), (string) Str::uuid());
    }

    public function instalar(): self
    {
        config([
            'pedidos.tokens_salientes' => ['carrito' => 'tc', 'inventario' => 'ti', 'pagos' => 'tp', 'envios' => 'te'],
            'pedidos.urls' => ['carrito' => 'http://carrito', 'productos' => 'http://productos',
                'inventario' => 'http://inventario', 'pagos' => 'http://pagos', 'envios' => 'http://envios'],
        ]);
        Http::swap(new \Illuminate\Http\Client\Factory);
        Http::fake(fn (Request $peticion) => $this->responder($peticion));

        return $this;
    }

    public function cuenta(string $clave): int
    {
        return count(array_filter($this->llamadas, fn (array $l) => $l['clave'] === $clave));
    }

    /** @return list<string> */
    public function claves(): array
    {
        return array_column($this->llamadas, 'clave');
    }

    /** @return list<array> */
    public function de(string $clave): array
    {
        return array_values(array_filter($this->llamadas, fn (array $l) => $l['clave'] === $clave));
    }

    public function itemsSnapshot(): array
    {
        return [['producto_id' => $this->producto, 'cantidad' => $this->cantidad, 'linea_id' => $this->linea]];
    }

    private function clave(Request $peticion): string
    {
        $ruta = parse_url($peticion->url(), PHP_URL_PATH);
        $accion = basename($ruta);

        return match (true) {
            $peticion->method() === 'GET' && str_starts_with($ruta, '/api/carrito/') => 'carrito.leer',
            $peticion->method() === 'GET' && str_starts_with($ruta, '/api/productos/') => 'productos.leer',
            $peticion->method() === 'GET' && str_starts_with($ruta, '/api/pagos/pedido/') => 'pagos.consultar',
            str_starts_with($ruta, '/api/carrito/') => 'carrito.'.$accion,
            $peticion->method() === 'POST' && in_array($ruta, [
                '/api/inventario/reservar', '/api/inventario/confirmar', '/api/inventario/liberar',
            ], true) => 'inventario.'.$accion,
            str_starts_with($ruta, '/api/pagos/') => 'pagos.'.$accion,
            str_starts_with($ruta, '/api/envios/') => 'envios.'.$accion,
            default => 'desconocida.'.$ruta,
        };
    }

    private function responder(Request $peticion): mixed
    {
        $clave = $this->clave($peticion);
        $cuerpo = $peticion->data();
        $idempotencia = $peticion->header('Idempotency-Key')[0] ?? null;
        $this->llamadas[] = [
            'clave' => $clave,
            'cuerpo' => $cuerpo,
            'idempotencia' => $idempotencia,
            'token' => $peticion->header('X-Service-Token')[0] ?? null,
        ];
        if ($this->archivo !== null) {
            file_put_contents($this->archivo, $clave."\n", FILE_APPEND | LOCK_EX);
        }
        if (isset($this->antes[$clave])) {
            ($this->antes[$clave])($cuerpo);
        }
        if (isset($this->retardo[$clave])) {
            usleep($this->retardo[$clave]);
        }
        if (!empty($this->fallos[$clave])) {
            $fallo = array_shift($this->fallos[$clave]);
            if ($fallo === 'timeout') {
                throw new ConnectionException('timeout simulado');
            }
            if (str_starts_with($clave, 'inventario.') && in_array($fallo, [409, 503], true)) {
                return $this->errorInventario($fallo, $fallo === 409
                    ? 'La operación es incompatible con el estado actual del inventario.'
                    : 'La base de datos no está disponible.');
            }

            return Http::response([], $fallo);
        }

        if (str_starts_with($clave, 'inventario.')) {
            if ($idempotencia === null || !Str::isUuid($idempotencia, 4)) {
                return $this->errorInventario(422, 'Los datos enviados no son válidos.',
                    ['Idempotency-Key' => ['Debe ser un UUID v4 válido.']]);
            }

            return $this->inventario($clave, $cuerpo, strtolower($idempotencia));
        }

        $id = ['pedido_id' => $cuerpo['pedido_id'] ?? null];
        $datos = match ($clave) {
            'carrito.leer' => ['usuario_id' => $this->usuario, 'items' => $this->itemsSnapshot(), 'version' => $this->version],
            'carrito.iniciar' => ($cuerpo['version_original'] ?? null) !== $this->version
                ? 409
                : $id + ['version_original' => $this->version, 'items' => $this->itemsSnapshot()],
            'carrito.finalizar', 'carrito.liberar' => ['usuario_id' => $this->usuario, 'items' => [], 'version' => $this->version + 1],
            'productos.leer' => ['precio' => '2.50'],
            'envios.cotizar' => ['costo_envio' => '4.00', 'dias_estimados' => 2],
            'pagos.procesar' => $id + ['id' => $this->pagoId, 'monto' => $cuerpo['monto'] ?? null,
                'metodo_pago' => $cuerpo['metodo_pago'] ?? null, 'estado' => $this->pago, 'creado_en' => now()->toISOString()],
            'pagos.consultar' => $this->pagoConsultable === null ? 404 : [
                'id' => $this->pagoIdConsultable ?? $this->pagoId, 'pedido_id' => basename(parse_url($peticion->url(), PHP_URL_PATH)),
                'monto' => '9.00', 'metodo_pago' => $this->metodoConsultable, 'estado' => $this->pagoConsultable,
                'creado_en' => now()->toISOString(),
            ],
            'envios.generar' => $id + ['id' => (string) Str::uuid(), 'guia' => 'GUIA-FICTICIA', 'estado' => 'preparando'],
            default => 404,
        };

        return is_int($datos) ? Http::response([], $datos) : Http::response(['success' => true, 'message' => 'OK', 'data' => $datos]);
    }

    /** Simula la idempotencia de las mutaciones que consume el checkout. */
    private function inventario(string $operacion, array $cuerpo, string $clave): PromiseInterface
    {
        $solicitud = [$operacion, $cuerpo];
        $previo = $this->resultadosInventario[$clave] ?? null;
        if ($previo !== null) {
            return $previo['solicitud'] === $solicitud
                ? $previo['respuesta']
                : $this->errorInventario(409, 'La clave de idempotencia ya se usó con otros datos.',
                    ['idempotency_key' => ['conflicto_idempotencia']]);
        }

        $id = $cuerpo['pedido_id'];
        $reserva = $this->reservas[$id] ?? null;
        if ($operacion === 'inventario.reservar' && $reserva === null && $this->sinStock) {
            $respuesta = $this->errorInventario(409, 'Inventario insuficiente.', ['stock' => ['stock_insuficiente']]);
        } else {
            $respuesta = $this->mutarReserva($operacion, $cuerpo, $reserva);
            if (is_int($respuesta)) {
                return $respuesta === 404
                    ? $this->errorInventario(404, 'Recurso no encontrado.')
                    : $this->errorInventario(409, 'La operación es incompatible con el estado actual del inventario.');
            }
        }

        $this->resultadosInventario[$clave] = compact('solicitud', 'respuesta');

        return $respuesta;
    }

    private function mutarReserva(string $operacion, array $cuerpo, ?array $reserva): PromiseInterface|int
    {
        $id = $cuerpo['pedido_id'];
        if ($operacion === 'inventario.reservar') {
            $reserva ??= ['pedido_id' => $id, 'items' => $cuerpo['items'], 'estado' => 'reservada'];
            if ($reserva['items'] !== $cuerpo['items']) {
                return 409;
            }
            $mensaje = 'Existencias reservadas correctamente.';
        } else {
            if ($reserva === null) {
                return 404;
            }
            $destino = $operacion === 'inventario.confirmar' ? 'confirmada' : 'liberada';
            if (!in_array($reserva['estado'], ['reservada', $destino], true)) {
                return 409;
            }
            $reserva['estado'] = $destino;
            $mensaje = 'Estado de reserva actualizado.';
        }

        $this->reservas[$id] = $reserva;

        return Http::response(['success' => true, 'message' => $mensaje, 'data' => $reserva]);
    }

    private function errorInventario(int $status, string $mensaje, array $errores = []): PromiseInterface
    {
        return Http::response(['success' => false, 'message' => $mensaje, 'errors' => (object) $errores], $status);
    }
}
