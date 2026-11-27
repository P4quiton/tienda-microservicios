<?php

namespace App\Http\Controllers;

use App\Services\JwtService;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\DB;
use RuntimeException;
use Throwable;

class HealthController extends Controller
{
    public function health(): JsonResponse
    {
        return response()->json([
            'status' => 'ok',
            'service' => 'api-usuarios',
        ], 200);
    }

    public function ready(JwtService $jwt): JsonResponse
    {
        try {
            DB::select('SELECT 1');

            $migrationApplied = DB::table('migrations')
                ->where('migration', '0001_01_01_000000_create_usuarios_table')
                ->exists();

            if (! $migrationApplied) {
                throw new RuntimeException('La migracion de usuarios no esta aplicada.');
            }

            $jwt->assertReady();

            return response()->json([
                'status' => 'ok',
                'service' => 'api-usuarios',
            ], 200);
        } catch (Throwable) {
            return response()->json([
                'status' => 'unavailable',
                'service' => 'api-usuarios',
            ], 503);
        }
    }
}
