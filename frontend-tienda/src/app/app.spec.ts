import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { App } from './app';
import { TIENDA_DATOS } from './datos/tienda-datos';
import { SESION_UI } from './datos/sesion-ui';
import { MockSesionUi } from './mock/mock-sesion-ui';
import { MockTiendaDatos } from './mock/mock-tienda-datos';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([]), { provide: TIENDA_DATOS, useClass: MockTiendaDatos }, { provide: SESION_UI, useClass: MockSesionUi }],
    }).compileComponents();
  });

  it('muestra la marca Nébula en el encabezado', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const logo = fixture.nativeElement.querySelector('.marca img') as HTMLImageElement;
    expect(logo.alt).toBe('Nébula');
  });
});
