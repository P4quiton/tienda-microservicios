import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { CarritoStore } from '../../datos/carrito.store';
import { aCentavos, deCentavos } from '../../datos/dinero';
import { CotizacionEnvio, Direccion, MetodoPago, Pedido, Producto } from '../../datos/models';
import { TIENDA_DATOS } from '../../datos/tienda-datos';
import { EstadoVista } from '../../shared/estado-vista';
import { MxnPipe } from '../../shared/mxn.pipe';

interface Linea { producto: Producto; cantidad: number; importe: string }

@Component({
  selector: 'app-checkout',
  imports: [RouterLink, FormsModule, EstadoVista, MxnPipe],
  templateUrl: './checkout.html',
  styleUrl: './checkout.css',
})
export class Checkout {
  private datos = inject(TIENDA_DATOS);
  protected carrito = inject(CarritoStore);

  protected cargando = signal(true);
  protected error = signal('');
  protected productos = signal<Record<string, Producto>>({});

  protected direccion: Direccion = { codigo_postal: '', calle: '', ciudad: '', estado: '' };
  protected cotizacion = signal<CotizacionEnvio | null>(null);
  protected cotizando = signal(false);
  protected errorCp = signal('');
  protected metodo = signal<MetodoPago>('tarjeta_simulada');
  protected confirmando = signal(false);
  protected errorPedido = signal('');
  protected resultado = signal<Pedido | null>(null);

  protected lineas = computed<Linea[]>(() => this.carrito.items().flatMap((i) => {
    const producto = this.productos()[i.producto_id];
    return producto ? [{ producto, cantidad: i.cantidad, importe: deCentavos(aCentavos(producto.precio) * i.cantidad) }] : [];
  }));
  protected subtotal = computed(() => deCentavos(this.lineas().reduce((a, l) => a + aCentavos(l.importe), 0)));
  protected total = computed(() => {
    const c = this.cotizacion();
    return c ? deCentavos(aCentavos(this.subtotal()) + aCentavos(c.costo_envio)) : null;
  });
  protected paso = computed(() => this.resultado() ? 4 : this.cotizacion() ? 3 : this.lineas().length ? 2 : 1);

  constructor() {
    // Una cotización deja de ser válida si cambia el carrito.
    effect(() => { this.carrito.unidades(); this.cotizacion.set(null); });
    this.cargar();
  }

  async cargar() {
    this.cargando.set(true);
    this.error.set('');
    try {
      await this.carrito.refrescar();
      const ids = this.carrito.items().map((i) => i.producto_id).filter((id) => !this.productos()[id]);
      const nuevos = await Promise.all(ids.map((id) => this.datos.obtenerProducto(id)));
      this.productos.update((m) => ({ ...m, ...Object.fromEntries(nuevos.map((p) => [p.id, p])) }));
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.cargando.set(false);
    }
  }

  async cotizar() {
    this.errorCp.set('');
    if (!/^[0-9]{5}$/.test(this.direccion.codigo_postal)) return this.errorCp.set('El código postal debe tener 5 dígitos.');
    this.cotizando.set(true);
    try {
      this.cotizacion.set(await this.datos.cotizarEnvio(this.direccion.codigo_postal, this.carrito.unidades()));
    } catch (e) {
      this.errorCp.set((e as Error).message);
    } finally {
      this.cotizando.set(false);
    }
  }

  direccionCompleta() {
    const d = this.direccion;
    return /^[0-9]{5}$/.test(d.codigo_postal) && !!d.calle.trim() && !!d.ciudad.trim() && !!d.estado.trim();
  }

  async confirmar() {
    this.errorPedido.set('');
    if (!this.cotizacion()) return this.errorPedido.set('Cotiza el envío antes de confirmar.');
    if (!this.direccionCompleta()) return this.errorPedido.set('Completa la dirección de entrega.');
    this.confirmando.set(true);
    try {
      const pedido = await this.datos.crearPedido({ ...this.direccion }, this.metodo());
      this.resultado.set(pedido);
      if (pedido.estado !== 'cancelado') this.carrito.limpiarLocal();
    } catch (e) {
      this.errorPedido.set((e as Error).message);
    } finally {
      this.confirmando.set(false);
    }
  }

  reintentarPago() {
    this.datos.nuevoIntentoCheckout();
    this.resultado.set(null);
  }
}
