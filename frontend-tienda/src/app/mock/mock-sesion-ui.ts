/**
 * Sesión SIMULADA. Cualquier correo válido y contraseña de 8+ caracteres entra,
 * salvo correos que contengan "invalido" (credenciales inválidas).
 * Registrar "demo@nebula.mx" simula correo ya registrado (409).
 */
import { Injectable, signal } from '@angular/core';
import { SesionUi, UsuarioUi } from '../datos/sesion-ui';
import { USUARIO_DEMO } from './fixtures';

const espera = () => new Promise((r) => setTimeout(r, 600));

@Injectable()
export class MockSesionUi implements SesionUi {
  private actual = signal<UsuarioUi | null>(null);
  readonly usuario = this.actual.asReadonly();

  async iniciarSesion(correo: string, _contrasena: string) {
    await espera();
    if (correo.includes('invalido')) throw new Error('Correo o contraseña incorrectos.');
    this.actual.set({ id: USUARIO_DEMO, nombre: correo.split('@')[0], correo, role: 'cliente' });
  }

  async registrar(nombre: string, correo: string, _contrasena: string) {
    await espera();
    if (correo === 'demo@nebula.mx') throw new Error('Ese correo ya está registrado.');
    // El registro crea la cuenta; el acceso ocurre después desde el formulario de login.
  }

  cerrarSesion() { this.actual.set(null); }
}
