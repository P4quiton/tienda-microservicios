<?php

namespace App\Providers;

use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Register any application services.
     */
    public function register(): void
    {
        //
    }

    /**
     * Bootstrap any application services.
     */
    public function boot(): void
    {
        RateLimiter::for('productos-consultas', static fn (Request $request) => Limit::perMinute(120)
            ->by((string) $request->ip()));

        RateLimiter::for('productos-mutaciones', static fn (Request $request) => Limit::perMinute(30)
            ->by((string) $request->ip()));
    }
}
