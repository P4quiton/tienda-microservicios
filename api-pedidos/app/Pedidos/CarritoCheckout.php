<?php

namespace App\Pedidos;

interface CarritoCheckout
{
    /**
     * Obtiene una vista consistente del carrito antes de reservar inventario.
     *
     * @return array{carrito_id: string, version: string, items: list<array{producto_id: string, cantidad: int}>}
     */
    public function leer(string $usuarioId): array;

    /** Bloquea el snapshot de forma idempotente por pedido. */
    public function preparar(Pedido $pedido): void;

    /** Libera el snapshot preparado de forma idempotente por pedido. */
    public function cancelar(Pedido $pedido): void;

    /** Retira las cantidades del snapshot de forma atómica e idempotente por pedido. */
    public function confirmar(Pedido $pedido): void;
}
