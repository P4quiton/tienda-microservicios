<?php

namespace App\Pedidos;

use Illuminate\Console\Command;

/**
 * Reanuda checkouts pendientes sin nueva petición del cliente (docs/flujo-compra.md, "Recuperación durable").
 * Origen: tabla pedidos (paso no terminal con próximo intento vencido). Destino: Compra::recuperar, que
 * repite cada paso con las mismas Idempotency-Key. Programado cada minuto en routes/console.php y
 * ejecutable al arrancar el contenedor. El bloqueo advisory por usuario evita trabajadores simultáneos.
 */
final class RecuperarPedidos extends Command
{
    protected $signature = 'pedidos:recuperar {--limite=50 : Máximo de pedidos por ejecución}';

    protected $description = 'Reanuda los checkouts pendientes con las mismas claves de idempotencia';

    public function handle(Compra $compra): int
    {
        $pendientes = Pedido::whereNotIn('paso', Pedido::TERMINALES)
            ->where(fn ($consulta) => $consulta->whereNull('proximo_intento')->orWhere('proximo_intento', '<=', now()))
            ->orderBy('creado_en')
            ->limit(max(1, (int) $this->option('limite')))
            ->pluck('id');

        $cuentas = ['completado' => 0, 'pendiente' => 0, 'ocupado' => 0, 'omitido' => 0];
        foreach ($pendientes as $id) {
            $cuentas[$compra->recuperar($id)]++;
        }
        $this->info(sprintf(
            'Pedidos revisados: %d (completados %d, pendientes %d, ocupados %d, omitidos %d)',
            count($pendientes), $cuentas['completado'], $cuentas['pendiente'], $cuentas['ocupado'], $cuentas['omitido'],
        ));

        return self::SUCCESS;
    }
}
