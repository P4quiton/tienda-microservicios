<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Resources\ProductoResource;
use App\Models\Producto;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Validator;
use Illuminate\Validation\ValidationException;

class ProductoController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        $filters = $request->validate([
            'q' => ['sometimes', 'string', 'max:255'],
            'categoria' => ['sometimes', 'string', 'max:120'],
            'pagina' => ['sometimes', 'integer', 'min:1'],
            'limite' => ['sometimes', 'integer', 'min:1', 'max:100'],
        ]);

        $pagina = (int) ($filters['pagina'] ?? 1);
        $limite = (int) ($filters['limite'] ?? 20);
        $query = Producto::query();

        if (isset($filters['q']) && trim($filters['q']) !== '') {
            $termino = mb_strtolower(trim($filters['q']));
            $query->where(function (Builder $builder) use ($termino): void {
                $builder->whereRaw('LOWER(nombre) LIKE ?', ["%{$termino}%"])
                    ->orWhereRaw('LOWER(descripcion) LIKE ?', ["%{$termino}%"]);
            });
        }

        if (isset($filters['categoria']) && trim($filters['categoria']) !== '') {
            $query->whereRaw('LOWER(categoria) = ?', [mb_strtolower(trim($filters['categoria']))]);
        }

        $total = (clone $query)->count();
        $productos = $query->orderBy('nombre')->orderBy('id')
            ->offset(($pagina - 1) * $limite)
            ->limit($limite)
            ->get();

        return response()->json([
            'success' => true,
            'message' => 'Catálogo consultado correctamente.',
            'data' => [
                'items' => ProductoResource::collection($productos)->resolve(),
                'total' => $total,
                'pagina' => $pagina,
                'limite' => $limite,
            ],
        ]);
    }

    public function show(string $id): JsonResponse
    {
        $producto = Producto::query()->findOrFail($id);

        return response()->json([
            'success' => true,
            'message' => 'Producto consultado correctamente.',
            'data' => (new ProductoResource($producto))->resolve(),
        ]);
    }

    public function store(Request $request): JsonResponse
    {
        $allowed = ['nombre', 'descripcion', 'precio', 'categoria', 'imagen_url'];
        $unexpected = array_diff(array_keys($request->json()->all()), $allowed);

        if ($unexpected !== []) {
            throw ValidationException::withMessages([
                'body' => ['El cuerpo contiene campos no permitidos: '.implode(', ', $unexpected).'.'],
            ]);
        }

        $data = Validator::make($request->json()->all(), [
            'nombre' => ['required', 'string', 'min:1', 'max:255'],
            'descripcion' => ['required', 'string'],
            'precio' => ['required', 'string', 'regex:/^\d{1,10}\.\d{2}$/', 'numeric', 'gt:0'],
            'categoria' => ['required', 'string', 'min:1', 'max:120'],
            'imagen_url' => ['required', 'string', 'url:http,https', 'max:2048'],
        ])->validate();

        $producto = Producto::query()->create($data);

        return response()->json([
            'success' => true,
            'message' => 'Producto creado correctamente.',
            'data' => (new ProductoResource($producto))->resolve(),
        ], 201);
    }
}
