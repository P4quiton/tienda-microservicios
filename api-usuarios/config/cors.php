<?php

return [

    'paths' => [
        'api/*',
    ],

    'allowed_methods' => [
        'GET',
        'HEAD',
        'POST',
        'OPTIONS',
    ],

    'allowed_origins' => array_values(
        array_filter(
            array_map(
                'trim',
                explode(',', env('CORS_ALLOWED_ORIGINS', ''))
            )
        )
    ),

    'allowed_origins_patterns' => [],

    'allowed_headers' => [
        'Accept',
        'Authorization',
        'Content-Type',
    ],

    'exposed_headers' => [
        'Retry-After',
        'X-RateLimit-Limit',
        'X-RateLimit-Remaining',
        'X-RateLimit-Reset',
        'WWW-Authenticate',
    ],

    'max_age' => 600,

    'supports_credentials' => false,

];
