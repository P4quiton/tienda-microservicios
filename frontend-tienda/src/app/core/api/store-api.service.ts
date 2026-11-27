import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import {
  Address,
  ApiSuccess,
  Cart,
  CreateOrderRequest,
  InventoryAvailability,
  LoginRequest,
  LoginResponse,
  Order,
  PaymentReceipt,
  Product,
  ProductPage,
  ProductReviews,
  RegisterRequest,
  Review,
  ShipmentTracking,
  ShippingQuote,
  UserProfile,
} from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class StoreApiService {
  private readonly http = inject(HttpClient);

  listProducts(options: { q?: string; categoria?: string; pagina?: number; limite?: number } = {}): Observable<ProductPage> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(options)) {
      if (value !== undefined && value !== '') params = params.set(key, String(value));
    }
    return this.http.get<ApiSuccess<ProductPage>>('/api/productos', { params }).pipe(map(({ data }) => data));
  }

  getProduct(id: string): Observable<Product> {
    return this.http.get<ApiSuccess<Product>>(`/api/productos/${encodeURIComponent(id)}`).pipe(map(({ data }) => data));
  }

  getAvailability(productId: string): Observable<InventoryAvailability> {
    return this.http.get<ApiSuccess<InventoryAvailability>>(`/api/inventario/${encodeURIComponent(productId)}`).pipe(map(({ data }) => data));
  }

  getReviews(productId: string): Observable<ProductReviews> {
    return this.http.get<ApiSuccess<ProductReviews>>(`/api/resenas/producto/${encodeURIComponent(productId)}`).pipe(map(({ data }) => data));
  }

  createReview(input: { producto_id: string; calificacion: number; comentario: string }): Observable<Review> {
    return this.http.post<ApiSuccess<Review>>('/api/resenas', input).pipe(map(({ data }) => data));
  }

  getCart(userId: string): Observable<Cart> {
    return this.http.get<ApiSuccess<Cart>>(`/api/carrito/${encodeURIComponent(userId)}`).pipe(map(({ data }) => data));
  }

  addToCart(userId: string, productId: string, quantity: number): Observable<Cart> {
    return this.http.post<ApiSuccess<Cart>>(
      `/api/carrito/${encodeURIComponent(userId)}/agregar`,
      { producto_id: productId, cantidad: quantity },
      { headers: { 'Idempotency-Key': crypto.randomUUID() } },
    ).pipe(map(({ data }) => data));
  }

  quoteShipping(codigo_postal: string, cantidad: number): Observable<ShippingQuote> {
    return this.http.post<ApiSuccess<ShippingQuote>>('/api/envios/cotizar', { codigo_postal, cantidad }).pipe(map(({ data }) => data));
  }

  createOrder(input: CreateOrderRequest, idempotencyKey: string = crypto.randomUUID()): Observable<Order> {
    return this.http.post<ApiSuccess<Order>>('/api/pedidos', input, {
      headers: { 'Idempotency-Key': idempotencyKey },
    }).pipe(map(({ data }) => data));
  }

  getOrderHistory(userId: string): Observable<Order[]> {
    return this.http.get<ApiSuccess<Order[]>>(`/api/pedidos/usuario/${encodeURIComponent(userId)}`).pipe(map(({ data }) => data));
  }

  getOrder(orderId: string): Observable<Order> {
    return this.http.get<ApiSuccess<Order>>(`/api/pedidos/${encodeURIComponent(orderId)}`).pipe(map(({ data }) => data));
  }

  getPaymentReceipt(orderId: string): Observable<PaymentReceipt> {
    return this.http.get<ApiSuccess<PaymentReceipt>>(`/api/pagos/pedido/${encodeURIComponent(orderId)}`).pipe(map(({ data }) => data));
  }

  trackShipment(guide: string): Observable<ShipmentTracking> {
    return this.http.get<ApiSuccess<ShipmentTracking>>(`/api/envios/rastreo/${encodeURIComponent(guide)}`).pipe(map(({ data }) => data));
  }

  register(input: RegisterRequest): Observable<UserProfile> {
    return this.http.post<ApiSuccess<UserProfile>>('/api/usuarios/registro', input).pipe(map(({ data }) => data));
  }

  login(input: LoginRequest): Observable<LoginResponse> {
    return this.http.post<ApiSuccess<LoginResponse>>('/api/usuarios/login', input).pipe(map(({ data }) => data));
  }

  updateProfile(id: string): Observable<UserProfile> {
    return this.http.get<ApiSuccess<UserProfile>>(`/api/usuarios/${encodeURIComponent(id)}`).pipe(map(({ data }) => data));
  }

  // Shipping quote accepts Address only at checkout; Pedido recalculates it on the server.
  quoteAddress(address: Address, quantity: number): Observable<ShippingQuote> {
    return this.quoteShipping(address.codigo_postal, quantity);
  }
}
