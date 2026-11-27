import { Component, ElementRef, computed, inject, input, output, signal, viewChildren } from '@angular/core';

export interface OpcionOrden { valor: string; texto: string; icono: 'destacado' | 'asc' | 'desc' | 'estrella' }

/** Menú desplegable de cristal (listbox accesible) para ordenar el catálogo. */
@Component({
  selector: 'app-menu-orden',
  host: { '(document:click)': 'fueraDeMenu($event)', '(keydown.escape)': 'cerrar(true)' },
  template: `
    <button #disparador type="button" class="menu-disparador" aria-haspopup="listbox" [attr.aria-expanded]="abierto()"
      aria-label="Ordenar por" [attr.aria-describedby]="'orden-actual'" (click)="alternar()" (keydown)="teclaDisparador($event)">
      <span id="orden-actual">{{ actual()?.texto }}</span>
      <svg aria-hidden="true" viewBox="0 0 24 24" class="chevron"><path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
    </button>
    @if (abierto()) {
      <div class="menu-panel" role="presentation">
        <ul role="listbox" aria-label="Ordenar por" tabindex="-1">
          @for (o of opciones(); track o.valor; let i = $index) {
            <li #item role="option" [attr.aria-selected]="o.valor === valor()" tabindex="-1" class="menu-item" [class.sel]="o.valor === valor()"
              (click)="elegir(o.valor)" (keydown)="teclaItem($event, i)">
              <span>{{ o.texto }}</span>
              <svg aria-hidden="true" viewBox="0 0 24 24">
                @switch (o.icono) {
                  @case ('destacado') { <path d="M12 3l2.2 5.3L20 9l-4.4 3.8L17 18.5 12 15.6 7 18.5l1.4-5.7L4 9l5.8-.7z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/> }
                  @case ('asc') { <path d="M7 20V4M3 8l4-4 4 4M14 8h7M14 13h5M14 18h3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/> }
                  @case ('desc') { <path d="M7 4v16M3 16l4 4 4-4M14 6h3M14 11h5M14 16h7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/> }
                  @default { <path d="M12 2.8l2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.2l-5.6 3 1.1-6.3L2.9 9.5l6.3-.9z" fill="currentColor"/> }
                }
              </svg>
            </li>
          }
        </ul>
        <div class="menu-separador" role="presentation"></div>
        <button type="button" class="menu-item menu-peligro" (click)="restablecer.emit(); cerrar(true)">
          <span>Limpiar filtros</span>
          <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      </div>
    }
  `,
})
export class MenuOrden {
  private host: ElementRef<HTMLElement> = inject(ElementRef);
  private items = viewChildren<ElementRef<HTMLElement>>('item');

  opciones = input.required<OpcionOrden[]>();
  valor = input.required<string>();
  cambio = output<string>();
  restablecer = output<void>();

  protected abierto = signal(false);
  protected actual = computed(() => this.opciones().find((o) => o.valor === this.valor()));

  alternar() { this.abierto() ? this.cerrar() : this.abrir(); }

  abrir(indice = Math.max(0, this.opciones().findIndex((o) => o.valor === this.valor()))) {
    this.abierto.set(true);
    setTimeout(() => this.items()[indice]?.nativeElement.focus());
  }

  cerrar(enfocar = false) {
    if (!this.abierto()) return;
    this.abierto.set(false);
    if (enfocar) (this.host.nativeElement.querySelector('.menu-disparador') as HTMLElement | null)?.focus();
  }

  elegir(valor: string) { this.cambio.emit(valor); this.cerrar(true); }

  fueraDeMenu(e: Event) { if (!this.host.nativeElement.contains(e.target as Node)) this.cerrar(); }

  teclaDisparador(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); this.abrir(); }
  }

  teclaItem(e: KeyboardEvent, i: number) {
    const n = this.opciones().length;
    const ir = (k: number) => { e.preventDefault(); this.items()[(k + n) % n]?.nativeElement.focus(); };
    switch (e.key) {
      case 'ArrowDown': return ir(i + 1);
      case 'ArrowUp': return ir(i - 1);
      case 'Home': return ir(0);
      case 'End': return ir(n - 1);
      case 'Enter': case ' ': e.preventDefault(); return this.elegir(this.opciones()[i].valor);
      case 'Tab': return this.cerrar();
    }
  }
}
