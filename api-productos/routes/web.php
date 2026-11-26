<?php

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Route;

Route::get('/health', function () {
    return response()->json(['status' => 'ok', 'service' => 'api-productos']);
});

Route::get('/ready', function () {
    try {
        DB::connection()->select('SELECT 1');

        return response()->json(['status' => 'ok', 'service' => 'api-productos']);
    } catch (Throwable) {
        return response()->json(['status' => 'unavailable', 'service' => 'api-productos'], 503);
    }
});
