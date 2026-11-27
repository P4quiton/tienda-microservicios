import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Carga, EstadoPedido, Pedido, Producto } from '../../datos/models';
import { TIENDA_DATOS } from '../../datos/tienda-datos';
import { EstadoVista } from '../../shared/estado-vista';
import { MxnPipe } from '../../shared/mxn.pipe';

const ESTADOS: Record<EstadoPedido, { texto: string; clase: string }> = {
  pendiente: { texto: 'Pendiente', clase: 'warn' },
  pagado: { texto: 'Pagado', clase: 'ok' },
  enviado: { texto: 'Enviado', clase: '' },
  cancelado: { texto: 'Cancelado', clase: 'err' },
};

/** Línea de tiempo basada solo en el estado del pedido (el pedido no expone guía ni estado de envío). */
const PROGRESO: Record<EstadoPedido, number> = { pendiente: 1, pagado: 2, enviado: 3, cancelado: 0 };

@Component({
  selector: 'app-mis-pedidos',
  imports: [DatePipe, RouterLink, EstadoVista, MxnPipe],
  templateUrl: './pedidos.html',
  styleUrl: './pedidos.css',
})
export class MisPedidos {
  private datos = inject(TIENDA_DATOS);

  protected estados = ESTADOS;
  protected progreso = PROGRESO;
  protected etapas = ['Pedido recibido', 'Pago confirmado', 'Enviado'];
  protected estado = signal<Carga<Pedido[]>>({ estado: 'cargando' });
  protected lista = computed(() => { const e = this.estado(); return e.estado === 'listo' ? e.datos : []; });
  protected productos = signal<Record<string, Producto>>({});
  protected abierto = signal<string | null>(null);

  constructor() { this.cargar(); }

  async cargar() {
    this.estado.set({ estado: 'cargando' });
    try {
      const pedidos = await this.datos.misPedidos();
      this.estado.set({ estado: 'listo', datos: pedidos });
      const ids = [...new Set(pedidos.flatMap((p) => p.items.map((i) => i.producto_id)))];
      const ps = await Promise.all(ids.map((id) => this.datos.obtenerProducto(id).catch(() => null)));
      this.productos.set(Object.fromEntries(ps.filter((p): p is Producto => !!p).map((p) => [p.id, p])));
    } catch (e) {
      this.estado.set({ estado: 'error', mensaje: (e as Error).message });
    }
  }

  alternar(id: string) { this.abierto.update((a) => (a === id ? null : id)); }
  folio(id: string) { return 'NB-' + id.slice(-5).toUpperCase(); }
}
