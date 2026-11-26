<?php

namespace App\Pedidos;

use PDOException;
use Throwable;

/**
 * Decide si una excepción indica que PostgreSQL no está disponible (no que la consulta sea errónea).
 * Origen: bootstrap/app.php (render de excepciones). Destino: respuesta 503 sin detalles internos.
 * SQLSTATE considerados: clase 08 (conexión), 57P (apagado/reinicio) y 53 (recursos agotados).
 */
final class BaseNoDisponible
{
    public static function causa(Throwable $error): bool
    {
        for ($actual = $error; $actual !== null; $actual = $actual->getPrevious()) {
            if ($actual instanceof PDOException) {
                $estado = (string) ($actual->errorInfo[0] ?? $actual->getCode());
                if (str_starts_with($estado, '08') || str_starts_with($estado, '57P') || str_starts_with($estado, '53')) {
                    return true;
                }
            }
        }

        return false;
    }
}
