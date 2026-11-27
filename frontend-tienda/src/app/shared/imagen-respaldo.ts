const IMAGENES_POR_CATEGORIA: Record<string, string> = {
  electrónica: '/mock/electronica.svg',
  hogar: '/mock/hogar.svg',
  deportes: '/mock/deportes.svg',
  papelería: '/mock/papeleria.svg',
};

/** Sustituye una imagen rota por una ilustración local y evita bucles de error. */
export function usarImagenRespaldo(target: EventTarget | null, categoria: string): void {
  if (!(target instanceof HTMLImageElement)) return;
  const img = target;
  if (img.dataset['respaldoAplicado']) return;
  img.dataset['respaldoAplicado'] = 'true';
  const normalizada = categoria.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  img.src = IMAGENES_POR_CATEGORIA[normalizada] ?? '/mock/electronica.svg';
}
