import { ApiError } from './errors.js';

export function catalogAvailability({ productsUrl, inventoryUrl, fetchJson = fetch }) {
  async function lookup(base, path, productId) {
    try {
      const response = await fetchJson(new URL(path + productId, base), {
        signal: AbortSignal.timeout(1000),
        redirect: 'error',
      });
      if (response.status === 404) return null;
      if (!response.ok) throw new Error('Respuesta no exitosa');
      const body = await response.json();
      if (body.success !== true || !body.data) throw new Error('Respuesta inválida');
      return body.data;
    } catch {
      throw new ApiError(503, 'No fue posible comprobar el producto o su disponibilidad');
    }
  }

  return async (productId) => {
    const product = await lookup(productsUrl, '/api/productos/', productId);
    if (!product) throw new ApiError(404, 'Producto inexistente');
    if (product.id !== productId) throw new ApiError(503, 'Respuesta de catálogo inválida');
    const inventory = await lookup(inventoryUrl, '/api/inventario/', productId);
    if (!inventory) return 0;
    if (inventory.producto_id !== productId ||
        !Number.isSafeInteger(inventory.disponibles) || inventory.disponibles < 0) {
      throw new ApiError(503, 'Respuesta de inventario inválida');
    }
    return inventory.disponibles;
  };
}
