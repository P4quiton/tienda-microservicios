import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../core/auth/auth.service';
import { SesionUi } from './sesion-ui';

/** Adaptador HTTP para la pantalla de acceso; JWT guardado solo en memoria. */
@Injectable()
export class HttpSesionUi implements SesionUi {
  private readonly auth = inject(AuthService);
  readonly usuario = this.auth.user;

  async iniciarSesion(correo: string, contrasena: string): Promise<void> {
    await firstValueFrom(this.auth.login({ correo, contrasena }));
  }

  async registrar(nombre: string, correo: string, contrasena: string): Promise<void> {
    await firstValueFrom(this.auth.register({ nombre, correo, contrasena }));
  }

  cerrarSesion(): void {
    this.auth.logout();
  }
}
