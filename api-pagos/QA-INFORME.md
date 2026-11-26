# QA-INFORME: api-pagos (puerto 8007)

Fecha: 2026-11-26. Alcance: ataque "QA hostil" al servicio y correccion de lo que fallo. Clasificacion L3 (dinero y controles de seguridad).
Sin git, sin docker build, sin cambios en docs/ ni en otros servicios. Datos ficticios; claves RSA generadas en memoria en cada ejecucion.

## Entorno y comandos
- Maven: no hay `mvn` en el PATH. Se uso Maven 3.9.11 ya descomprimido en `/tmp/tienda-pagos-maven.8R9aeV/` con el cache `/mnt/disco/desarrollo-local/.m2/repository` en modo `-o` (offline, sin descargas). Java 21.0.11 local.
- PostgreSQL 17 temporal: `docker run --rm -d --name mojarra-pg-pagos -p 55437:5432 --tmpfs /var/lib/postgresql/data -e POSTGRES_PASSWORD=<aleatoria> postgres:17`; al terminar `docker stop mojarra-pg-pagos` (solo ese contenedor).
- Pruebas: `PAGOS_TEST_DB_PASSWORD=<pwd> mvn -o -B -Dmaven.repo.local=/mnt/disco/desarrollo-local/.m2/repository test` (URL/usuario opcionales: `PAGOS_TEST_DB_URL`, `PAGOS_TEST_DB_USER`; por defecto `jdbc:postgresql://localhost:55437/postgres`, `postgres`). Sin `PAGOS_TEST_DB_PASSWORD` las pruebas con BD se omiten (el build sigue verde).

## Resultados de pruebas
| Momento | Resultado real |
|---|---|
| Linea base (codigo original) | 10 pruebas, 0 fallos (3 clases, todas con mocks, ninguna con BD real) |
| Suite hostil contra codigo ORIGINAL | 85 ejecutadas: 8 fallos + 2 errores. Entre ellos 6 fallos reales de producto (ver hallazgos 1-5); 2 eran errores de mis expectativas ("null" es JSON valido; HTTP recorta espacios en cabeceras) y se corrigieron en la prueba, no en el producto |
| Tras los arreglos | 86 ejecutadas, 0 fallos, 0 errores, 0 omitidas, BUILD SUCCESS (`Tests run: 86, Failures: 0, Errors: 0, Skipped: 0`) |
| Sin variable de BD | `Tests run: 13, Failures: 0, Errors: 0, Skipped: 1`, BUILD SUCCESS |

Desglose final: PaymentAccessConfigTest 1, PagosControllerTest 5, PaymentAccessHttpTest 3, PaymentAccessTest 2 (las 10 originales intactas + 1 nueva), ApiHostilTest 68, ConcurrenciaTest 5, ResilienciaTest 2.

Salida real de la fallida (extracto, codigo original):
```
duplicateJsonKeysAreRejected  expected: <400> but was: <201>   (monto "999.00", ultima clave gana)
hugeBodiesAreRejectedNotProcessed expected: <400> but was: <422> (2 MB leidos y parseados completos)
malformedJsonWithoutCredentialsIs401 expected: <401> but was: <400>
wrongContentType... {"timestamp":...,"status":415,"error":"Unsupported Media Type","path":...}  (no es el sobre del contrato)
ResilienciaTest: Failed to load ApplicationContext (BD caida al arrancar => el proceso muere)
```

## Hallazgos

| # | Sev. | Hallazgo | Arreglo | Prueba de regresion |
|---|---|---|---|---|
| 1 | Alta | BD caida AL ARRANCAR: Flyway lanzaba excepcion y el contexto Spring moria; `/health` no existia ("/health vive" incumplido; en K8s = crash-loop sin diagnostico) | `MigracionResiliente`: si migrar falla, el proceso arranca, `/ready` da 503 y un hilo reintenta cada 3 s hasta migrar (Flyway usa bloqueo en BD, seguro con replicas) | `ResilienciaTest.applicationStartsAndHealthLivesWhileReadyAndPaymentsReport503` |
| 2 | Alta (DoS) | Sin limite de cuerpo: 2 MB (o JSON profundo) se leian y parseaban enteros antes de rechazarse | `CuerpoJson`: maximo 4096 bytes leidos (no confia en Content-Length) -> 400 | `hugeBodiesAreRejectedNotProcessed` |
| 3 | Media | JSON malformado/cuerpo enorme se evaluaba ANTES que la autenticacion: un anonimo recibia 400 en vez de 401 y obligaba al servidor a parsear | El cuerpo se lee manualmente despues de `requirePedidos` y de validar `Idempotency-Key` | `malformedJsonWithoutCredentialsIs401`, `hugeBodyWithoutCredentialsIs401NotReadOrParsed` |
| 4 | Media | Claves JSON duplicadas aceptadas (ultima gana): ambiguedad entre parsers/proxy (p. ej. `monto` 1.00 vs 999.00) | `STRICT_DUPLICATE_DETECTION` -> 400 | `duplicateJsonKeysAreRejected` |
| 5 | Baja | 404 de ruta, 405 y 415 devolvian el JSON por defecto de Spring (con timestamp/path), no el sobre `{success,message,errors}`; excepciones no previstas no tenian manejador | `ApiErrorHandler`: mapea excepciones MVC a su estado con el sobre del contrato; resto => 500 generico sin traza (se registra en log) | `wrongContentTypeAndMethodsUseErrorEnvelope` |
| 6 | Media | Con BD caida, `POST /procesar` daba 500 (`CannotCreateTransactionException` no es `DataAccessException`) | Manejador tambien para `TransactionException` -> 503 | `ResilienciaTest` (POST y GET con BD caida => 503 sin detalles JDBC) |
| 7 | Media | Con una BD que acepta TCP pero no responde, `/ready` y los pagos se colgaban indefinidamente (sin timeouts del driver) | `connectTimeout=2`, `loginTimeout=2`, `socketTimeout=10` s en `application.properties` | Manual con `docker pause` (abajo); no automatizada |
| 8 | Baja (hardening) | Se podia configurar el mismo secreto para entrada y salida, rompiendo "un secreto por par" | `PaymentAccess` falla al arrancar si ambos son iguales y no vacios | `PaymentAccessConfigTest` (no se observo en rojo; es prueba de un guard nuevo) |
| 9 | Baja | Basura tras el JSON (`{...}{"x":1}`, `{...} texto`) se aceptaba silenciosamente | `FAIL_ON_TRAILING_TOKENS` -> 400 | `trailingGarbageAfterJsonIsRejected` (no se observo en rojo por separado) |

Decisiones a confirmar: cuerpo demasiado grande, Content-Type distinto de `application/json` y JSON invalido devuelven 400 (el contrato no define 413/415). El rechazo de Content-Type distinto de application/json es nuevo: Pedidos debe enviar `Content-Type: application/json`.

### Verificado sin hallazgos (la suite lo prueba y paso en el codigo original)
- Importes: rechaza numeros JSON, `10`, `10.5`, `10.555`, negativos, `0.00`, `1e3`, espacios, `NaN`, hex, digitos de ancho completo, 11 enteros, cadena vacia/null (422).
- UUID: nil, v1, variante invalida, sin guiones, con llaves/espacios, no v4 en `pedido_id`, `Idempotency-Key` y `sub` (422).
- Campos extra/faltantes, tipos erroneos, forma no objeto (422); JSON malformado (400).
- X-Service-Token: ausente, vacio, token de salida (otro par), mayusculas, prefijos/sufijos, por query string => 401. JWT de usuario (cliente o admin) en POST => 403.
- JWT RS256: payload manipulado (cliente->admin), sin firma, `alg=none`, PlainJWT, HS256 firmado con la clave publica, clave ajena, expirado, `iat`/`nbf` futuros, vida >1 h, sin exp/iat/aud/iss/sub/role, aud/iss erroneos, sub no UUID v4, rol invalido => 401.
- Titularidad: A sobre pedido de B => 403; B, admin y servicio => 200; Pedidos caido/500/302/401 => 503 (nunca permite); pedido desconocido => 404.
- Idempotencia: misma clave+payload => mismo 201 (5 reintentos identicos); misma clave con otro monto/metodo/pedido => 409; otra clave mismo pedido => 409; pedido en mayusculas no duplica; rechazo simulado se persiste una vez (201).
- Concurrencia (40 hilos): misma clave y payload => 40x201 con un unico id y 1 fila; claves distintas mismo pedido => exactamente 1x201 y 39x409; misma clave con payloads distintos => 1 ganador; 60 pagos distintos en paralelo => 60x201 sin agotar el pool.
- Inyeccion SQL en `pedido_id`, `monto`, `metodo_pago`, path y `Idempotency-Key`: todo 422/404, tabla `pagos` intacta (todo parametrizado).
- BD: CHECK de monto>0, metodo y estado; Flyway aplicado dos veces => 0 migraciones la segunda y `validate()` OK.

### Prueba manual con el JAR real (BD pausada con `docker pause mojarra-pg-pagos`)
```
--- BD pausada desde el arranque
{"status":"ok","service":"api-pagos"} [200 0.10s]          <- /health
{"status":"unavailable","service":"api-pagos"} [503 3.02s]  <- /ready
{"success":false,"message":"Persistencia no disponible","errors":{}} [503 6.00s]  <- POST /procesar
--- BD recuperada (docker unpause)  /health [200]  /ready [200]  (log: "Migracion aplicada tras reintento")
--- pausa en caliente: /health [200 0.003s]  /ready [503 5.02s]  ; tras unpause /ready [200]
```
Antes del arreglo 7, en esta misma situacion `/ready` y el POST superaban 5-8 s sin respuesta (curl: codigo 000).

## Archivos tocados (solo api-pagos)
Codigo: `CuerpoJson.java` (nuevo), `MigracionResiliente.java` (nuevo), `PagosController.java`, `ApiError.java`, `PaymentAccess.java`, `application.properties`.
Pruebas: `PaymentAccessConfigTest.java`, `qa/QaBase.java`, `qa/ApiHostilTest.java`, `qa/ConcurrenciaTest.java`, `qa/ResilienciaTest.java`. No se modifico ninguna de las 10 pruebas originales ni `docs/api/*.yaml`.

## NO VERIFICADO / pendientes
- `docker build` de la imagen: no ejecutado (prohibido). El Dockerfile no se toco; se compilo y ejecuto el JAR con Maven local, no la imagen.
- Rate limiting 429 (el contrato lo lista): el servicio no lo implementa; no se probo ni se anadio (decision de diseno: mejor en Nginx/proxy).
- `/ready` tarda hasta ~5 s con la BD colgada (no caida): configurar `timeoutSeconds >= 6` en la sonda de Kubernetes o bajar `hikari.connection-timeout`. No se reviso k8s/.
- `PaymentAccess.requireOwner` no comprueba que `data.id` de Pedidos coincida con el pedido pedido (defensa en profundidad opcional).
- Sin JWT_PUBLIC_KEY_PATH o tokens de servicio vacios el servicio arranca y responde 401 a todo en silencio; podria registrar un aviso al arrancar.
- Rendimiento/carga sostenida (k6) no ejecutada; solo 60 pagos concurrentes locales.
- Mockito imprime avisos de agente dinamico en JDK 21 (no afectan resultados).
- El cache Maven `/mnt/disco/desarrollo-local/.m2` se uso en modo lectura (`-o`).

## Contrato 1.1.0
Revision frente a `docs/api/pagos.yaml` 1.1.0 (rama upstream/docs/checkout-contracts).
- Verificado: el codigo previo YA cumplia lo exigido: fila unica con resultado + `idempotency_key` + `request_hash` (V1, UNIQUE por `pedido_id` y por clave, insert atomico); misma clave y payload devuelve el original; payload incompatible con otra clave devuelve 409; un reintento tras timeout no crea un segundo efecto. No hizo falta migracion nueva ni cambio de codigo (no hay estado "en curso": el efecto simulado y su registro son una sola transaccion).
- Regresion rojo/verde: no fue posible observar rojo, porque no habia defecto. Se anadio `qa/Contrato110Test.java` (4 pruebas) que fija el comportamiento: fila unica por pedido, 409 con otra clave y original intacto, reintento tras abandono del cliente (timeout de 1 ms) sin segundo efecto, GET 404 sin pago.
- Documentado en README: 404 de `GET /api/pagos/pedido/{id}` no garantiza ausencia de solicitud en curso.
- Pruebas (PG17 temporal): antes 86 verdes; despues 90 verdes (86 + 4).
- Pendiente: la prueba de timeout es un abandono del cliente, no un corte real de red/BD a mitad de transaccion; no se probo reinicio del proceso entre intentos.
