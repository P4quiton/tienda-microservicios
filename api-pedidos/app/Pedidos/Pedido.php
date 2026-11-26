<?php

namespace App\Pedidos;

use Illuminate\Database\Eloquent\Model;
use Ramsey\Uuid\Uuid;

final class Pedido extends Model
{
    /** Pasos en los que el checkout ya no está activo (ver migración de contrato 1.1.0). */
    public const TERMINALES = ['terminado', 'sin_stock', 'carrito_desactualizado', 'rango_invalido'];

    protected $table = 'pedidos';

    protected $guarded = [];

    public $incrementing = false;

    public $timestamps = false;

    protected $casts = [
        'items' => 'array',
        'snapshot' => 'array',
        'direccion' => 'array',
        'costo_envio' => 'decimal:2',
        'total' => 'decimal:2',
        'creado_en' => 'immutable_datetime',
        'proximo_intento' => 'immutable_datetime',
    ];

    /**
     * Idempotency-Key estable por operación y pedido (UUID). Inventario/reservar y Pagos/procesar
     * usan el id del pedido, como en el protocolo previo; el resto, un UUIDv5 derivado del id.
     * Misma operación => misma clave en cada reintento, incluso tras reiniciar el proceso.
     */
    public function clave(string $operacion): string
    {
        return in_array($operacion, ['reservar', 'pagar'], true)
            ? $this->id
            : Uuid::uuid5($this->id, $operacion)->toString();
    }

    public function respuesta(): array
    {
        return [
            'id' => $this->id,
            'usuario_id' => $this->usuario_id,
            'items' => $this->items ?? [],
            'direccion' => $this->direccion,
            'costo_envio' => $this->costo_envio ?? '0.00',
            'total' => $this->total ?? '0.00',
            'estado' => $this->estado,
            'creado_en' => $this->creado_en->toISOString(),
        ];
    }
}
