<?php

namespace Database\Seeders;

use App\Models\Producto;
use Illuminate\Database\Seeder;

class ProductoSeeder extends Seeder
{
    /**
     * Run the database seeds.
     */
    public function run(): void
    {
        $productos = [
            ['nombre' => 'Audífonos inalámbricos', 'descripcion' => 'Audífonos Bluetooth con estuche de carga.', 'precio' => '899.99', 'categoria' => 'Electrónica', 'imagen_url' => 'https://placehold.co/600x400?text=Audifonos'],
            ['nombre' => 'Lámpara de escritorio', 'descripcion' => 'Lámpara LED con intensidad ajustable.', 'precio' => '549.00', 'categoria' => 'Hogar', 'imagen_url' => 'https://placehold.co/600x400?text=Lampara'],
            ['nombre' => 'Balón de fútbol', 'descripcion' => 'Balón tamaño 5 para entrenamiento.', 'precio' => '429.50', 'categoria' => 'Deportes', 'imagen_url' => 'https://placehold.co/600x400?text=Balon'],
            ['nombre' => 'Cuaderno de notas', 'descripcion' => 'Cuaderno de pasta dura con 160 páginas.', 'precio' => '125.00', 'categoria' => 'Papelería', 'imagen_url' => 'https://placehold.co/600x400?text=Cuaderno'],
        ];

        foreach ($productos as $producto) {
            Producto::query()->firstOrCreate(['nombre' => $producto['nombre']], $producto);
        }
    }
}
