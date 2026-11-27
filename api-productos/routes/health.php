<?php

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Route;
use Illuminate\Support\Facades\Schema;

Route::get('/health', function () {
    return response()->json(['status' => 'ok', 'service' => 'api-productos']);
})->name('health');

Route::get('/ready', function () {
    $ready = false;

    try {
        DB::connection()->select('SELECT 1');

        $migrationApplied = DB::table('migrations')
            ->where('migration', '2026_11_26_042306_create_productos_table')
            ->exists();

        $path = config('services.jwt.public_key_path');

        if ($migrationApplied && Schema::hasTable('productos') && is_string($path) && is_file($path) && is_readable($path)) {
            $contents = file_get_contents($path);
            $key = $contents === false ? false : openssl_pkey_get_public($contents);
            $details = $key === false ? false : openssl_pkey_get_details($key);
            $ready = $details !== false && $details['type'] === OPENSSL_KEYTYPE_RSA && $details['bits'] >= 3072;
        }
    } catch (Throwable) {
        $ready = false;
    }

    return response()->json([
        'status' => $ready ? 'ok' : 'unavailable',
        'service' => 'api-productos',
    ], $ready ? 200 : 503);
})->name('ready');
