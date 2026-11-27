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
    .card { overflow: hidden; display: flex; flex-direction: column; height: 100%; padding: .55rem; transition: transform .25s ease, box-shadow .25s ease; }
    .card:hover { transform: translateY(-4px); box-shadow: var(--sombra-alta); }
    .imagen { display: block; border-radius: 16px; overflow: hidden; box-shadow: inset 0 0 0 1px rgba(255,255,255,.8); }
    .imagen img { width: 100%; aspect-ratio: 4/3; object-fit: cover; transition: transform .4s ease; }
    .card:hover .imagen img { transform: scale(1.04); }
    .cuerpo { padding: .9rem .6rem .6rem; display: flex; flex-direction: column; gap: .3rem; flex: 1; align-items: flex-start; }
    h3 { font-size: 1.05rem; } h3 a { color: inherit; text-decoration: none; } h3 a:hover { text-decoration: underline; }
    .resenas, .precio, .stock { margin: 0; }
    .precio { font-size: 1.35rem; font-weight: 800; letter-spacing: -.01em; color: var(--noche); }
    .stock { font-size: .82rem; color: var(--ok); display: flex; align-items: center; gap: .4rem; }
    .stock.agotado { color: var(--err); }
    .punto { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
    .btn { margin-top: auto; width: 100%; }
    .stock + .btn { margin-top: .6rem; }
  `,
})
export class ProductoCard {
  protected usarImagenRespaldo = usarImagenRespaldo;
  dato = input.required<ProductoResumen>();
  agregando = input(false);
  agregar = output<string>();
}
