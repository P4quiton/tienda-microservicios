import { createPublicKey } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createApp } from './app.js';
import { catalogAvailability } from './catalog.js';
import { openPool } from './db.js';
import { cartStore } from './store.js';

const env = process.env;
const pool = openPool();
pool.on('error', () => console.error('Se interrumpió una conexión de PostgreSQL'));

try {
  const pem = await readFile(env.JWT_PUBLIC_KEY_PATH, 'utf8');
  if (!pem.includes('BEGIN PUBLIC KEY')) throw new Error('Formato de clave pública inválido');
  const publicKey = createPublicKey(pem);
  if (publicKey.asymmetricKeyType !== 'rsa' || publicKey.asymmetricKeyDetails.modulusLength < 2048) {
    throw new Error('Se requiere una clave pública RSA de 2048 bits o más');
  }
  if (!env.SERVICE_TOKEN_PEDIDOS_CARRITO || env.SERVICE_TOKEN_PEDIDOS_CARRITO === 'REPLACE_ME') {
    throw new Error('Falta el token interno de Pedidos');
  }

  const available = catalogAvailability({
    productsUrl: new URL(env.API_PRODUCTOS_URL),
    inventoryUrl: new URL(env.API_INVENTARIO_URL),
  });
  const app = createApp({
    store: cartStore(pool), available, publicKey, serviceToken: env.SERVICE_TOKEN_PEDIDOS_CARRITO,
    enableDraftCartCheckout: env.ENABLE_DRAFT_CART_CHECKOUT === 'true',
  });
  const port = Number(env.PORT ?? 8005);
  const server = app.listen(port, '0.0.0.0', () => console.log(`api-carrito escucha en ${port}`));
  const shutdown = () => server.close(() => void pool.end());
  process.once('SIGTERM', shutdown);
  process.once('SIGINT', shutdown);
} catch {
  console.error('No se pudo iniciar api-carrito. Revisa la configuración.');
  await pool.end();
  process.exitCode = 1;
}
