import { Component, input, output } from '@angular/core';

/** Bloques visuales reutilizables para carga, error y vacío. */
@Component({
  selector: 'app-estado-vista',
  template: `
    @switch (tipo()) {
      @case ('cargando') {
        <div class="caja" role="status" aria-live="polite">
          <span class="spinner" aria-hidden="true"></span>
          <p>{{ titulo() || 'Cargando…' }}</p>
        </div>
      }
      @case ('error') {
        <div class="caja tarjeta" role="alert">
          <span class="icono err" aria-hidden="true">!</span>
          <h2>{{ titulo() || 'Algo salió mal' }}</h2>
          <p class="muted">{{ mensaje() }}</p>
          <button type="button" class="btn btn-secundario" (click)="reintentar.emit()">Reintentar</button>
        </div>
      }
      @default {
        <div class="caja tarjeta">
          <span class="icono" aria-hidden="true">○</span>
          <h2>{{ titulo() }}</h2>
          <p class="muted">{{ mensaje() }}</p>
          <ng-content />
        </div>
      }
    }
  `,
  styles: `
    .caja { display: grid; justify-items: center; gap: .5rem; text-align: center; padding: 3rem 1.5rem; }
    .caja p { margin: 0; }
    .icono { width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center; font-size: 1.5rem; font-weight: 700; background: var(--info-bg); color: var(--info); }
    .icono.err { background: var(--err-bg); color: var(--err); }
    .spinner { width: 36px; height: 36px; border-radius: 50%; border: 4px solid rgba(11,92,255,.15); border-top-color: var(--azul); animation: girar .8s linear infinite; }
    @keyframes girar { to { transform: rotate(360deg); } }
  `,
})
export class EstadoVista {
  tipo = input<'cargando' | 'error' | 'vacio'>('vacio');
  titulo = input('');
  mensaje = input('');
  reintentar = output<void>();
}
