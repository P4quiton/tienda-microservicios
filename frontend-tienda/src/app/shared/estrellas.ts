import { Component, computed, input } from '@angular/core';

@Component({
  selector: 'app-estrellas',
  template: `<span class="estrellas" role="img" [attr.aria-label]="etiqueta()">
    @for (i of [1, 2, 3, 4, 5]; track i) {
      <svg viewBox="0 0 20 20" [attr.width]="tam()" [attr.height]="tam()" aria-hidden="true">
        <path d="M10 1.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L10 14.8l-5.2 2.8 1-5.8L1.5 7.7l5.9-.8z" [attr.fill]="i <= redondeado() ? '#f5a623' : '#d7deea'" />
      </svg>
    }</span>`,
  styles: `.estrellas { display: inline-flex; gap: 1px; vertical-align: -2px; }`,
})
export class Estrellas {
  valor = input<number | null>(0);
  tam = input(16);
  redondeado = computed(() => Math.round(this.valor() ?? 0));
  etiqueta = computed(() => this.valor() == null ? 'Sin calificaciones' : `${this.valor()} de 5 estrellas`);
}
