import { Injectable, inject } from '@angular/core';
import { firstValueFrom, Observable } from 'rxjs';
import { StoreApiService } from '../core/api/store-api.service';
import { SessionService } from '../core/auth/session.service';
import { toApiProblem } from '../core/api/api-error';
import { ComprobantePago, CotizacionEnvio, Direccion, ItemCarrito, MetodoPago, Pedido, Producto, RastreoEnvio, ResumenResenas } from './models';
import { TiendaDatos } from './tienda-datos';

/**
 * Adaptador entre la interfaz de las vistas y los contratos HTTP v1.
 * Usa exclusivamente rutas públicas o protegidas por el JWT del usuario;
 * nunca envía X-Service-Token desde el navegador.
 */
@Injectable()
export class HttpTiendaDatos implements TiendaDatos {
  private readonly api = inject(StoreApiService);
  private readonly session = inject(SessionService);
  private checkoutKey: string | null = null;
  private readonly cartAddKeys = new Map<string, string>();

  async listarProductos(filtro: { busqueda?: string; categoria?: string }): Promise<Producto[]> {
    const options = { q: filtro.busqueda, categoria: filtro.categoria, limite: 100 };
    const first = await this.execute(this.api.listProducts({ ...options, pagina: 1 }));
    const paginas = Math.ceil(first.total / first.limite);
    if (paginas <= 1) return first.items;
    const restantes = await Promise.all(Array.from({ length: paginas - 1 }, (_, index) =>
      this.execute(this.api.listProducts({ ...options, pagina: index + 2 })),
    ));
    return [ ...first.items, ...restantes.flatMap((page) => page.items) ];
  }

  async obtenerProducto(id: string): Promise<Producto> {
    return this.execute(this.api.getProduct(id));
  }

  async disponibles(productoId: string): Promise<number> {
    const result = await this.execute(this.api.getAvailability(productoId));
    return result.disponibles;
  }

  async resenas(productoId: string): Promise<ResumenResenas> {
    return this.execute(this.api.getReviews(productoId));
  }

  async crearResena(r: { producto_id: string; calificacion: number; comentario: string }): Promise<void> {
    await this.execute(this.api.createReview(r));
  }

  async carrito(): Promise<ItemCarrito[]> {
    const userId = this.requireUserId();
    const cart = await this.execute(this.api.getCart(userId));
    return cart.items.map(({ producto_id, cantidad }) => ({ producto_id, cantidad }));
  }

  async agregarAlCarrito(item: ItemCarrito): Promise<ItemCarrito[]> {
    const userId = this.requireUserId();
    const fingerprint = JSON.stringify([userId, item.producto_id, item.cantidad]);
    const key = this.cartAddKeys.get(fingerprint) ?? crypto.randomUUID();
    this.cartAddKeys.set(fingerprint, key);
    try {
      const cart = await this.execute(this.api.addToCart(userId, item.producto_id, item.cantidad, key));
      this.cartAddKeys.delete(fingerprint);
      return cart.items.map(({ producto_id, cantidad }) => ({ producto_id, cantidad }));
    } catch (error) {
      const problem = toApiProblem(error);
      // Un 503 o una desconexión deja incierto el resultado; el siguiente intento repite la clave.
      if (problem.status !== 503 && problem.status !== 0) this.cartAddKeys.delete(fingerprint);
      throw problem;
    }
  }

  async cotizarEnvio(codigoPostal: string, cantidad: number): Promise<CotizacionEnvio> {
    return this.execute(this.api.quoteShipping(codigoPostal, cantidad));
  }

  async crearPedido(direccion: Direccion, metodo: MetodoPago): Promise<Pedido> {
    this.checkoutKey ??= crypto.randomUUID();
    try {
      const pedido = await this.execute(this.api.createOrder({ direccion, metodo_pago: metodo }, this.checkoutKey));
      this.checkoutKey = null;
      return pedido;
    } catch (error) {
      const problem = toApiProblem(error);
      // Solo un 503 deja incierto el resultado y exige reusar la misma clave.
      if (!problem.uncertainOutcome) this.checkoutKey = null;
      throw problem;
    }
  }

  async misPedidos(): Promise<Pedido[]> {
    return this.execute(this.api.getOrderHistory(this.requireUserId()));
  }

  async comprobantePago(pedidoId: string): Promise<ComprobantePago> {
    return this.execute(this.api.getPaymentReceipt(pedidoId));
  }

  async rastrearEnvio(guia: string): Promise<RastreoEnvio> {
    return this.execute(this.api.trackShipment(guia));
  }

  /** Inicia explícitamente otro intento tras mostrar el resultado del anterior. */
  nuevoIntentoCheckout(): void {
    this.checkoutKey = null;
  }

  private requireUserId(): string {
    const userId = this.session.user()?.id;
    if (!userId || !this.session.accessToken) {
      throw new Error('Inicia sesión para consultar tu carrito o tus pedidos.');
    }
    return userId;
  }

  private async execute<T>(request: Observable<T>): Promise<T> {
    try {
      return await firstValueFrom(request);
    } catch (error) {
      throw toApiProblem(error);
    }
  }
}
