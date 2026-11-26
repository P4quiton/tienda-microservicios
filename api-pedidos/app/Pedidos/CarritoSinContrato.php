<?php

namespace App\Pedidos;

final class CarritoSinContrato implements CarritoCheckout
{
    public function leer(string $usuarioId): array
    {
        throw new ApiError(503, 'La finalización del carrito versionado no está disponible');
    }

    public function preparar(Pedido $pedido): void
    {
        throw new ApiError(503, 'La finalización del carrito versionado no está disponible');
    }

    public function cancelar(Pedido $pedido): void
    {
        throw new ApiError(503, 'La finalización del carrito versionado no está disponible');
    }

    public function confirmar(Pedido $pedido): void
    {
        throw new ApiError(503, 'La finalización del carrito versionado no está disponible');
    }
}
