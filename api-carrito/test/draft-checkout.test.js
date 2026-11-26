import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { test } from 'node:test';
import pg from 'pg';
import { createApp } from '../src/app.js';
import { cartStore } from '../src/store.js';

const user = randomUUID();
const product = randomUUID();
const secret = 'token-pedidos-pruebas';
const headers = { 'X-Service-Token': secret, 'Content-Type': 'application/json' };

async function withServer(options, run) {
  const server = createApp({ serviceToken: secret, ...options }).listen(0, '127.0.0.1');
  await once(server, 'listening');
  try { await run(`http://127.0.0.1:${server.address().port}/api/carrito/${user}/checkout`); }
  finally { await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve())); }
}

test('rutas experimentales requieren bandera y token de Pedidos', async () => {
  await withServer({ store: {} }, async (url) => {
    assert.equal((await fetch(url, { headers })).status, 404);
  });
  await withServer({ enableDraftCartCheckout: true, store: { checkout: async () => ({}) } }, async (url) => {
    assert.equal((await fetch(url)).status, 401);
    assert.equal((await fetch(url, { headers: { Authorization: 'Bearer cualquiera' } })).status, 401);
    assert.equal((await fetch(url, { headers })).status, 200);
    assert.equal((await fetch(url + '/preparar', { method: 'POST', headers, body: '{}' })).status, 422);
  });
});

test('protocolo HTTP conserva snapshot, rechaza conflictos y respeta adiciones', { skip: !process.env.TEST_DATABASE_URL }, async () => {
  const pool = new pg.Pool({ connectionString: process.env.TEST_DATABASE_URL });
  const store = cartStore(pool);
  try {
    await store.add({ actorId: user, userId: user, key: randomUUID(), productId: product, quantity: 2, available: async () => 10 });
    await withServer({ store, enableDraftCartCheckout: true }, async (url) => {
      const read = async () => (await (await fetch(url, { headers })).json()).data;
      const post = (action, payload) => fetch(url + '/' + action, { method: 'POST', headers, body: JSON.stringify(payload) });
      const snapshot = await read();
      assert.deepEqual(snapshot, { carrito_id: user, version: '1', items: [{ producto_id: product, cantidad: 2 }] });
      const payload = { pedido_id: randomUUID(), version: snapshot.version, items: snapshot.items };
      assert.equal((await post('preparar', { ...payload, version: '0' })).status, 409);
      assert.equal((await post('preparar', { ...payload, items: [{ producto_id: product, cantidad: 1 }] })).status, 409);
      assert.equal((await post('preparar', payload)).status, 200);
      assert.equal((await post('preparar', payload)).status, 200);
      const otherOrder = { ...payload, pedido_id: randomUUID() };
      assert.equal((await post('preparar', otherOrder)).status, 503);
      assert.equal((await post('preparar', { ...otherOrder, version: '0' })).status, 409);
      assert.equal((await post('confirmar', { ...payload, version: '0' })).status, 409);
      assert.equal((await post('cancelar', { ...payload, version: '0' })).status, 409);
      await store.add({ actorId: user, userId: user, key: randomUUID(), productId: product, quantity: 1, available: async () => 10 });
      const confirmations = await Promise.all([post('confirmar', payload), post('confirmar', payload)]);
      assert.deepEqual(confirmations.map((response) => response.status), [200, 200]);
      assert.deepEqual(await confirmations[0].json(), await confirmations[1].json());
      assert.equal((await read()).items[0].cantidad, 1);
      assert.equal((await post('cancelar', payload)).status, 409);
      const next = await read();
      const canceled = { pedido_id: randomUUID(), version: next.version, items: next.items };
      assert.equal((await post('preparar', canceled)).status, 200);
      assert.equal((await post('cancelar', canceled)).status, 200);
      assert.equal((await post('cancelar', canceled)).status, 200);
      assert.equal((await post('confirmar', canceled)).status, 409);
      assert.equal((await read()).items[0].cantidad, 1);
    });
  } finally { await pool.end(); }
});
