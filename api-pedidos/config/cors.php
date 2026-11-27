<?php

// Lista vacía por defecto: el frontend usa Nginx en el mismo origen y no necesita CORS.
// Solo orígenes completos; '*' se descarta porque Fruitcake lo trataría como comodín.
$origenes = array_values(array_filter(
    array_map('trim', explode(',', (string) env('CORS_ALLOWED_ORIGINS', ''))),
    static fn (string $origen): bool => $origen !== '' && !str_contains($origen, '*'),
));

return [
    'paths' => ['api/*'],
    'allowed_methods' => ['GET', 'HEAD', 'POST', 'PATCH', 'OPTIONS'],
    // Fruitcake devuelve el único origen de 'allowed_origins' en Access-Control-Allow-Origin aunque la
    // petición venga de otro origen. Con patrones anclados, la cabecera depende del Origin recibido y
    // falta cuando el origen no está permitido.
    'allowed_origins' => [],
    'allowed_origins_patterns' => array_map(
        static fn (string $origen): string => '#^'.preg_quote($origen, '#').'$#',
        $origenes,
    ),
    'allowed_headers' => [
        'Accept',
        'Authorization',
        'Content-Type',
        'Idempotency-Key',
    ],
    'exposed_headers' => [
        'Retry-After',
        'X-RateLimit-Limit',
        'X-RateLimit-Remaining',
        'WWW-Authenticate',
    ],
    'max_age' => 600,
    'supports_credentials' => false,
];
