<?php

namespace App\Pedidos;

use Illuminate\Support\Str;

/**
 * Cliente de Carrito (carrito.yaml 1.1.0). Origen: Compra. Destino: api-carrito con el
 * X-Service-Token del par Pedidos->Carrito. Solo valida y normaliza; no guarda estado.
 * leer: GET /api/carrito/{usuario_id}; iniciar/finalizar/liberar: POST con Idempotency-Key estable.
 */
final class CarritoHttp
{
    public function __construct(private ServiciosCompra $servicios) {}

    /** @return array{carrito_id: string, version: int, items: list<array{producto_id: string, cantidad: int, linea_id: string}>} */
    public function leer(string $usuarioId): array
    {
        $datos = $this->servicios->consultar('carrito', '/api/carrito/'.$usuarioId);
        if (strtolower((string) ($datos['usuario_id'] ?? '')) !== $usuarioId || !$this->versionValida($datos['version'] ?? null)) {
            throw new ApiError(503, 'Carrito inválido');
        }

        return ['carrito_id' => $usuarioId, 'version' => $datos['version'], 'items' => $this->lineas($datos['items'] ?? null)];
    }

    /**
     * Captura el snapshot inmutable en Carrito. 409 si la versión cambió u otro checkout está activo.
     *
     * @return list<array{producto_id: string, cantidad: int, linea_id: string}> líneas del snapshot original
     */
    public function iniciar(Pedido $pedido): array
    {
        $version = (int) $pedido->carrito_version;
        $datos = $this->servicios->ejecutar('carrito', $this->ruta($pedido, 'iniciar'), [
            'pedido_id' => $pedido->id,
            'version_original' => $version,
        ], $pedido->clave('iniciar'));
        if (($datos['pedido_id'] ?? null) !== $pedido->id || ($datos['version_original'] ?? null) !== $version) {
            throw new ApiError(503, 'Snapshot del carrito inválido');
        }
        $items = $this->lineas($datos['items'] ?? null);
        if ($items === []) {
            throw new ApiError(503, 'Snapshot del carrito vacío');
        }

        return $items;
    }

    /** Retira del carrito las cantidades compradas (por linea_id). Repetir devuelve el resultado registrado. */
    public function finalizar(Pedido $pedido): void
    {
        $this->servicios->ejecutar('carrito', $this->ruta($pedido, 'finalizar'), [
            'pedido_id' => $pedido->id,
            'version_original' => (int) $pedido->carrito_version,
            'items' => $pedido->snapshot,
        ], $pedido->clave('finalizar'));
    }

    /** Cierra el checkout sin modificar artículos (fallo o rechazo definitivo antes de cobrar). */
    public function liberar(Pedido $pedido): void
    {
        $this->servicios->ejecutar('carrito', $this->ruta($pedido, 'liberar'), [
            'pedido_id' => $pedido->id,
        ], $pedido->clave('liberar_carrito'));
    }

    private function ruta(Pedido $pedido, string $accion): string
    {
        return '/api/carrito/'.$pedido->usuario_id.'/'.$accion;
    }

    private function versionValida(mixed $version): bool
    {
        return is_int($version) && $version >= 0;
    }

    /** @return list<array{producto_id: string, cantidad: int, linea_id: string}> */
    private function lineas(mixed $items): array
    {
        if (!is_array($items) || !array_is_list($items)) {
            throw new ApiError(503, 'Snapshot del carrito inválido');
        }
        $vistas = [];
        $normalizadas = [];
        foreach ($items as $item) {
            if (!is_array($item) || !is_string($item['producto_id'] ?? null) || !Str::isUuid($item['producto_id'], 4)
                || !is_int($item['cantidad'] ?? null) || $item['cantidad'] < 1
                || !is_string($item['linea_id'] ?? null) || !Str::isUuid($item['linea_id'])
                || isset($vistas[strtolower($item['linea_id'])])) {
                throw new ApiError(503, 'Snapshot del carrito inválido');
            }
            $vistas[strtolower($item['linea_id'])] = true;
            $normalizadas[] = [
                'producto_id' => strtolower($item['producto_id']),
                'cantidad' => $item['cantidad'],
                'linea_id' => strtolower($item['linea_id']),
            ];
        }

        return $normalizadas;
    }
}
