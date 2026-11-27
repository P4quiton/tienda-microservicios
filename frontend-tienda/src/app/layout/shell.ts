import { Component, DestroyRef, ElementRef, afterNextRender, effect, inject, signal, viewChild } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
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

  /** Fondo compartido de la barra de pestañas: se desliza hasta la pestaña activa. */
  private tabbar = viewChild<ElementRef<HTMLElement>>('tabbar');
  protected indicador = signal({ x: 0, w: 0, visible: false });

  /** Tema visual: preferencia guardada o, si no hay, la del sistema. */
  protected oscuro = signal(document.documentElement.dataset['theme'] === 'dark');

  constructor() {
    const destroyRef = inject(DestroyRef);
    const sub = this.router.events.subscribe((e) => { if (e instanceof NavigationEnd) setTimeout(() => this.moverIndicador()); });
    afterNextRender(() => {
      this.moverIndicador();
      const ro = new ResizeObserver(() => this.moverIndicador());
      const ul = this.tabbar()?.nativeElement;
      if (ul) ro.observe(ul);
      destroyRef.onDestroy(() => ro.disconnect());
    });
    destroyRef.onDestroy(() => sub.unsubscribe());
    this.carrito.refrescar().catch(() => undefined);
    effect(() => {
      if (this.session.expired()) {
        const volver = this.router.url.startsWith('/acceso') ? undefined : this.router.url;
        this.router.navigate(['/acceso'], { queryParams: volver ? { volver } : {} });
      }
    });
  }

  /** Activa la animación solo tras la primera interacción (no al cargar). */
  protected temaAnimado = signal(false);

  /** Pestaña destino mientras se navega o se pide iniciar sesión para llegar a ella. */
  protected tabDestino = signal<string | null>(null);

  private moverIndicador(objetivo?: HTMLElement | null) {
    const ul = this.tabbar()?.nativeElement;
    if (!ul) return;
    // Sin pestaña activa (p. ej. /acceso?volver=/mis-pedidos), resalta la pestaña a la que se quiere llegar.
    const volver = this.router.parseUrl(this.router.url).queryParams['volver'] as string | undefined;
    const destino = this.router.url.startsWith('/acceso') && volver ? volver.split('?')[0] : null;
    this.tabDestino.set(destino);
    const li = (objetivo
      ?? ul.querySelector<HTMLElement>('a.activo')
      ?? (destino ? ul.querySelector<HTMLElement>(`a[href="${destino}"]`) : null))?.closest('li');
    if (!li) return this.indicador.update((i) => ({ ...i, visible: false }));
    this.indicador.set({ x: li.offsetLeft, w: li.offsetWidth, visible: true });
  }

  /** Al pulsar una pestaña, el fondo empieza a deslizarse de inmediato. */
  protected pulsarTab(e: Event) {
    this.moverIndicador(e.currentTarget as HTMLElement);
  }

  alternarTema() {
    this.temaAnimado.set(true);
    const oscuro = !this.oscuro();
    this.oscuro.set(oscuro);
    document.documentElement.dataset['theme'] = oscuro ? 'dark' : 'light';
    try { localStorage.setItem('nebula-tema', oscuro ? 'dark' : 'light'); } catch { /* almacenamiento no disponible */ }
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
