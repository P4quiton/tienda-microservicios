<?php

namespace App\Pedidos;

use Illuminate\Support\Str;

/** Adaptador provisional: requiere habilitación explícita hasta acordar el contrato. */
final class CarritoHttp implements CarritoCheckout
{
    public function __construct(private ServiciosCompra $servicios) {}

    public function leer(string $usuarioId): array
    {
        $datos = $this->servicios->consultar('carrito', '/api/carrito/'.$usuarioId.'/checkout');
        if (($datos['carrito_id'] ?? null) !== $usuarioId
            || !is_string($datos['version'] ?? null) || $datos['version'] === ''
            || strlen($datos['version']) > 255
            || !is_array($datos['items'] ?? null) || !array_is_list($datos['items'])) {
            throw new ApiError(503, 'Snapshot del carrito inválido');
        }
        $productos = [];
        foreach ($datos['items'] as $item) {
            if (!is_array($item) || !is_string($item['producto_id'] ?? null)
                || !Str::isUuid($item['producto_id'], 4) || !is_int($item['cantidad'] ?? null)
                || $item['cantidad'] < 1 || isset($productos[strtolower($item['producto_id'])])) {
                throw new ApiError(503, 'Snapshot del carrito inválido');
            }
            $productos[strtolower($item['producto_id'])] = true;
        }

        return $datos;
    }

    public function preparar(Pedido $pedido): void
    {
        $this->enviar($pedido, 'preparar');
    }

    public function confirmar(Pedido $pedido): void
    {
        $this->enviar($pedido, 'confirmar');
    }

    public function cancelar(Pedido $pedido): void
    {
        $this->enviar($pedido, 'cancelar');
    }

    private function enviar(Pedido $pedido, string $accion): void
    {
        $items = array_map(fn (array $item) => [
            'producto_id' => $item['producto_id'], 'cantidad' => $item['cantidad'],
        ], $pedido->items);
        $this->servicios->ejecutar('carrito', '/api/carrito/'.$pedido->usuario_id.'/checkout/'.$accion, [
            'pedido_id' => $pedido->id,
            'version' => $pedido->carrito_version,
            'items' => $items,
        ]);
    }
}
