# QA hostil: api-pedidos (puerto 8006)

Alcance: solo `api-pedidos`. No se tocaron `docs/`, otros servicios ni la integración HTTP de Carrito (`CarritoHttp` / `CarritoSinContrato`). No se ejecutó git. Todos los datos son ficticios.

## Entorno de pruebas
- PHP 8.5.13 y PHPUnit 12.5.45, con la imagen local `pedidos-test-temporal` (sin build ni push).
- La imagen no trae PHPUnit (se instaló con `--no-dev`) y no hay `vendor` local. Se montó en solo lectura el `vendor` de una corrida anterior, `/dev/shm/pedidos-runtime.7ARkWi/app/vendor`, que corresponde al mismo `composer.lock`.
- PostgreSQL 17 temporal: `mojarra-pg-pedidos` en `127.0.0.1:55436`, con `--tmpfs` y contraseña aleatoria local. Se detuvo al terminar (`docker stop mojarra-pg-pedidos`). Aparece en un `docker ps` posterior porque `--rm -d` tarda en retirarlo; no se tocó ningún otro contenedor.
- Comando (envoltorio local en el scratchpad): `docker run --rm --network host --entrypoint "" -v <app,config,routes,tests,database,bootstrap/app.php,phpunit.xml> -v <vendor>:/app/vendor:ro -e TEST_POSTGRES=1 -e DB_* pedidos-test-temporal php vendor/bin/phpunit --do-not-cache-result`

## Resultado de pruebas
| Momento | Resultado |
|---|---|
| Antes (6 pruebas existentes, TEST_POSTGRES=1) | `OK (6 tests, 46 assertions)` |
| Pruebas hostiles nuevas contra el código original | 20 pruebas: 17 pasan y **3 fallan** (rojo) |
| Después de los arreglos, suite completa | `OK (26 tests, 242 assertions)` |
| Suite completa con TEST_POSTGRES=0 | `OK, but some tests were skipped! Tests: 26, Skipped: 9` (las 9 piden PostgreSQL) |

Salida real de las 3 fallas iniciales:
- `test_cadenas_con_controles_o_demasiado_largas...`: `"con\u0000nulo" Failed asserting that 503 is identical to 422.`
- `test_cuerpo_enorme_se_rechaza`: `Failed asserting that 503 is identical to 422.`
- `test_bd_caida_las_rutas_de_negocio...`: `Expected response status code [503] but received 500.` (`PDOException ... port 1 failed: Connection refused`)

Mutación de control: al sustituir el `pg_try_advisory_lock` de `Compra` por un `true`, la prueba de compras paralelas falló. Los 6 procesos chocaron en `pedidos_usuario_id_clave_idempotencia_unique`, así que la prueba detecta la ausencia del bloqueo. Se restauró el código original y se comprobó con `diff`.

## Hallazgos
| # | Sev. | Hallazgo | Arreglo | Prueba de regresión |
|---|---|---|---|---|
| 1 | Media | BD caída: las rutas de negocio (POST, GET pedido, historial) respondían **500** con la excepción SQL sin tratar. El contrato exige 503 para dependencia no disponible. | `app/Pedidos/BaseNoDisponible.php` detecta SQLSTATE 08, 57P y 53 en la cadena de excepciones. `bootstrap/app.php` responde 503 `Dependencia no disponible`, sin SQL ni host. | `test_bd_caida_las_rutas_de_negocio_responden_503_sin_filtrar_detalles` |
| 2 | Media | Un carácter NUL (`\u0000`) en `calle`, `ciudad` o `estado` pasaba la validación. `jsonb` no lo admite, así que el insert fallaba tras haber llamado a Productos y Envíos. Tampoco había límite de longitud. | `Controlador`: se rechazan con 422 los caracteres de control (`\p{Cc}`, `\p{Zl}`, `\p{Zp}`) y más de 200 caracteres por campo. | `test_cadenas_con_controles_o_demasiado_largas...` |
| 3 | Media | No había tope del cuerpo JSON: un cuerpo de 2 MB llegaba a la lógica de negocio. | `Controlador::json`: más de 16 KiB responde 422 (por Content-Length y por tamaño real). | `test_cuerpo_enorme_se_rechaza` |

Decisión de diseño: el tope responde 422 y no 413, porque el contrato OpenAPI no declara 413. Si el equipo prefiere 413 hay que añadirlo al YAML, que no se tocó. El tope también cubre cuerpos grandes mal formados. El middleware `ValidatePostSize` de Laravel (8 MB por defecto) sigue como segunda barrera.

## Ataques que ya se resistían (pruebas añadidas como regresión)
- JSON malformado, vacío, con comillas simples, UTF-8 inválido o anidado 5000 niveles: 400. Campos extra, tipos erróneos, raíz no objeto, método de pago inválido y CP no numérico o con salto de línea: 422.
- `Idempotency-Key` que no sea UUID v4 (v1, variante inválida, con espacios, 5000 caracteres, ausente): 422.
- JWT, 25 variantes, todas 401:
  - sin token, basura, firma truncada o ausente, payload alterado;
  - `alg=none` y `None`, y confusión HS256 con la clave pública;
  - firmado por otra clave;
  - expirado, `exp==iat`, `iat` futuro, vigencia de 2 h, `nbf` futuro;
  - `iss` o `aud` ajenos o ausentes, `sub` ausente, no UUID o UUID v1;
  - rol desconocido o ausente, `exp` ausente, `iat` como cadena.
  - La clave pública ausente o corrupta responde 401, no 500.
- Titularidad: A sobre `/usuario/B` y sobre un pedido de B responde 403, también con UUID en mayúsculas. El titular y el admin acceden (200); `sub` en mayúsculas equivale al mismo titular.
- `X-Service-Token`:
  - ausente, vacío, equivocado, en mayúsculas o con espacio: 401;
  - secreto de otro par (el saliente a Carrito): 401;
  - secreto no configurado (null o vacío): nunca autentica;
  - un JWT dentro de `X-Service-Token`: 401, y un token de servicio no abre rutas de usuario.
- `PATCH /api/pedidos/{id}/estado` sigue **cerrado por defecto**: sin credencial da 401; con un token de servicio válido (Pagos o Envíos) da 403; con JWT cliente o admin da 401. No se inventó la identidad autorizada ni se dio acceso a clientes.
- Inyección SQL: cargas en rutas (`1' OR '1'='1`, `DROP TABLE`, `UNION`) responden 422. Una carga en `calle` se guarda literal y la tabla sigue íntegra.
- Idempotencia: la misma clave repetida (incluso en mayúsculas) devuelve el mismo pedido, con 1 pedido, 1 cobro y 1 guía. Otro payload con la misma clave da 409.
- Concurrencia real (6 procesos PHP, `tests/Support/CompraWorker.php`, cobro simulado con 400 ms de retardo): con la misma clave quedó 1 pedido, 1 reserva, 1 cobro y 1 guía, y las respuestas fueron 201 o 409. Con 4 claves distintas del mismo usuario también hubo 1 cobro y 1 pedido.
- Migraciones: `migrate` dos veces es idempotente. `rollback` seguido de `migrate` es reversible, y `/ready` da 503 sin tabla y 200 con tabla.
- BD caída: `/health` da 200 y `/ready` da 503. Se comprobó también con `php artisan serve` real (4 workers) y la BD apuntando a un puerto muerto, con cache y sesión por defecto (`database`).
- Errores: 404 y 405 en JSON sin traza, aun con `APP_DEBUG=true`.

## Pendientes y NO VERIFICADO
- **NO VERIFICADO**: `docker build` de la imagen del servicio. La regla lo prohíbe y no hay disco (la raíz tenía 1.3 GB libres).
- **NO VERIFICADO**: el checkout contra el Carrito real. `CarritoSinContrato` sigue devolviendo 503 por defecto, como se pidió. Las pruebas de checkout usan dobles. Concurrencia e idempotencia se probaron a nivel `Compra::ejecutar` con procesos paralelos, no con HTTP concurrente contra los 4 workers.
- Identidad autorizada para `PATCH /estado`: sigue sin definir, es decisión del equipo (`docs/seguridad.md`). El endpoint permanece cerrado.
- Sin rate limiting en la API (el contrato lista 429). Recomendable en el proxy Nginx, junto con el límite de cuerpo.
- Un `iat` con 1 s de desfase de reloj entre servicios se rechaza (sin tolerancia). Valorar un leeway pequeño de 5 a 10 s; hoy el comportamiento es estricto y queda como está.
- La base solo se protege con el bloqueo advisory y el índice único; no hay `CHECK` de `estado` ni `paso`, ni índice parcial de "una compra activa por usuario". Añadirlos exigiría una migración nueva: decisión L3, no tomada.
- No hay `connect_timeout` en la conexión PostgreSQL: con un host que descarta paquetes en vez de rechazar, `/ready` podría tardar. No se probó.
- `ApiError` (401/422) se registra como error en el log de Laravel. Es solo ruido; no se cambió.
- `GET /usuario/{id}` no pagina. Hoy devuelve todos los pedidos del titular.
- Las pruebas de PostgreSQL usan una única base compartida y limpian sus propias filas. No ejecutar contra una base real.

## Archivos
- Nuevos: `app/Pedidos/BaseNoDisponible.php`, `tests/Feature/QaHostilTest.php`, `tests/Support/CompraWorker.php`, `QA-INFORME.md`.
- Modificados: `bootstrap/app.php`, `app/Pedidos/Controlador.php`.
