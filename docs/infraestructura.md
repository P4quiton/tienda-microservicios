# Infraestructura de bases de datos

## 1. Objetivo

Proporcionar una infraestructura de bases de datos reproducible, persistente y con autenticación para los microservicios de la plataforma de comercio electrónico.

La infraestructura utiliza Docker Compose para facilitar la configuración del entorno de desarrollo y la posterior migración hacia Kubernetes.

## 2. Tecnologías

| Tecnología | Versión |
|---|---|
| PostgreSQL | 17, imagen Alpine |
| MongoDB | 8.0 |
| Docker Compose | V2 o posterior compatible con la configuración |
| PowerShell | Generación de credenciales en Windows |
| SCRAM-SHA-256 | Autenticación de PostgreSQL |

## 3. Distribución de bases de datos

Se utiliza una instancia compartida de PostgreSQL con siete bases de datos independientes y una instancia de MongoDB para el servicio de Reseñas.

| Microservicio | Motor | Base de datos | Usuario |
|---|---|---|---|
| Usuarios | PostgreSQL | db_usuarios | usr_usuarios |
| Productos | PostgreSQL | db_productos | usr_productos |
| Envíos | PostgreSQL | db_envios | usr_envios |
| Inventario | PostgreSQL | db_inventario | usr_inventario |
| Carrito | PostgreSQL | db_carrito | usr_carrito |
| Pedidos | PostgreSQL | db_pedidos | usr_pedidos |
| Pagos | PostgreSQL | db_pagos | usr_pagos |
| Reseñas | MongoDB | db_resenas | usr_resenas |

Cada microservicio es responsable de administrar su propia información. La comunicación entre dominios debe realizarse mediante las APIs correspondientes, evitando consultas directas a las bases de otros servicios.

## 4. Estructura de archivos

```text
infra/
├── postgres/
│   ├── pg_hba.conf
│   └── init/
│       └── 01-create-databases.sh
└── mongodb/
    └── init/
        └── 01-create-users.js

scripts/
└── init-env.ps1

docker-compose.yml
compose.init-test.yaml
.env.example
```

## 5. Inicialización del entorno

### Requisitos

- Docker instalado y ejecutándose.
- Docker Compose disponible.
- Repositorio actualizado.
- PowerShell para ejecutar el generador de credenciales proporcionado.

### Generación de credenciales

Desde la raíz del repositorio:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\init-env.ps1
```

El script genera contraseñas aleatorias mediante un generador criptográficamente seguro.

El archivo `.env` generado es local y no debe compartirse ni subirse al repositorio.

El script no sobrescribe archivos `.env` existentes.

En otros sistemas operativos se puede crear un archivo `.env` a partir de `.env.example`, sustituyendo los valores `REPLACE_ME` por secretos aleatorios independientes.

### Iniciar infraestructura

```bash
docker compose config --quiet
docker compose pull
docker compose up -d --wait --wait-timeout 180
docker compose ps
```

Ambos servicios deberán aparecer con estado healthy.

## 6. Configuración de conexiones

### Desarrollo desde el equipo anfitrión

| Motor | Host | Puerto predeterminado |
|---|---|---|
| PostgreSQL | 127.0.0.1 | 15432 |
| MongoDB | 127.0.0.1 | 27017 |

Los puertos publicados pueden modificarse mediante `POSTGRES_HOST_PORT` y `MONGO_HOST_PORT`.

### Desarrollo dentro de Docker

| Motor | Host | Puerto |
|---|---|---|
| PostgreSQL | postgres | 5432 |
| MongoDB | mongodb | 27017 |

Las conexiones entre contenedores se realizan mediante la red `red-tienda`.

Los puertos internos no deben modificarse por conflictos de puertos en el equipo anfitrión.

### Credenciales por servicio

Para conectarse a PostgreSQL, cada microservicio deberá utilizar su usuario, su base de datos y la contraseña correspondiente:

- POSTGRES_USUARIOS_PASSWORD
- POSTGRES_PRODUCTOS_PASSWORD
- POSTGRES_ENVIOS_PASSWORD
- POSTGRES_INVENTARIO_PASSWORD
- POSTGRES_CARRITO_PASSWORD
- POSTGRES_PEDIDOS_PASSWORD
- POSTGRES_PAGOS_PASSWORD

Para MongoDB, el servicio de Reseñas utilizará:

- Usuario: usr_resenas
- Base de datos: db_resenas
- Base de autenticación: db_resenas
- Contraseña: valor de MONGO_RESENAS_PASSWORD

Las credenciales administrativas no deben utilizarse desde los microservicios.

## 7. Seguridad

### PostgreSQL

- Autenticación mediante SCRAM-SHA-256.
- Configuración explícita mediante pg_hba.conf.
- Eliminación de reglas de autenticación trust.
- Autenticación obligatoria mediante contraseña en conexiones locales y TCP.
- Usuarios independientes para cada microservicio.
- Restricción de acceso a bases de datos ajenas.
- Usuarios de aplicación sin privilegios de superusuario.
- Restricción de creación de roles y bases de datos.
- Rechazo de conexiones de replicación física.
- Healthcheck mediante consulta autenticada.

### MongoDB

- Autenticación habilitada.
- Usuario administrativo independiente.
- Usuario usr_resenas con rol readWrite limitado a db_resenas.
- Restricción de acceso a operaciones administrativas.
- Healthcheck autenticado.

### Red y credenciales

- Publicación de puertos limitada a localhost.
- Comunicación entre contenedores mediante red interna.
- Exclusión de archivos .env mediante .gitignore.
- Contraseñas independientes y aleatorias por servicio.
- Archivos de inicialización montados en modo de solo lectura.

Estas medidas corresponden al entorno de desarrollo. Para producción se deberán considerar mecanismos adicionales, como TLS, gestión externa de secretos, respaldos y políticas de red.

## 8. Persistencia de datos

La información se conserva utilizando los siguientes volúmenes Docker:

- postgres_data
- mongodb_data
- mongodb_config

Los contenedores pueden detenerse, reiniciarse o recrearse sin eliminar la información almacenada en dichos volúmenes.

Los scripts de inicialización solamente se ejecutan automáticamente cuando los directorios de datos están vacíos.

Modificar contraseñas en el archivo .env después de la inicialización no cambia automáticamente las contraseñas existentes en los motores de bases de datos.

Para detener la infraestructura conservando los datos:

```bash
docker compose down
```

No utilizar `docker compose down -v` sobre el entorno principal, salvo que se pretenda eliminar permanentemente sus datos.

## 9. Entorno independiente de pruebas

El archivo compose.init-test.yaml permite inicializar una infraestructura temporal con una red y volúmenes independientes.

```bash
docker compose -p tienda-init-test -f docker-compose.yml -f compose.init-test.yaml up -d --wait --wait-timeout 180
```

Este entorno no publica puertos en el equipo anfitrión.

Para eliminar exclusivamente los recursos temporales:

```bash
docker compose -p tienda-init-test -f docker-compose.yml -f compose.init-test.yaml down -v
```

## 10. Pruebas realizadas

Se verificaron los siguientes aspectos:

- Inicialización automática de PostgreSQL y MongoDB desde volúmenes vacíos.
- Creación de ocho bases de datos.
- Creación de usuarios independientes.
- Autenticación correcta de los siete usuarios PostgreSQL.
- Rechazo de contraseñas incorrectas.
- Rechazo de conexiones locales sin contraseña en PostgreSQL.
- Restricción de conexiones entre bases de datos ajenas en los casos probados.
- Restricción de privilegios administrativos.
- Autenticación y autorización del usuario de Reseñas.
- Conectividad TCP desde el equipo anfitrión.
- Escritura y lectura de registros PostgreSQL.
- Escritura y lectura de documentos MongoDB.
- Conservación de datos después de recrear los contenedores.

### Incidencias resueltas

**Conflicto del puerto 5432**

Se detectó una instalación local de PostgreSQL 18 utilizando el puerto 5432. Se implementaron puertos externos configurables y se estableció 15432 como puerto predeterminado para PostgreSQL en Docker.

**Autenticación local mediante trust**

Durante las pruebas se detectó que PostgreSQL permitía conexiones locales con contraseñas incorrectas. Se implementó un archivo pg_hba.conf personalizado para exigir autenticación SCRAM-SHA-256.

Posteriormente se repitieron las pruebas sobre la instancia existente y sobre una instalación nueva.

**Persistencia de información**

Se almacenaron registros de prueba en PostgreSQL y MongoDB. Después de recrear completamente los contenedores, se comprobó que los datos permanecieron disponibles.

## 11. Estado de implementación

La infraestructura inicial de bases de datos fue implementada y validada en el entorno de desarrollo.

La incorporación de los contenedores de las APIs, el frontend Angular y el despliegue mediante Kubernetes se realizará en las siguientes etapas del proyecto.