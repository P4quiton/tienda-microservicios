import { InjectionToken } from '@angular/core';
import { ComprobantePago, CotizacionEnvio, Direccion, ItemCarrito, MetodoPago, Pedido, Producto, RastreoEnvio, ResumenResenas } from './models';

/**
 * Las vistas solo dependen de este contrato; app.config.ts selecciona el
 * proveedor simulado o el adaptador HTTP según el modo de ejecución.
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
  /** GET /api/pagos/pedido/{pedido_id}; el endpoint valida que el pedido pertenezca al titular. */
  comprobantePago(pedidoId: string): Promise<ComprobantePago>;
  /** GET /api/envios/rastreo/{guia}; Envíos expone el estado del paquete sin alterar estado comercial del pedido. */
  rastrearEnvio(guia: string): Promise<RastreoEnvio>;
}

export const TIENDA_DATOS = new InjectionToken<TiendaDatos>('TIENDA_DATOS');
