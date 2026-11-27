// Tipos alineados con docs/api/*.yaml (v1). Importes MXN como cadenas "0.00".

export type Monto = string;

export interface Producto {
  id: string;
  nombre: string;
  descripcion: string;
  precio: Monto;
  categoria: string;
  imagen_url: string;
}

export interface Resena {
  id: string;
  producto_id: string;
  usuario_id: string;
  calificacion: number;
  comentario: string;
  creado_en: string;
}

/** GET /api/resenas/producto/{id}: promedio es null sin reseñas. */
export interface ResumenResenas {
  items: Resena[];
  promedio: number | null;
  total: number;
}

export interface ItemCarrito {
  producto_id: string;
  cantidad: number;
}

export interface CotizacionEnvio {
  costo_envio: Monto;
  dias_estimados: number;
}

export type MetodoPago = 'tarjeta_simulada' | 'transferencia_simulada';
export type EstadoPedido = 'pendiente' | 'pagado' | 'enviado' | 'cancelado';
export type EstadoEnvio = 'preparando' | 'en_transito' | 'entregado';

export interface Direccion {
  codigo_postal: string;
  calle: string;
  ciudad: string;
  estado: string;
}

export interface Pedido {
  id: string;
  usuario_id: string;
  items: { producto_id: string; cantidad: number; precio_unitario: Monto }[];
  direccion: Direccion;
  costo_envio: Monto;
  total: Monto;
  estado: EstadoPedido;
  creado_en: string;
  /** Campos previstos en Pedidos 1.2; el endpoint actual puede omitirlos durante la integración. */
  guia?: string | null;
  pago_id?: string | null;
  metodo_pago?: MetodoPago | null;
}

export interface RastreoEnvio {
  guia: string;
  pedido_id: string;
  estado: EstadoEnvio;
}

export interface ComprobantePago {
  id: string;
  pedido_id: string;
  monto: Monto;
  metodo_pago: MetodoPago;
  estado: 'aprobado' | 'rechazado';
  creado_en: string;
}

/** Estado genérico de carga para las vistas. */
export type Carga<T> =
  | { estado: 'cargando' }
  | { estado: 'error'; mensaje: string }
  | { estado: 'sin-datos'; mensaje: string }
  | { estado: 'listo'; datos: T };
