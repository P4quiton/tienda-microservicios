# Seguridad

JWT RS256, clave privada solo en Usuarios, pública para verificación. Claims obligatorios sub (UUID), role (cliente/admin), iss=api-usuarios, aud=tienda-microservicios, iat y exp (60 minutos). Validar algoritmo explícito, firma, emisor, audiencia y vigencia. Argon2id para contraseñas; registro fuerza cliente, admin por seed controlado. Rate limiting en login. Nunca registrar tokens, contraseñas o datos sensibles.

Operaciones protegidas: verificar identidad y propiedad en backend, no confiar en guards de Angular. Token en memoria del frontend para el MVP; al recargar se vuelve a autenticar. No usar datos de tarjeta reales. HTTPS obligatorio fuera de entorno local.

Identidad entre servicios: `X-Service-Token`, secreto aleatorio independiente por par llamador/destino; el receptor compara en tiempo constante y asigna permisos a la identidad del llamador. Pedidos llama a inventario, carrito, envíos y pagos; Pagos y Envíos consultan Pedidos para verificar titularidad usando su propia identidad. No reutilizar el token de cliente como credencial interna. Si una consulta interna requiere conocer al titular, el servicio que recibe al usuario valida su JWT y compara sub con usuario_id devuelto por Pedidos. Nunca enviar secretos al navegador; proxy bloquea rutas internas y elimina encabezados X-Service-Token entrantes. PATCH estado solo para servicio interno expresamente autorizado (por definir antes de exponerlo); Pedidos actualiza su propio estado localmente.

Secrets de Kubernetes no equivalen a cifrado por sí solos: no guardar valores reales en Git ni en imágenes. `.env.example` solo nombres y marcadores. ConfigMap solo datos no sensibles. Bases no publicadas, credenciales de mínimo privilegio. Validar entradas y consultas parametrizadas. Errores sin stack traces.

## Seguridad de las bases de datos

La infraestructura de desarrollo utiliza usuarios independientes por microservicio, evitando el uso de credenciales administrativas desde las aplicaciones.

PostgreSQL exige autenticación SCRAM-SHA-256 mediante un archivo pg_hba.conf personalizado. No se permiten conexiones mediante el método trust.

Los usuarios PostgreSQL solamente tienen permisos sobre sus respectivas bases de datos y no cuentan con privilegios administrativos globales.

MongoDB utiliza autenticación obligatoria y un usuario con permisos readWrite limitados a db_resenas.

Los puertos publicados de ambos motores se restringen a localhost. La comunicación entre los contenedores se realiza mediante la red red-tienda.

Las contraseñas se generan mediante un generador criptográficamente seguro y se almacenan en archivos de entorno excluidos del control de versiones.

Se realizaron pruebas de autenticación, autorización, aislamiento entre bases de datos y persistencia de información.

Consultar [Infraestructura de bases de datos](infraestructura.md) para conocer las configuraciones y los procedimientos de validación.