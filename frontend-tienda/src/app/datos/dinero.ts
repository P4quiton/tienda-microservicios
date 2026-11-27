import { Monto } from './models';

/** Convierte "899.99" a centavos enteros para sumar sin float. */
export function aCentavos(m: Monto): number {
  const [e, d = '00'] = m.split('.');
  return Number(e) * 100 + Number(d.padEnd(2, '0').slice(0, 2));
}

export function deCentavos(c: number): Monto {
  return `${Math.floor(c / 100)}.${String(c % 100).padStart(2, '0')}`;
}
