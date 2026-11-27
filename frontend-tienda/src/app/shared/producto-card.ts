import { Component, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Producto } from '../datos/models';
import { Estrellas } from './estrellas';
import { MxnPipe } from './mxn.pipe';
import { usarImagenRespaldo } from './imagen-respaldo';

export interface ProductoResumen {
  producto: Producto;
  promedio: number | null;
  totalResenas: number;
  disponibles: number | null;
}

@Component({
  selector: 'app-producto-card',
  imports: [RouterLink, Estrellas, MxnPipe],
  template: `
    @let p = dato().producto;
    <article class="card tarjeta">
      <a [routerLink]="['/producto', p.id]" class="imagen"><img [src]="p.imagen_url || '/mock/electronica.svg'" (error)="usarImagenRespaldo($event.target, p.categoria)" [alt]="p.nombre" loading="lazy" width="400" height="300" /></a>
      <div class="cuerpo">
        <span class="etiqueta">{{ p.categoria }}</span>
        <h3><a [routerLink]="['/producto', p.id]">{{ p.nombre }}</a></h3>
        <p class="resenas muted">
          <app-estrellas [valor]="dato().promedio" [tam]="14" />
          @if (dato().promedio != null) { <strong>{{ dato().promedio }}</strong> ({{ dato().totalResenas }} reseñas) } @else { Sin reseñas }
        </p>
        <p class="precio">{{ p.precio | mxn }}</p>
        <p class="stock" [class.agotado]="dato().disponibles === 0">
          <span class="punto" aria-hidden="true"></span>
          @switch (true) {
            @case (dato().disponibles === null) { Consultando disponibilidad… }
            @case (dato().disponibles === 0) { Agotado }
            @default { Disponible · {{ dato().disponibles }} unidades }
          }
        </p>
        <button type="button" class="btn btn-primario" [disabled]="!dato().disponibles || agregando()" (click)="agregar.emit(p.id)">
          {{ agregando() ? 'Agregando…' : 'Agregar' }}
        </button>
      </div>
    </article>
  `,
  styles: `
    /* Tarjeta de cristal esmerilado con tinte pastel (--tono lo asigna el grid). */
    :host { display: block; --tono: 214 100% 92%; --tono-2: 260 100% 94%; }
    .card { position: relative; overflow: hidden; display: flex; flex-direction: column; height: 100%; padding: .6rem; border-radius: 30px;
      background:
        radial-gradient(110% 60% at 0% 0%, rgba(255,255,255,.55), transparent 50%),
        linear-gradient(160deg, hsl(var(--tono) / .95), hsl(var(--tono-2) / .85));
      -webkit-backdrop-filter: blur(18px) saturate(1.5); backdrop-filter: blur(18px) saturate(1.5);
      box-shadow: inset 0 0 0 1.5px rgba(255,255,255,.7), inset 0 2px 2px rgba(255,255,255,.9), inset 0 0 24px rgba(255,255,255,.4),
        0 20px 40px -22px hsl(var(--tono) / 1), 0 18px 36px -24px rgba(30,50,120,.35);
      transition: transform .35s var(--nb-ease), box-shadow .35s var(--nb-ease); }
    .card:hover { transform: translateY(-5px); box-shadow: inset 0 0 0 1.5px rgba(255,255,255,.85), inset 0 2px 2px #fff, inset 0 0 28px rgba(255,255,255,.5), 0 28px 50px -24px rgba(30,50,120,.45); }
    .imagen { position: relative; display: block; border-radius: 22px; overflow: hidden; background: rgba(255,255,255,.45);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.8), 0 10px 22px -14px rgba(30,50,120,.4); }
    .imagen::after { content: ''; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
      background: linear-gradient(180deg, rgba(255,255,255,.35), transparent 35%); box-shadow: inset 0 1px 1px rgba(255,255,255,.9); }
    .imagen:focus-visible { outline-offset: 3px; border-radius: 22px; }
    .imagen img { width: 100%; aspect-ratio: 4/3; object-fit: cover; transition: transform .5s var(--nb-ease); }
    .card:hover .imagen img { transform: scale(1.05); }
    .cuerpo { padding: .95rem .55rem .35rem; display: flex; flex-direction: column; gap: .35rem; flex: 1; align-items: flex-start; }
    .etiqueta { padding: .25rem .7rem; border-radius: 999px; font-size: .74rem; color: var(--noche);
      background: rgba(255,255,255,.55); box-shadow: var(--nb-lente-sombra); }
    h3 { font-size: 1.12rem; letter-spacing: -.01em; } h3 a { color: var(--noche); text-decoration: none; } h3 a:hover { text-decoration: underline; }
    .resenas, .precio, .stock { margin: 0; }
    .resenas { color: #3c4a6b; }
    .precio { font-size: 1.45rem; font-weight: 800; letter-spacing: -.02em; color: var(--noche); }
    .stock { font-size: .8rem; font-weight: 600; color: var(--ok); display: inline-flex; align-items: center; gap: .4rem;
      padding: .25rem .65rem; border-radius: 999px; background: rgba(255,255,255,.6); box-shadow: inset 0 0 0 1px rgba(255,255,255,.8); }
    .stock.agotado { color: var(--err); }
    .punto { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
    .btn { margin-top: auto; width: 100%; }
    .stock + .btn { margin-top: .7rem; }
    @media (prefers-reduced-motion: reduce) { .card:hover, .card:hover .imagen img { transform: none; } }
    @media (prefers-contrast: more) { .card { background: #fff; } }
  `,
})
export class ProductoCard {
  protected usarImagenRespaldo = usarImagenRespaldo;
  dato = input.required<ProductoResumen>();
  agregando = input(false);
  agregar = output<string>();
}
