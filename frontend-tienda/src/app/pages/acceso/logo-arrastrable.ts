import { Directive, ElementRef, inject } from '@angular/core';

type Muestra = { t: number; v: number };
type Eje = { el: HTMLElement; anim?: Animation; muestras: Muestra[]; base: number; min: number; max: number; desfase: number };

const MUESTRAS = 240;

/** Lee el `translate` calculado de un elemento como [x, y] en px. */
function leer(el: HTMLElement): [number, number] {
  const [x = 0, y = 0] = getComputedStyle(el).translate.split(' ').map((v) => parseFloat(v) || 0);
  return [x, y];
}

/**
 * Emblema agarrable: dentro de su recuadro, el usuario lo toma con el cursor de mano y lo
 * mueve libremente sin salir de los límites. Al soltarlo, las animaciones CSS de deriva (X)
 * y flotación (Y) continúan desde el instante cuya posición coincide con el punto de suelta,
 * de modo que el logo retoma su vuelo sin saltos.
 */
@Directive({
  selector: '[appLogoArrastrable]',
  host: {
    '(pointerdown)': 'agarrar($event)',
    '(pointermove)': 'mover($event)',
    '(pointerup)': 'soltar()',
    '(pointercancel)': 'soltar()',
  },
})
export class LogoArrastrable {
  private host: ElementRef<HTMLElement> = inject(ElementRef);
  private arrastre: { x: Eje; y: Eje; px: number; py: number; sombra?: Animation } | null = null;

  private animacion(el: HTMLElement, nombre: string) {
    return el.getAnimations().find((a) => (a as CSSAnimation).animationName === nombre);
  }

  /** Recorre un ciclo completo (ida y vuelta, por `alternate`) para conocer posiciones y límites. */
  private eje(el: HTMLElement, nombre: string, i: 0 | 1, respaldo: [number, number]): Eje {
    const anim = this.animacion(el, nombre);
    const base = leer(el)[i];
    if (!anim) return { el, muestras: [], base, min: respaldo[0], max: respaldo[1], desfase: 0 };
    anim.pause();
    const t0 = Number(anim.currentTime);
    const total = Number(anim.effect!.getComputedTiming().duration) * 2;
    const muestras: Muestra[] = [];
    for (let k = 0; k <= MUESTRAS; k++) {
      anim.currentTime = (total * k) / MUESTRAS;
      muestras.push({ t: total * k / MUESTRAS, v: leer(el)[i] });
    }
    anim.currentTime = t0;
    const vs = muestras.map((m) => m.v);
    return { el, anim, muestras, base, min: Math.min(...vs), max: Math.max(...vs), desfase: 0 };
  }

  protected agarrar(e: PointerEvent) {
    const agarre = (e.target as HTMLElement).closest<HTMLElement>('.logo-agarre');
    if (!agarre || this.arrastre) return;
    e.preventDefault();
    const raiz = this.host.nativeElement;
    const deriva = raiz.querySelector<HTMLElement>('.logo-deriva')!;
    const flota = raiz.querySelector<HTMLElement>('.logo-flota')!;
    // Límites de respaldo (sin animación, p. ej. con movimiento reducido)
    const libreX = raiz.clientWidth - deriva.offsetWidth - 20;
    const libreY = raiz.clientHeight - flota.offsetHeight - 34;
    const x = this.eje(deriva, 'logo-deriva', 0, [20, libreX]);
    const y = this.eje(flota, 'logo-flota', 1, [8, libreY]);
    x.desfase = this.desfaseActual(deriva, 0);
    y.desfase = this.desfaseActual(flota, 1);
    const sombra = this.animacion(raiz.querySelector<HTMLElement>('.logo-3d-sombra')!, 'logo-sombra');
    sombra?.pause();
    this.arrastre = { x, y, px: e.clientX - x.desfase, py: e.clientY - y.desfase, sombra };
    agarre.setPointerCapture(e.pointerId);
    raiz.classList.add('agarrado');
    document.documentElement.classList.add('nb-agarrando');
  }

  protected mover(e: PointerEvent) {
    const a = this.arrastre;
    if (!a) return;
    const dx = this.limitar(a.x, e.clientX - a.px);
    const dy = this.limitar(a.y, e.clientY - a.py);
    this.aplicar(a.x.el, dx, 0, false);
    this.aplicar(a.y.el, 0, dy, false);
    // Inclinación según la velocidad horizontal, como si el objeto tuviera inercia
    const inclina = Math.max(-18, Math.min(18, e.movementX * 1.6));
    this.host.nativeElement.style.setProperty('--inclina', `${inclina}deg`);
  }

  protected soltar() {
    const a = this.arrastre;
    if (!a) return;
    this.arrastre = null;
    const raiz = this.host.nativeElement;
    raiz.classList.remove('agarrado');
    raiz.style.removeProperty('--inclina');
    document.documentElement.classList.remove('nb-agarrando');
    this.retomar(a.x, 0);
    // La sombra comparte duración con la flotación: se sincroniza con su nuevo instante
    const tFlota = this.retomar(a.y, 1);
    if (a.sombra && tFlota !== null) a.sombra.currentTime = tFlota;
    a.sombra?.play();
  }

  /** Desplazamiento manual vigente (si se agarra de nuevo mientras vuelve a su trayectoria). */
  private desfaseActual(el: HTMLElement, i: 0 | 1) {
    const m = new DOMMatrixReadOnly(getComputedStyle(el).transform);
    return i === 0 ? m.m41 : m.m42;
  }

  private limitar(eje: Eje, d: number) {
    return Math.max(eje.min, Math.min(eje.max, eje.base + d)) - eje.base;
  }

  private aplicar(el: HTMLElement, dx: number, dy: number, suave: boolean) {
    el.style.transition = suave ? 'transform .6s cubic-bezier(.22, 1, .36, 1)' : 'none';
    el.style.transform = dx || dy ? `translate(${dx}px, ${dy}px)` : '';
  }

  /** Salta la animación al instante más cercano al punto de suelta y absorbe el residuo con suavidad. */
  private retomar(eje: Eje, i: 0 | 1): number | null {
    const destino = eje.base + (i === 0 ? this.desfaseActual(eje.el, 0) : this.desfaseActual(eje.el, 1));
    if (!eje.anim || !eje.muestras.length) return null;
    let mejor = eje.muestras[0];
    for (const m of eje.muestras) if (Math.abs(m.v - destino) < Math.abs(mejor.v - destino)) mejor = m;
    eje.anim.currentTime = mejor.t;
    const residuo = destino - leer(eje.el)[i];
    this.aplicar(eje.el, i === 0 ? residuo : 0, i === 1 ? residuo : 0, false);
    eje.anim.play();
    requestAnimationFrame(() => requestAnimationFrame(() => this.aplicar(eje.el, 0, 0, true)));
    return mejor.t;
  }
}
