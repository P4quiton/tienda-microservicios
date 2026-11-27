<?php

return [
    'algorithm' => 'RS256',

    'issuer' => env('JWT_ISSUER', 'api-usuarios'),

    'audience' => env(
        'JWT_AUDIENCE',
        'tienda-microservicios'
    ),

    'ttl_seconds' => (int) env('JWT_TTL_SECONDS', 3600),

    'private_key_path' => env(
        'JWT_PRIVATE_KEY_PATH',
        'storage/keys/jwt-private.pem'
    ),

    'public_key_path' => env(
        'JWT_PUBLIC_KEY_PATH',
        'storage/keys/jwt-public.pem'
    ),
];