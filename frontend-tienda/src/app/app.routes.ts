import { Routes } from '@angular/router';
import { requiereSesion } from './datos/sesion-ui';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'catalogo' },
  { path: 'catalogo', title: 'Catálogo · Nébula', loadComponent: () => import('./pages/catalogo/catalogo').then((m) => m.Catalogo) },
  { path: 'producto/:id', title: 'Producto · Nébula', loadComponent: () => import('./pages/producto/producto').then((m) => m.ProductoDetalle) },
  { path: 'acceso', title: 'Acceso · Nébula', loadComponent: () => import('./pages/acceso/acceso').then((m) => m.Acceso) },
  { path: 'checkout', canActivate: [requiereSesion], title: 'Carrito · Nébula', loadComponent: () => import('./pages/checkout/checkout').then((m) => m.Checkout) },
  { path: 'mis-pedidos', canActivate: [requiereSesion], title: 'Mis pedidos · Nébula', loadComponent: () => import('./pages/pedidos/pedidos').then((m) => m.MisPedidos) },
  { path: '**', redirectTo: 'catalogo' },
];
