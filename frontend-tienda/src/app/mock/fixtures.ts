/**
 * FIXTURES DE DEMOSTRACIÓN — no son datos reales; solo los consume MockTiendaDatos.
 */
import { ComprobantePago, EstadoEnvio, Pedido, Producto, Resena } from '../datos/models';

export const USUARIO_DEMO = '00000000-0000-4000-8000-000000000001';

const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

export const PRODUCTOS: Producto[] = [
  { id: uuid(101), nombre: 'Auriculares Nova Pro', categoria: 'Electrónica', precio: '2499.00', imagen_url: '/mock/electronica.svg',
    descripcion: 'Sonido envolvente de alta fidelidad, cancelación activa de ruido y hasta 40 horas de batería.' },
  { id: uuid(102), nombre: 'Smartwatch Aura Fit', categoria: 'Deportes', precio: '1899.00', imagen_url: '/mock/deportes.svg',
    descripcion: 'Monitoreo de actividad, sueño y ritmo cardiaco con pantalla AMOLED siempre activa.' },
  { id: uuid(103), nombre: 'Bocina Orbit Mini', categoria: 'Electrónica', precio: '899.00', imagen_url: '/mock/electronica.svg',
    descripcion: 'Bocina compacta con sonido 360°, resistente al agua y 12 horas de reproducción.' },
  { id: uuid(104), nombre: 'Lámpara Lunar Desk', categoria: 'Hogar', precio: '1299.00', imagen_url: '/mock/hogar.svg',
    descripcion: 'Lámpara de escritorio con luz cálida regulable y base de carga inalámbrica.' },
  { id: uuid(105), nombre: 'Libreta Constelación', categoria: 'Papelería', precio: '289.00', imagen_url: '/mock/papeleria.svg',
    descripcion: 'Libreta de tapa dura con hojas punteadas de 120 g y cinta separadora.' },
  { id: uuid(107), nombre: 'Botella Térmica Polar', categoria: 'Deportes', precio: '459.00', imagen_url: '/mock/deportes.svg',
    descripcion: 'Botella de acero inoxidable que mantiene bebidas frías 24 h y calientes 12 h.' },
  { id: uuid(106), nombre: 'Difusor Halo', categoria: 'Hogar', precio: '649.00', imagen_url: '/mock/hogar.svg',
    descripcion: 'Difusor ultrasónico de aromas con luz ambiental y apagado automático.' },
];

/** GET /api/inventario/{producto_id} → disponibles */
export const INVENTARIO: Record<string, number> = {
  [uuid(101)]: 18, [uuid(102)]: 27, [uuid(103)]: 42, [uuid(104)]: 15, [uuid(105)]: 0, [uuid(106)]: 4, [uuid(107)]: 33,
};

const r = (n: number, prod: number, cal: number, comentario: string, dias: number): Resena => ({
  id: uuid(500 + n), producto_id: uuid(prod), usuario_id: uuid(900 + n), calificacion: cal, comentario,
  creado_en: new Date(Date.UTC(2026, 10, 25) - dias * 864e5).toISOString(),
});

export const RESENAS: Resena[] = [
  r(1, 101, 5, 'Excelente calidad de sonido y la cancelación de ruido realmente funciona. Muy cómodos.', 6),
  r(2, 101, 5, 'La batería dura muchísimo y el diseño es increíble. Totalmente recomendados.', 14),
  r(3, 101, 4, 'Muy buenos, aunque el estuche podría ser más pequeño.', 30),
  r(4, 102, 5, 'Ligero y preciso al medir el sueño.', 3),
  r(5, 102, 4, 'Buena pantalla; la correa podría ser más suave.', 20),
  r(6, 103, 5, 'Suena mucho más fuerte de lo que esperaba.', 9),
  r(7, 104, 5, 'Perfecta para mi escritorio, la carga inalámbrica es muy práctica.', 11),
  r(8, 106, 4, 'Bonita luz y buen aroma, el tanque es algo pequeño.', 2),
];

export const PEDIDOS: Pedido[] = [
  { id: uuid(10542), usuario_id: USUARIO_DEMO, estado: 'enviado', creado_en: '2026-11-15T17:20:00Z',
    guia: 'ENVNEBULA10542', pago_id: uuid(30542), metodo_pago: 'tarjeta_simulada',
    items: [{ producto_id: uuid(101), cantidad: 1, precio_unitario: '2499.00' }, { producto_id: uuid(103), cantidad: 1, precio_unitario: '899.00' }],
    direccion: { codigo_postal: '03100', calle: 'Av. Universidad 1200', ciudad: 'Ciudad de México', estado: 'CDMX' },
    costo_envio: '129.00', total: '3527.00' },
  { id: uuid(10541), usuario_id: USUARIO_DEMO, estado: 'pagado', creado_en: '2026-11-10T12:05:00Z',
    guia: 'ENVNEBULA10541', pago_id: uuid(30541), metodo_pago: 'tarjeta_simulada',
    items: [{ producto_id: uuid(102), cantidad: 1, precio_unitario: '1899.00' }],
    direccion: { codigo_postal: '44100', calle: 'Calle Juárez 45', ciudad: 'Guadalajara', estado: 'Jalisco' },
    costo_envio: '149.00', total: '2048.00' },
  { id: uuid(10540), usuario_id: USUARIO_DEMO, estado: 'pendiente', creado_en: '2026-11-05T09:40:00Z',
    guia: null, pago_id: null, metodo_pago: 'tarjeta_simulada',
    items: [{ producto_id: uuid(104), cantidad: 1, precio_unitario: '1299.00' }],
    direccion: { codigo_postal: '64000', calle: 'Av. Constitución 300', ciudad: 'Monterrey', estado: 'Nuevo León' },
    costo_envio: '159.00', total: '1458.00' },
  { id: uuid(10539), usuario_id: USUARIO_DEMO, estado: 'cancelado', creado_en: '2026-10-28T19:15:00Z',
    guia: null, pago_id: uuid(30539), metodo_pago: 'transferencia_simulada',
    items: [{ producto_id: uuid(106), cantidad: 2, precio_unitario: '649.00' }],
    direccion: { codigo_postal: '03100', calle: 'Av. Universidad 1200', ciudad: 'Ciudad de México', estado: 'CDMX' },
    costo_envio: '129.00', total: '1427.00' },
];

/** Comprobantes ficticios para pedidos de demostración con pago concluido. */
export const PAGOS_DEMO: Record<string, ComprobantePago> = {
  [uuid(10542)]: { id: uuid(30542), pedido_id: uuid(10542), monto: '3527.00', metodo_pago: 'tarjeta_simulada', estado: 'aprobado', creado_en: '2026-11-15T17:21:00Z' },
  [uuid(10541)]: { id: uuid(30541), pedido_id: uuid(10541), monto: '2048.00', metodo_pago: 'tarjeta_simulada', estado: 'aprobado', creado_en: '2026-11-10T12:06:00Z' },
  [uuid(10539)]: { id: uuid(30539), pedido_id: uuid(10539), monto: '1427.00', metodo_pago: 'transferencia_simulada', estado: 'rechazado', creado_en: '2026-10-28T19:16:00Z' },
};

/** Rastreo ficticio para probar la consulta manual y el ciclo de 60 s + 60 s sin servicios reales. */
export interface EnvioDemo {
  pedido_id: string;
  inicio: number;
}

export const ENVIOS_DEMO: Record<string, EnvioDemo> = {
  [PEDIDOS[0].guia!]: { pedido_id: PEDIDOS[0].id, inicio: Date.now() - 180_000 },
  [PEDIDOS[1].guia!]: { pedido_id: PEDIDOS[1].id, inicio: Date.now() - 20_000 },
};

/** La guía aparece 60 s después del pago aprobado, igual que la asignación simulada de despacho. */
export function guiaDemo(inicio: number, ahora = Date.now()): string | null {
  if (ahora - inicio < 60_000) return null;
  return `ENV${inicio.toString(36).toUpperCase()}`;
}

export function estadoEnvioDemo(inicio: number, ahora = Date.now()): EstadoEnvio {
  const transcurrido = ahora - inicio;
  if (transcurrido < 60_000) return 'preparando';
  if (transcurrido < 120_000) return 'en_transito';
  return 'entregado';
}
