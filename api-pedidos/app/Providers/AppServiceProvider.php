<?php

namespace App\Providers;

use App\Pedidos\CarritoCheckout;
use App\Pedidos\CarritoSinContrato;
use App\Pedidos\CarritoHttp;
use Illuminate\Support\ServiceProvider;

final class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->app->bind(CarritoCheckout::class, config('pedidos.draft_cart_checkout') ? CarritoHttp::class : CarritoSinContrato::class);
    }
}
