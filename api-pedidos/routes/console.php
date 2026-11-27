<?php

use Illuminate\Support\Facades\Schedule;

// Recuperación durable del checkout: reanuda pasos pendientes sin intervención del cliente.
Schedule::command('pedidos:recuperar')->everyMinute()
    // Un solo run a la vez por instancia (candado en caché). Entre réplicas con caché de archivo por
    // instancia estos candados NO coordinan; la garantía real es el bloqueo advisory por usuario en Compra.
    ->withoutOverlapping(10)
    ->onOneServer();
