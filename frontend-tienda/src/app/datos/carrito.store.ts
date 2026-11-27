import { Injectable, computed, inject, signal } from '@angular/core';
import { ItemCarrito } from './models';
import { TIENDA_DATOS } from './tienda-datos';

/** Estado compartido del carrito (contador del encabezado y checkout). */
@Injectable({ providedIn: 'root' })
export class CarritoStore {
  private datos = inject(TIENDA_DATOS);
  readonly items = signal<ItemCarrito[]>([]);
  readonly unidades = computed(() => this.items().reduce((a, i) => a + i.cantidad, 0));

  async refrescar() { this.items.set(await this.datos.carrito()); }

  async agregar(producto_id: string, cantidad = 1) {
    this.items.set(await this.datos.agregarAlCarrito({ producto_id, cantidad }));
  }

  /** Pedidos vacía el carrito en el servidor; aquí solo se refleja localmente. */
  limpiarLocal() { this.items.set([]); }
}
