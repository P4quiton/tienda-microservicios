# Decisiones técnicas

Acuerdos de arquitectura aprobados por el coordinador; compartir con el equipo. Versiones mayores objetivo, no dependencias verificadas ni instaladas todavía.

| Servicio | Stack | BD |
|---|---|---|
| Usuarios, Productos, Pedidos | PHP 8.5 / Laravel 13 | PostgreSQL 17 |
| Envíos | Python 3.12 / FastAPI | PostgreSQL 17 |
| Inventario | Go 1.26 / Gin | PostgreSQL 17 |
| Carrito | Node 24 LTS / Express 5 | PostgreSQL 17 |
| Pagos | Java 21 / Spring Boot 3.5 | PostgreSQL 17 |
| Reseñas | Python 3.12 / FastAPI | MongoDB 8.0 |
| Frontend | Angular 21 / Node 24 LTS | Ninguna |

Fijar versiones patch y lockfiles al inicializar y comprobar compatibilidad, build y soporte. Cada contenedor escucha en 0.0.0.0 y puerto del README. BD `db_<servicio>`, usuario `usr_<servicio>`. PostgreSQL: revocar CONNECT de PUBLIC en bases de aplicación, otorgar solo al propietario autorizado; roles sin privilegios administrativos. MongoDB: rol limitado a db_resenas. Migraciones y datos de prueba propios. No usar latest, no copiar secretos, preferir multietapa y usuario no root.

UUID v4, JWT RS256, JSON estándar, importes decimal string en MXN, HTTP REST, Nginx como proxy, Pedidos como coordinador. No Kafka/RabbitMQ ni pasarela real. Health y readiness obligatorios. GitHub Container Registry opcional al integrar; inicialmente imágenes locales.

Entorno verificado: Docker Desktop 4.100.1, Engine 29.9.3, Compose 5.7.1, Kubernetes/kubectl 1.36.1 (kubeadm). Espacio libre observado: 27.29 GB; vigilar crecimiento. No se exige idéntica versión de Docker a todos los compañeros.
