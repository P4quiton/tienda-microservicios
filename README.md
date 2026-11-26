# Tienda Microservicios

Práctica académica de arquitectura Multi-Stack: ocho APIs REST, frontend Angular, Docker Compose y ampliación Kubernetes local.

**Estado:** configuración inicial; todavía no hay aplicaciones implementadas ni despliegue de la tienda. Docker y Kubernetes se verificaron en el equipo del coordinador.

| Módulo | Responsable | Puerto |
|---|---|---:|
| api-usuarios | Integrante 1 | 8001 |
| api-productos | Integrante 2 | 8002 |
| api-envios | Integrante 3 | 8003 |
| api-inventario | Integrante 2 | 8004 |
| api-carrito | Integrante 3 | 8005 |
| api-pedidos | Integrante 3 | 8006 |
| api-pagos | Integrante 3 | 8007 |
| api-resenas | Integrante 2 | 8008 |
| frontend-tienda | Integrante 4 | 4200 |

Integrante 1: repositorio, infraestructura, Compose, Kubernetes y seguridad transversal. Cada responsable entrega código, pruebas, Dockerfile, .dockerignore y documentación.

## Inicio
```bash
git clone https://github.com/P4quiton/tienda-microservicios.git
cd tienda-microservicios
```
Leer los acuerdos antes de inicializar frameworks. Eliminar `.gitkeep` de la carpeta del servicio si el generador exige un directorio vacío. No borrar otros archivos.

## Documentación
- [Arquitectura](docs/arquitectura.md)
- [Decisiones técnicas](docs/decisiones-tecnicas.md)
- [Contratos de API](docs/contratos-api.md) y [OpenAPI por servicio](docs/api/)
- [Seguridad](docs/seguridad.md)
- [Flujo de compra](docs/flujo-compra.md)
- [Contribución](docs/contribucion.md)

## Ejecución futura
`docker compose up --build` será el comando de ejecución una vez integrados los servicios y el archivo Compose. Kubernetes será un despliegue alternativo, no un requisito para desarrollar cada API. No ejecutar ambos entornos completos simultáneamente si faltan recursos.
