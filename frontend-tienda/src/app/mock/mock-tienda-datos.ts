/**
 * Implementación SIMULADA de TiendaDatos con fixtures en memoria.
 * Para demostrar estados: añade ?mock=error o ?mock=vacio a la URL.
 */
import { Injectable } from '@angular/core';
import { aCentavos, deCentavos } from '../datos/dinero';
import { ComprobantePago, CotizacionEnvio, Direccion, ItemCarrito, MetodoPago, Pedido, Producto, RastreoEnvio, ResumenResenas } from '../datos/models';
import { TiendaDatos } from '../datos/tienda-datos';
import { ENVIOS_DEMO, estadoEnvioDemo, guiaDemo, INVENTARIO, PAGOS_DEMO, PEDIDOS, PRODUCTOS, RESENAS, USUARIO_DEMO } from './fixtures';

const modo = () => new URLSearchParams(location.search).get('mock');
const normalizar = (s: string) => s.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();

@Injectable()
export class MockTiendaDatos implements TiendaDatos {
  private items: ItemCarrito[] = [{ producto_id: PRODUCTOS[0].id, cantidad: 1 }, { producto_id: PRODUCTOS[2].id, cantidad: 1 }];
  private resenasExtra = [...RESENAS];
  private pedidos = [...PEDIDOS];
  private comprobantes = new Map(Object.entries(PAGOS_DEMO));
  private envios = new Map(Object.entries(ENVIOS_DEMO));

  private async latencia<T>(valor: () => T, ms = 450): Promise<T> {
    await new Promise((r) => setTimeout(r, ms));
    if (modo() === 'error') throw new Error('No se pudo conectar con el servicio (simulado).');
    return valor();
  }

  listarProductos(f: { busqueda?: string; categoria?: string }) {
    return this.latencia(() => modo() === 'vacio' ? [] : PRODUCTOS.filter((p) =>
      (!f.categoria || p.categoria === f.categoria) &&
      (!f.busqueda || normalizar(p.nombre + ' ' + p.descripcion).includes(normalizar(f.busqueda)))));
  }

  obtenerProducto(id: string) {
    return this.latencia(() => {
      const p = PRODUCTOS.find((x) => x.id === id);
      if (!p) throw new Error('Producto no encontrado.');
      return p;
    });
  }

  disponibles(id: string) { return this.latencia(() => INVENTARIO[id] ?? 0, 200); }

  resenas(id: string): Promise<ResumenResenas> {
    return this.latencia(() => {
      const items = modo() === 'vacio' ? [] : this.resenasExtra.filter((r) => r.producto_id === id);
      const promedio = items.length ? Math.round((items.reduce((a, r) => a + r.calificacion, 0) / items.length) * 10) / 10 : null;
      return { items, promedio, total: items.length };
    }, 250);
  }

  crearResena(r: { producto_id: string; calificacion: number; comentario: string }) {
    return this.latencia(() => {
      this.resenasExtra.unshift({ ...r, id: crypto.randomUUID(), usuario_id: USUARIO_DEMO, creado_en: new Date().toISOString() });
    });
  }

  carrito() { return this.latencia(() => modo() === 'vacio' ? [] : this.items.map((i) => ({ ...i })), 250); }

  agregarAlCarrito(item: ItemCarrito) {
    return this.latencia(() => {
      const actual = this.items.find((i) => i.producto_id === item.producto_id);
      if (actual) actual.cantidad += item.cantidad; else this.items.push({ ...item });
      return this.items.map((i) => ({ ...i }));
    }, 250);
  }

  cotizarEnvio(cp: string, cantidad: number): Promise<CotizacionEnvio> {
    // Tarifa determinista por CP y cantidad, como describe el contrato.
    return this.latencia(() => ({
      costo_envio: deCentavos(9900 + (Number(cp.slice(0, 2)) % 7) * 1000 + Math.max(0, cantidad - 1) * 1500),
      dias_estimados: 2 + (Number(cp[0]) % 3),
    }), 600);
  }

  async crearPedido(direccion: Direccion, metodo: MetodoPago): Promise<Pedido> {
    const { costo_envio } = await this.cotizarEnvio(direccion.codigo_postal, this.items.reduce((a, i) => a + i.cantidad, 0));
    return this.latencia(() => {
      const items = this.items.map((i) => ({ ...i, precio_unitario: PRODUCTOS.find((p) => p.id === i.producto_id)!.precio }));
      const subtotal = items.reduce((a, i) => a + aCentavos(i.precio_unitario) * i.cantidad, 0);
      // Acuerdo de pagos simulados: tarjeta aprueba, transferencia rechaza.
      // Supuesto UI: un rechazo llega como pedido 'cancelado' y el carrito se conserva.
      const aprobado = metodo === 'tarjeta_simulada';
      const id = crypto.randomUUID();
      const pagoId = crypto.randomUUID();
      const creado = new Date().toISOString();
      const total = deCentavos(subtotal + aCentavos(costo_envio));
      const pedido: Pedido = { id, usuario_id: USUARIO_DEMO, items, direccion, costo_envio, total,
        estado: aprobado ? 'pagado' : 'cancelado', creado_en: creado, guia: null, pago_id: pagoId, metodo_pago: metodo };
      this.pedidos.unshift(pedido);
      this.comprobantes.set(id, { id: pagoId, pedido_id: id, monto: total, metodo_pago: metodo,
        estado: aprobado ? 'aprobado' : 'rechazado', creado_en: creado });
      if (aprobado) this.envios.set('', { pedido_id: id, inicio: Date.now() });
      if (aprobado) this.items = [];
      return pedido;
    }, 900);
  }

  nuevoIntentoCheckout(): void { /* Los mocks no necesitan clave de idempotencia. */ }

  misPedidos() { return this.latencia(() => { this.sincronizarGuias(); return modo() === 'vacio' ? [] : [...this.pedidos]; }); }

  comprobantePago(pedidoId: string): Promise<ComprobantePago> {
    return this.latencia(() => {
      const receipt = this.comprobantes.get(pedidoId);
      if (!receipt) throw new Error('El pedido aún no tiene un comprobante disponible.');
      return receipt;
    }, 300);
  }

  rastrearEnvio(guia: string): Promise<RastreoEnvio> {
    return this.latencia(() => {
      const envio = this.envios.get(guia) ?? [...this.envios.values()].find((item) => guiaDemo(item.inicio) === guia);
      if (!envio) throw new Error('Guía no encontrada.');
      return { guia, pedido_id: envio.pedido_id, estado: estadoEnvioDemo(envio.inicio) };
    }, 300);
  }

  private sincronizarGuias(): void {
    this.envios.forEach((envio, clave) => {
      if (clave) return;
      const guia = guiaDemo(envio.inicio);
      if (!guia) return;
      const pedido = this.pedidos.find((p) => p.id === envio.pedido_id);
      if (pedido) pedido.guia = guia;
      this.envios.delete(clave);
      this.envios.set(guia, envio);
    });
  }
}
