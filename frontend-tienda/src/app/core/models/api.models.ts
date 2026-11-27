export interface ApiSuccess<T> {
  success: true;
  message: string;
  data: T;
}

export interface ApiFailure {
  success: false;
  message: string;
  errors: Record<string, string[]>;
}

export interface Product {
  id: string;
  nombre: string;
  descripcion: string;
  precio: string;
  categoria: string;
  imagen_url: string;
}

export interface ProductPage {
  items: Product[];
  total: number;
  pagina: number;
  limite: number;
}

export interface InventoryAvailability {
  producto_id: string;
  disponibles: number;
}

export interface Review {
  id: string;
  producto_id: string;
  usuario_id: string;
  calificacion: number;
  comentario: string;
  creado_en: string;
}

export interface ProductReviews {
  items: Review[];
  promedio: number | null;
  total: number;
}

export interface CartItem {
  producto_id: string;
  cantidad: number;
  linea_id: string;
}

export interface Cart {
  usuario_id: string;
  items: CartItem[];
  version: number;
}

export interface Address {
  codigo_postal: string;
  calle: string;
  ciudad: string;
  estado: string;
}

export type PaymentMethod = 'tarjeta_simulada' | 'transferencia_simulada';
export type PaymentStatus = 'aprobado' | 'rechazado';
export type OrderStatus = 'pendiente' | 'pagado' | 'enviado' | 'cancelado';
export type ShipmentStatus = 'preparando' | 'en_transito' | 'entregado';

export interface OrderItem {
  producto_id: string;
  cantidad: number;
  precio_unitario: string;
}

export interface Order {
  id: string;
  usuario_id: string;
  items: OrderItem[];
  direccion: Address;
  costo_envio: string;
  total: string;
  estado: OrderStatus;
  creado_en: string;
  /** Campos previstos en el siguiente contrato de Pedidos; faltan en el despliegue actual. */
  guia?: string | null;
  pago_id?: string | null;
  metodo_pago?: PaymentMethod | null;
}

export interface ShippingQuote {
  costo_envio: string;
  dias_estimados: number;
}

export interface PaymentReceipt {
  id: string;
  pedido_id: string;
  monto: string;
  metodo_pago: PaymentMethod;
  estado: PaymentStatus;
  creado_en: string;
}

export interface ShipmentTracking {
  guia: string;
  pedido_id: string;
  estado: ShipmentStatus;
}

export interface UserProfile {
  id: string;
  nombre: string;
  correo: string;
  role: 'cliente' | 'admin';
}

export interface LoginResponse {
  access_token: string;
  token_type: 'Bearer';
  expires_in: number;
  usuario: UserProfile;
}

export interface RegisterRequest {
  nombre: string;
  correo: string;
  contrasena: string;
}

export interface LoginRequest {
  correo: string;
  contrasena: string;
}

export interface CreateOrderRequest {
  direccion: Address;
  metodo_pago: PaymentMethod;
}

export interface ApiProblem {
  status: number;
  message: string;
  errors: Record<string, string[]>;
  retryAfterSeconds?: number;
  uncertainOutcome: boolean;
}
