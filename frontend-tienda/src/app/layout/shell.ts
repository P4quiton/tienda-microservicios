import { Component, effect, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { SessionService } from '../core/auth/session.service';
import { CarritoStore } from '../datos/carrito.store';
import { SESION_UI } from '../datos/sesion-ui';

@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './shell.html',
  styleUrl: './shell.css',
})
export class Shell {
  protected carrito = inject(CarritoStore);
  protected sesion = inject(SESION_UI);
  private session = inject(SessionService);
  private router = inject(Router);

  constructor() {
    this.carrito.refrescar().catch(() => undefined);
    effect(() => {
      if (this.session.expired()) {
        const volver = this.router.url.startsWith('/acceso') ? undefined : this.router.url;
        this.router.navigate(['/acceso'], { queryParams: volver ? { volver } : {} });
      }
    });
  }

  salir() {
    this.sesion.cerrarSesion();
    this.router.navigate(['/catalogo']);
  }

  buscar(e: Event, termino: string) {
    e.preventDefault();
    this.router.navigate(['/catalogo'], { queryParams: { q: termino.trim() || null }, queryParamsHandling: 'merge' });
  }
}
