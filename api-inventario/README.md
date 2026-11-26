# API Inventario

Servicio de inventario con Go 1.26 y Gin. El puerto predeterminado es `8004`; la configuración se carga desde variables de entorno. La persistencia y los endpoints de negocio se incorporarán en los siguientes cambios.

## Configuración local

Copia `.env.example` a `.env` y completa las credenciales locales. Para cargarlo en Bash desde esta carpeta:

```bash
set -a
. ./.env
set +a
```

Ejecuta el servidor:

```bash
go run ./cmd/api
```

## Estado del servicio

- `GET /health`: comprueba que el proceso responde.
- `GET /ready`: devolverá disponibilidad cuando PostgreSQL quede conectado.

El contrato completo está en [`../docs/api/inventario.yaml`](../docs/api/inventario.yaml).
