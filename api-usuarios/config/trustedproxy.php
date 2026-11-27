<?php

// Frontera de confianza para X-Forwarded-For. Origen: TRUSTED_PROXIES (IP o CIDR separados por comas).
// Vacío = no se confía en ningún proxy: $request->ip() es la dirección del socket. Se descartan a propósito
// '*', 'true', alias y prefijos /0, porque confiar "en todo" permite falsificar la IP y evadir el limitador.
// La variable debe existir como variable de entorno del proceso (bootstrap/app.php la lee al arrancar).
$entries = explode(',', (string) env('TRUSTED_PROXIES', ''));

return [
    'proxies' => array_values(array_filter(array_map('trim', $entries), static function (string $entry): bool {
        [$address, $prefix] = array_pad(explode('/', $entry, 2), 2, null);

        if (filter_var($address, FILTER_VALIDATE_IP) === false) {
            return false;
        }

        // Un prefijo /0 confiaría en toda la familia de direcciones.
        $maxPrefix = str_contains($address, ':') ? 128 : 32;

        return $prefix === null || (ctype_digit($prefix) && (int) $prefix >= 1 && (int) $prefix <= $maxPrefix);
    })),
];
