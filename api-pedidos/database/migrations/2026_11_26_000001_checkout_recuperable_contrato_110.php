<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Contrato 1.1.0: el pedido se persiste antes de calcular importes y antes de cualquier efecto externo,
 * conserva el snapshot versionado de Carrito (con linea_id), el avance reintentable y el registro de
 * claves del PATCH de Envíos. Idempotente: se puede repetir sin error.
 * Los pasos "terminales" no cuentan como checkout activo: un solo checkout activo por usuario.
 */
return new class extends Migration
{
    private const TERMINALES = "'terminado','sin_stock','carrito_desactualizado','rango_invalido'";

    public function up(): void
    {
        // Importes e ítems se conocen solo tras iniciar el carrito y consultar Productos/Envíos.
        foreach (['items', 'costo_envio', 'total'] as $columna) {
            DB::statement("alter table pedidos alter column $columna drop not null");
        }

        Schema::table('pedidos', function (Blueprint $table) {
            if (!Schema::hasColumn('pedidos', 'snapshot')) {
                $table->jsonb('snapshot')->nullable();
            }
            if (!Schema::hasColumn('pedidos', 'intentos')) {
                $table->unsignedInteger('intentos')->default(0);
            }
            if (!Schema::hasColumn('pedidos', 'proximo_intento')) {
                $table->timestampTz('proximo_intento')->nullable();
            }
            if (!Schema::hasColumn('pedidos', 'ultimo_error')) {
                $table->text('ultimo_error')->nullable();
            }
        });

        DB::statement('create unique index if not exists pedidos_un_checkout_activo on pedidos (usuario_id) where paso not in ('.self::TERMINALES.')');
        DB::statement('create index if not exists pedidos_recuperacion on pedidos (proximo_intento) where paso not in ('.self::TERMINALES.')');

        if (!Schema::hasTable('pedidos_cambios_estado')) {
            Schema::create('pedidos_cambios_estado', function (Blueprint $table) {
                $table->uuid('clave')->primary();
                $table->uuid('pedido_id')->index();
                $table->string('estado');
                $table->timestampTz('creado_en');
            });
        }
    }

    public function down(): void
    {
        Schema::dropIfExists('pedidos_cambios_estado');
        DB::statement('drop index if exists pedidos_recuperacion');
        DB::statement('drop index if exists pedidos_un_checkout_activo');
        Schema::table('pedidos', function (Blueprint $table) {
            $table->dropColumn(['snapshot', 'intentos', 'proximo_intento', 'ultimo_error']);
        });
        DB::statement("update pedidos set items = '[]'::jsonb where items is null");
        DB::statement('update pedidos set costo_envio = 0 where costo_envio is null');
        DB::statement('update pedidos set total = 0 where total is null');
        foreach (['items', 'costo_envio', 'total'] as $columna) {
            DB::statement("alter table pedidos alter column $columna set not null");
        }
    }
};
