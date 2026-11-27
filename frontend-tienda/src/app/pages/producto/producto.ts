import { DatePipe } from '@angular/common';
import { Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { CarritoStore } from '../../datos/carrito.store';
import { Carga, Producto, ResumenResenas } from '../../datos/models';
import { SESION_UI } from '../../datos/sesion-ui';
import { TIENDA_DATOS } from '../../datos/tienda-datos';
import { EstadoVista } from '../../shared/estado-vista';
import { Estrellas } from '../../shared/estrellas';
import { MxnPipe } from '../../shared/mxn.pipe';
import { usarImagenRespaldo } from '../../shared/imagen-respaldo';

@Component({
  selector: 'app-producto-detalle',
  imports: [RouterLink, FormsModule, DatePipe, EstadoVista, Estrellas, MxnPipe],
  templateUrl: './producto.html',
  styleUrl: './producto.css',
})
export class ProductoDetalle {
  protected usarImagenRespaldo = usarImagenRespaldo;
  private datos = inject(TIENDA_DATOS);
  private carrito = inject(CarritoStore);
  protected sesion = inject(SESION_UI);

  id = input.required<string>();

  protected producto = signal<Carga<Producto>>({ estado: 'cargando' });
  protected disponibles = signal<number | null>(null);
  protected resenas = signal<Carga<ResumenResenas>>({ estado: 'cargando' });
  protected cantidad = signal(1);
  protected agregando = signal(false);
  protected aviso = signal('');

  // Formulario de reseña
  protected calificacion = signal(0);
  protected comentario = signal('');
  protected enviando = signal(false);
  protected errorResena = signal('');
  protected resenaEnviada = signal(false);

  constructor() {
    effect(() => { this.cargar(this.id()); });
  }

  async cargar(id = this.id()) {
    this.producto.set({ estado: 'cargando' });
    this.disponibles.set(null);
    try {
      this.producto.set({ estado: 'listo', datos: await this.datos.obtenerProducto(id) });
    } catch (e) {
      this.producto.set({ estado: 'error', mensaje: (e as Error).message });
      return;
    }
    this.datos.disponibles(id).then((d) => this.disponibles.set(d)).catch(() => this.disponibles.set(null));
    this.cargarResenas();
  }

  async cargarResenas() {
    this.resenas.set({ estado: 'cargando' });
    try {
      this.resenas.set({ estado: 'listo', datos: await this.datos.resenas(this.id()) });
    } catch (e) {
      this.resenas.set({ estado: 'error', mensaje: (e as Error).message });
    }
  }

  cambiarCantidad(delta: number) {
    const max = this.disponibles() ?? 1;
    this.cantidad.update((c) => Math.min(Math.max(1, c + delta), Math.max(1, max)));
  }

  async agregar() {
    this.agregando.set(true);
    try {
      await this.carrito.agregar(this.id(), this.cantidad());
      this.aviso.set(`Agregaste ${this.cantidad()} al carrito.`);
    } catch (e) {
      this.aviso.set('No se pudo agregar: ' + (e as Error).message);
    } finally {
      this.agregando.set(false);
    }
  }

  async enviarResena(e: Event) {
    e.preventDefault();
    this.errorResena.set('');
    if (!this.calificacion()) return this.errorResena.set('Selecciona una calificación de 1 a 5 estrellas.');
    if (this.comentario().trim().length < 5) return this.errorResena.set('Escribe un comentario de al menos 5 caracteres.');
    this.enviando.set(true);
    try {
      await this.datos.crearResena({ producto_id: this.id(), calificacion: this.calificacion(), comentario: this.comentario().trim() });
      this.calificacion.set(0);
      this.comentario.set('');
      this.resenaEnviada.set(true);
      this.cargarResenas();
    } catch (err) {
      this.errorResena.set((err as Error).message);
    } finally {
      this.enviando.set(false);
    }
  }
}
