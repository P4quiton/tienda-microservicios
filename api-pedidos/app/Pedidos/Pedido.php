<?php

namespace App\Pedidos;

use Illuminate\Database\Eloquent\Model;

final class Pedido extends Model
{
    protected $table = 'pedidos';

    protected $guarded = [];

    public $incrementing = false;

    public $timestamps = false;

    protected $casts = [
        'items' => 'array',
        'direccion' => 'array',
        'costo_envio' => 'decimal:2',
        'total' => 'decimal:2',
        'creado_en' => 'immutable_datetime',
    ];

    public function respuesta(): array
    {
        return [
            'id' => $this->id,
            'usuario_id' => $this->usuario_id,
            'items' => $this->items,
            'direccion' => $this->direccion,
            'costo_envio' => $this->costo_envio,
            'total' => $this->total,
            'estado' => $this->estado,
            'creado_en' => $this->creado_en->toISOString(),
        ];
    }
}
