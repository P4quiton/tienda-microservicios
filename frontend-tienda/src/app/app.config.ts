import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';

import { routes } from './app.routes';
import { TIENDA_DATOS } from './datos/tienda-datos';
import { SESION_UI } from './datos/sesion-ui';
import { MockSesionUi } from './mock/mock-sesion-ui';
import { MockTiendaDatos } from './mock/mock-tienda-datos';
import { apiInterceptor } from './core/api/api.interceptor';
import { HttpTiendaDatos } from './datos/http-tienda-datos';
import { HttpSesionUi } from './datos/http-sesion-ui';

const MODO_APP_KEY = 'nebula.app.mode';
const modoSolicitado = new URLSearchParams(location.search).get('mode');
if (modoSolicitado === 'api' || modoSolicitado === 'mock') {
  sessionStorage.setItem(MODO_APP_KEY, modoSolicitado);
}
const usarApi = (modoSolicitado ?? sessionStorage.getItem(MODO_APP_KEY)) === 'api';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideHttpClient(withInterceptors([apiInterceptor])),
    provideRouter(routes, withComponentInputBinding(), withInMemoryScrolling({ scrollPositionRestoration: 'top' })),
    { provide: MockTiendaDatos, useClass: MockTiendaDatos },
    { provide: HttpTiendaDatos, useClass: HttpTiendaDatos },
    { provide: MockSesionUi, useClass: MockSesionUi },
    { provide: HttpSesionUi, useClass: HttpSesionUi },
    {
      provide: TIENDA_DATOS,
      useFactory: (mock: MockTiendaDatos, live: HttpTiendaDatos) => usarApi ? live : mock,
      deps: [MockTiendaDatos, HttpTiendaDatos],
    },
    {
      provide: SESION_UI,
      useFactory: (mock: MockSesionUi, live: HttpSesionUi) => usarApi ? live : mock,
      deps: [MockSesionUi, HttpSesionUi],
    },
  ]
};
