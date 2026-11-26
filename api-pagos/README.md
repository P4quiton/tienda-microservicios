# API de pagos simulados

Java 21, Spring Boot 3.5 y PostgreSQL 17. La API escucha en el puerto 8007 y sigue el [contrato de Pagos](../docs/api/pagos.yaml).

Configura las variables de `.env.example` en tu entorno. `DATABASE_URL` puede sobrescribir la configuración `DB_*` mediante una URL JDBC. Monta la clave **pública** de Usuarios en formato PEM y configura su ruta en `JWT_PUBLIC_KEY_PATH`. Los tokens de entrada y salida corresponden a Pedidos → Pagos y Pagos → Pedidos, respectivamente. La migración Flyway se aplica al arrancar contra la base del servicio.

```sh
mvn test
mvn spring-boot:run
docker build -t api-pagos:local .
```

`/health` comprueba el proceso y `/ready` valida que la tabla de pagos esté disponible. Solo Pedidos puede solicitar un pago y debe enviar un UUID v4 en `Idempotency-Key`. Una transacción de PostgreSQL registra el resultado, la clave y el hash de la solicitud. La clave repetida con la misma solicitud devuelve el comprobante original. Una clave repetida con otra solicitud o un segundo intento con otra clave para el mismo pedido devuelve 409.

Para cubrir ambos resultados de integración, `tarjeta_simulada` aprueba y `transferencia_simulada` rechaza. Ambos resultados se registran y responden 201. El servicio acepta exclusivamente el identificador del pedido, el monto decimal como texto y uno de los métodos simulados.
