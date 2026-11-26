# Contribución

Desde main actualizado, crear una rama por servicio: feature/api-usuarios, feature/api-productos, feature/api-envios, feature/api-inventario, feature/api-carrito, feature/api-pedidos, feature/api-pagos, feature/api-resenas, feature/frontend-tienda. Infraestructura: feature/docker-compose y feature/kubernetes.

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/api-productos
```

Trabajar solo en la carpeta asignada; eliminar .gitkeep antes de inicializar si es necesario. Coordinar cambios de contratos mediante PR separado. Cada servicio incluye README con comandos, .env.example sin secretos, Dockerfile, .dockerignore, lockfiles, migraciones, seeds y pruebas. Verificar health/ready y endpoints, build de imagen y pruebas negativas de autorización. No modificar Compose central sin coordinar con integrante 1.

Antes de subir: git fetch origin, comparar e integrar origin/main si corresponde, probar, revisar git diff y git status. Commit descriptivo, push de rama y PR hacia main con resumen, pruebas y evidencia. No hacer push directo a main. Todos revisan sus módulos y participan en integración final.

Integrante 4 puede empezar con mocks ajustados a OpenAPI; no debe esperar a que todas las APIs estén listas. Si cambia un campo o ruta, actualizar contrato y avisar antes de fusionar.
