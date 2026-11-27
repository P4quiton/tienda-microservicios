<?php

namespace Tests\Support;

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

    public ?string $archivo = null;

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
            str_starts_with($ruta, '/api/inventario/') => 'inventario.'.$accion,
            str_starts_with($ruta, '/api/pagos/') => 'pagos.'.$accion,
            str_starts_with($ruta, '/api/envios/') => 'envios.'.$accion,
            default => 'desconocida.'.$ruta,
        };
    }

    private function responder(Request $peticion): mixed
    {
        $clave = $this->clave($peticion);
        $cuerpo = $peticion->data();
        $this->llamadas[] = [
            'clave' => $clave,
            'cuerpo' => $cuerpo,
            'idempotencia' => $peticion->header('Idempotency-Key')[0] ?? null,
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

            return Http::response([], $fallo);
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
            'inventario.reservar' => $this->sinStock ? 409 : $id + ['items' => $cuerpo['items'] ?? [], 'estado' => 'reservada'],
            'inventario.confirmar' => $id + ['items' => [], 'estado' => 'confirmada'],
            'inventario.liberar' => $id + ['items' => [], 'estado' => 'liberada'],
            'pagos.procesar' => $id + ['id' => $this->pagoId, 'monto' => $cuerpo['monto'] ?? null,
                'metodo_pago' => $cuerpo['metodo_pago'] ?? null, 'estado' => $this->pago, 'creado_en' => now()->toISOString()],
            'pagos.consultar' => $this->pagoConsultable === null ? 404 : [
                'id' => $this->pagoId, 'pedido_id' => basename(parse_url($peticion->url(), PHP_URL_PATH)),
                'monto' => '9.00', 'metodo_pago' => 'tarjeta_simulada', 'estado' => $this->pagoConsultable,
                'creado_en' => now()->toISOString(),
            ],
            'envios.generar' => $id + ['id' => (string) Str::uuid(), 'guia' => 'GUIA-FICTICIA', 'estado' => 'preparando'],
            default => 404,
        };

        return is_int($datos) ? Http::response([], $datos) : Http::response(['success' => true, 'message' => 'OK', 'data' => $datos]);
    }
}
