// Regresion E2E: con la BD congelada (docker pause) tras haber conectado, /ready colgaba sin responder.
// Causa: solo existia statement_timeout (lo aplica el servidor). Ahora hay query_timeout en el cliente
// y el error resultante se traduce a 503.
import './env-limites-altos.js';
import assert from 'node:assert/strict';
import { generateKeyPairSync } from 'node:crypto';
import { once } from 'node:events';
import { after, before, test } from 'node:test';
import { createApp } from '../src/app.js';
import { openPool } from '../src/db.js';

const { publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
let server;
let base;

before(async () => {
  const app = createApp({
    publicKey,
    serviceToken: 'token-solo-pruebas',
    available: async () => 5,
    store: {
      ready: async () => { throw new Error('Query read timeout'); },
      list: async () => { throw new Error('Query read timeout'); },
    },
  });
  server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  base = `http://127.0.0.1:${server.address().port}`;
});

after(() => server.close());

test('el pool define un timeout de consulta en el cliente', async () => {
  const pool = openPool({ DB_HOST: '127.0.0.1', DB_PORT: '1', DB_DATABASE: 'x', DB_USERNAME: 'x', DB_PASSWORD: 'x' });
  assert.ok(pool.options.query_timeout > 0 && pool.options.query_timeout <= 10000, String(pool.options.query_timeout));
  await pool.end();
});

test('un "Query read timeout" del driver responde 503 en /ready y en las rutas de negocio', async () => {
  assert.equal((await fetch(base + '/ready')).status, 503);
  const res = await fetch(`${base}/api/carrito/00000000-0000-4000-8000-000000000000`, { headers: { 'X-Service-Token': 'token-solo-pruebas' } });
  assert.equal(res.status, 503);
});
