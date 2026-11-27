import { InjectionToken, Signal, inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

export interface UsuarioUi {
  id: string;
  nombre: string;
  correo: string;
  role: string;
}

/**
 * La UI solo usa esta interfaz; app.config.ts selecciona mock o HTTP.
 * El adaptador HTTP usa AuthService/SessionService y mantiene el JWT en memoria.
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
