<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('pedidos', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->uuid('usuario_id')->index();
            $table->uuid('clave_idempotencia');
            $table->string('huella', 64);
            $table->jsonb('items');
            $table->jsonb('direccion');
            $table->string('metodo_pago');
            $table->decimal('costo_envio', 12, 2);
            $table->decimal('total', 12, 2);
            $table->string('estado');
            $table->string('paso');
            $table->uuid('carrito_id');
            $table->string('carrito_version');
            $table->string('guia')->nullable();
            $table->timestampTz('creado_en');
            $table->unique(['usuario_id', 'clave_idempotencia']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('pedidos');
    }
};
