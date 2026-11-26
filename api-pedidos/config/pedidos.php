<?php

return [
    'draft_cart_checkout' => env('ENABLE_DRAFT_CART_CHECKOUT', false),
    'jwt_public_key_path' => env('JWT_PUBLIC_KEY_PATH', '/run/secrets/jwt-public.pem'),
    'urls' => [
        'carrito' => env('API_CARRITO_URL', 'http://api-carrito:8005'),
        'productos' => env('API_PRODUCTOS_URL', 'http://api-productos:8002'),
        'inventario' => env('API_INVENTARIO_URL', 'http://api-inventario:8004'),
        'pagos' => env('API_PAGOS_URL', 'http://api-pagos:8007'),
        'envios' => env('API_ENVIOS_URL', 'http://api-envios:8003'),
    ],
    'tokens_salientes' => [
        'carrito' => env('SERVICE_TOKEN_PEDIDOS_CARRITO'),
        'inventario' => env('SERVICE_TOKEN_PEDIDOS_INVENTARIO'),
        'pagos' => env('SERVICE_TOKEN_PEDIDOS_PAGOS'),
        'envios' => env('SERVICE_TOKEN_PEDIDOS_ENVIOS'),
    ],
    'tokens_entrantes' => [
        'pagos' => env('SERVICE_TOKEN_PAGOS_PEDIDOS'),
        'envios' => env('SERVICE_TOKEN_ENVIOS_PEDIDOS'),
    ],
];
