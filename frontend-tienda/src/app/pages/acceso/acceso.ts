import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { SESION_UI } from '../../datos/sesion-ui';

type Modo = 'entrar' | 'registro';
const CORREO = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

@Component({
  selector: 'app-acceso',
  imports: [FormsModule],
  templateUrl: './acceso.html',
  styleUrl: './acceso.css',
})
export class Acceso {
  private sesion = inject(SESION_UI);
  private router = inject(Router);

  /** Ruta a la que volver tras autenticarse (query param). */
  volver = input<string>();

  protected modo = signal<Modo>('entrar');
  protected form = { nombre: '', correo: '', contrasena: '' };
  protected errores = signal<Partial<Record<'nombre' | 'correo' | 'contrasena', string>>>({});
  protected errorGeneral = signal('');
  protected avisoRegistro = signal('');
  protected enviando = signal(false);

  cambiar(m: Modo) { this.modo.set(m); this.errores.set({}); this.errorGeneral.set(''); this.avisoRegistro.set(''); }

  private validar() {
    const e: ReturnType<typeof this.errores> = {};
    const { nombre, correo, contrasena } = this.form;
    if (this.modo() === 'registro' && !nombre.trim()) e.nombre = 'Escribe tu nombre.';
    if (!CORREO.test(correo)) e.correo = 'Escribe un correo válido.';
    if (contrasena.length < 8 || contrasena.length > 128) e.contrasena = 'La contraseña debe tener entre 8 y 128 caracteres.';
    this.errores.set(e);
    return !Object.keys(e).length;
  }

  async enviar(ev: Event) {
    ev.preventDefault();
    this.errorGeneral.set('');
    this.avisoRegistro.set('');
    if (!this.validar()) return;
    this.enviando.set(true);
    try {
      const { nombre, correo, contrasena } = this.form;
      if (this.modo() === 'entrar') await this.sesion.iniciarSesion(correo.trim(), contrasena);
      else {
        await this.sesion.registrar(nombre.trim(), correo.trim(), contrasena);
        this.modo.set('entrar');
        this.form.contrasena = '';
        this.avisoRegistro.set('Cuenta creada. Inicia sesión para continuar.');
        return;
      }
      this.router.navigateByUrl(this.volver() || '/catalogo');
    } catch (e) {
      this.errorGeneral.set((e as Error).message);
    } finally {
      this.enviando.set(false);
    }
  }
}
