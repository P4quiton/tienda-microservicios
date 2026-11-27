<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('usuarios', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->string('nombre', 120);
            $table->string('correo', 254)->unique();
            $table->string('password', 255);
            $table->string('role', 10)->default('cliente');
            $table->timestampsTz();
        });

        DB::statement("
            ALTER TABLE usuarios
            ADD CONSTRAINT usuarios_role_check
            CHECK (role IN ('cliente', 'admin'))
        ");

        DB::statement("
            ALTER TABLE usuarios
            ADD CONSTRAINT usuarios_correo_normalizado_check
            CHECK (
                correo = LOWER(TRIM(correo))
                AND LENGTH(correo) > 0
            )
        ");

        DB::statement("
            ALTER TABLE usuarios
            ADD CONSTRAINT usuarios_nombre_check
            CHECK (LENGTH(TRIM(nombre)) > 0)
        ");
    }

    public function down(): void
    {
        Schema::dropIfExists('usuarios');
    }
};
