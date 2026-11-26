<?php

namespace App\Pedidos;

use Illuminate\Database\Eloquent\Model;

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
     * usan el id del pedido, como en el protocolo previo; el resto, un UUID v4 derivado por hash del id y la
     * operación (Carrito, Envíos e Inventario exigen v4: un UUIDv5 recibía 422 y el checkout nunca avanzaba).
     * Misma operación => misma clave en cada reintento, incluso tras reiniciar el proceso.
     */
    public function clave(string $operacion): string
    {
        return in_array($operacion, ['reservar', 'pagar'], true)
            ? $this->id
            : self::uuidV4Derivado($this->id.'|'.$operacion);
    }

    /** UUID con bits de versión 4 y variante RFC 4122 a partir de un hash determinista (no es aleatorio). */
    private static function uuidV4Derivado(string $semilla): string
    {
        $bytes = substr(hash('sha256', $semilla, true), 0, 16);
        $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
        $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
        $hex = bin2hex($bytes);

        return sprintf('%s-%s-%s-%s-%s', substr($hex, 0, 8), substr($hex, 8, 4), substr($hex, 12, 4), substr($hex, 16, 4), substr($hex, 20, 12));
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
