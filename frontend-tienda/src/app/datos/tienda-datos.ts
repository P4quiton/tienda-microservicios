import { InjectionToken } from '@angular/core';
import { CotizacionEnvio, Direccion, ItemCarrito, MetodoPago, Pedido, Producto, ResumenResenas } from './models';

/**
 * PUNTO DE INTEGRACIÓN. Las vistas solo dependen de este contrato.
 * Hoy se provee MockTiendaDatos (src/app/mock); la capa HTTP/auth real debe
 * implementar esta misma interfaz y registrarse en app.config.ts.
 * Cada método corresponde a un endpoint de docs/api (indicado en el comentario).
 */
export interface TiendaDatos {
  /** GET /api/productos?busqueda&categoria&pagina&limite */
  listarProductos(filtro: { busqueda?: string; categoria?: string }): Promise<Producto[]>;
  /** GET /api/productos/{id} */
  obtenerProducto(id: string): Promise<Producto>;
  /** GET /api/inventario/{producto_id} → disponibles */
  disponibles(productoId: string): Promise<number>;
  /** GET /api/resenas/producto/{producto_id} */
  resenas(productoId: string): Promise<ResumenResenas>;
  /** POST /api/resenas */
  crearResena(r: { producto_id: string; calificacion: number; comentario: string }): Promise<void>;
  /** GET /api/carrito/{usuario_id} */
  carrito(): Promise<ItemCarrito[]>;
  /** POST /api/carrito/{usuario_id}/agregar */
  agregarAlCarrito(item: ItemCarrito): Promise<ItemCarrito[]>;
  /** POST /api/envios/cotizar */
  cotizarEnvio(codigoPostal: string, cantidad: number): Promise<CotizacionEnvio>;
  /** POST /api/pedidos (Pedidos coordina inventario, pago, envío y vaciado del carrito) */
  crearPedido(direccion: Direccion, metodo: MetodoPago): Promise<Pedido>;
  /** Conserva la misma clave durante reintentos inciertos; reinicia al iniciar un intento nuevo. */
  nuevoIntentoCheckout(): void;
  /** GET /api/pedidos/usuario/{usuario_id} */
  misPedidos(): Promise<Pedido[]>;
}

export const TIENDA_DATOS = new InjectionToken<TiendaDatos>('TIENDA_DATOS');
