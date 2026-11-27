import { Pipe, PipeTransform } from '@angular/core';
import { aCentavos } from '../datos/dinero';

const fmt = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' });

@Pipe({ name: 'mxn' })
export class MxnPipe implements PipeTransform {
  transform(m: string | null | undefined): string {
    return m ? `${fmt.format(aCentavos(m) / 100)} MXN` : '';
  }
}
