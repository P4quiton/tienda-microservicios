import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { Router } from '@angular/router';
import { CarritoStore } from '../../datos/carrito.store';
import { Carga } from '../../datos/models';
import { TIENDA_DATOS } from '../../datos/tienda-datos';
import { EstadoVista } from '../../shared/estado-vista';
import { ProductoCard, ProductoResumen } from '../../shared/producto-card';

type Orden = 'recomendados' | 'precio-asc' | 'precio-desc' | 'calificacion';


@Component({
  selector: 'app-catalogo',
  imports: [ProductoCard, EstadoVista],
  templateUrl: './catalogo.html',
  styleUrl: './catalogo.css',
})
export class Catalogo {
  private datos = inject(TIENDA_DATOS);
  private router = inject(Router);
  private carrito = inject(CarritoStore);

  /** Query params enlazados por el router. */
  q = input<string>();
  categoria = input<string>();

  /** categoria es texto libre en el contrato: las chips se derivan del catálogo sin filtrar. */
  protected categorias = signal<string[]>([]);
  protected orden = signal<Orden>('recomendados');
  protected estado = signal<Carga<ProductoResumen[]>>({ estado: 'cargando' });
  protected agregando = signal<string | null>(null);
  protected aviso = signal('');

  protected ordenados = computed(() => {
    const e = this.estado();
    if (e.estado !== 'listo') return [];
    const lista = [...e.datos];
    const precio = (x: ProductoResumen) => Number(x.producto.precio);
    switch (this.orden()) {
      case 'precio-asc': return lista.sort((a, b) => precio(a) - precio(b));
      case 'precio-desc': return lista.sort((a, b) => precio(b) - precio(a));
      case 'calificacion': return lista.sort((a, b) => (b.promedio ?? 0) - (a.promedio ?? 0));
      default: return lista;
    }
  });

  constructor() {
    effect(() => { this.cargar(this.q(), this.categoria()); });
    this.datos.listarProductos({})
      .then((ps) => this.categorias.set([...new Set(ps.map((p) => p.categoria))].sort((a, b) => a.localeCompare(b, 'es'))))
      .catch(() => undefined);
  }

  async cargar(busqueda = this.q(), categoria = this.categoria()) {
    this.estado.set({ estado: 'cargando' });
    try {
      const productos = await this.datos.listarProductos({ busqueda, categoria });
      // Promedio de reseñas e inventario por producto (endpoints independientes).
      const datos = await Promise.all(productos.map(async (producto) => {
        const [r, disponibles] = await Promise.all([
          this.datos.resenas(producto.id).catch(() => null),
          this.datos.disponibles(producto.id).catch(() => null),
        ]);
        return { producto, promedio: r?.promedio ?? null, totalResenas: r?.total ?? 0, disponibles };
      }));
      this.estado.set({ estado: 'listo', datos });
    } catch (e) {
      this.estado.set({ estado: 'error', mensaje: (e as Error).message });
    }
  }

  filtrar(categoria: string | null) {
    this.router.navigate([], { queryParams: { categoria }, queryParamsHandling: 'merge' });
  }

  limpiar() { this.router.navigate([], { queryParams: { categoria: null, q: null } }); }

  async agregar(id: string) {
    this.agregando.set(id);
    try {
      await this.carrito.agregar(id);
      this.aviso.set('Producto agregado al carrito.');
    } catch (e) {
      this.aviso.set('No se pudo agregar: ' + (e as Error).message);
    } finally {
      this.agregando.set(null);
    }
  }
}
