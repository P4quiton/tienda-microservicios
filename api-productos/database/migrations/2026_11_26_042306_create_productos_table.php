<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        Schema::create('productos', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->string('nombre', 255);
            $table->text('descripcion');
            $table->decimal('precio', 12, 2);
            $table->string('categoria', 120)->index();
            $table->text('imagen_url');
            $table->timestamps();
            $table->index(['nombre', 'id']);
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('productos');
    }
};
