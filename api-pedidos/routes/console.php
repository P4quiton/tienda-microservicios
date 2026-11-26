<?php

use Illuminate\Support\Facades\Schedule;

// Recuperación durable del checkout: reanuda pasos pendientes sin intervención del cliente.
Schedule::command('pedidos:recuperar')->everyMinute();
