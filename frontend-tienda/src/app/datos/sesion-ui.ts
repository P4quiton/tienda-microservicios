import { InjectionToken, Signal, inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

export interface UsuarioUi {
  id: string;
  nombre: string;
  correo: string;
  role: string;
}

/**
 * PUNTO DE INTEGRACIÓN de acceso. La UI solo usa esta interfaz.
 * Hoy: MockSesionUi. Integración: adaptar AuthService/SessionService de core/
 * (POST /api/usuarios/login y /api/usuarios/registro; JWT en memoria).
 */
export interface SesionUi {
  readonly usuario: Signal<UsuarioUi | null>;
  iniciarSesion(correo: string, contrasena: string): Promise<void>;
  /** Registra la cuenta; el usuario debe iniciar sesión después. */
  registrar(nombre: string, correo: string, contrasena: string): Promise<void>;
  cerrarSesion(): void;
}

export const SESION_UI = new InjectionToken<SesionUi>('SESION_UI');

/** Redirige a /acceso conservando la ruta solicitada. */
export const requiereSesion: CanActivateFn = (_r, estado) =>
  inject(SESION_UI).usuario() ? true : inject(Router).createUrlTree(['/acceso'], { queryParams: { volver: estado.url } });
