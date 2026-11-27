<?php

namespace App\Providers;

use App\Pedidos\RecuperarPedidos;
use Illuminate\Support\ServiceProvider;

final class AppServiceProvider extends ServiceProvider
{
    public function boot(): void
    {
        if ($this->app->runningInConsole()) {
            $this->commands([RecuperarPedidos::class]);
        }
    }
}
