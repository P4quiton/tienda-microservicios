# API Reseñas

Servicio independiente para reseñas de productos, preparado con FastAPI, Python 3.12 y MongoDB 8.0. El puerto de desarrollo es `8008`; la configuración se obtiene de variables de entorno.

## Configuración

Instala Python 3.12 y crea un entorno virtual. Conserva cualquier `.env` existente; crea uno desde `.env.example` solo si aún no tienes configuración local. Instala las dependencias de ejecución con:

```bash
pip install -r requirements.lock
```

La infraestructura del monorepo proporciona MongoDB. El servicio utiliza la base `db_resenas` y el usuario `usr_resenas`; configura `MONGO_PASSWORD` con la credencial local generada para Reseñas. No subas `.env`, contraseñas, tokens ni claves al repositorio.

Consulta el contrato vigente en [`../docs/api/resenas.yaml`](../docs/api/resenas.yaml). Los endpoints y las instrucciones completas de ejecución se documentarán conforme se incorporen en los siguientes cambios.
