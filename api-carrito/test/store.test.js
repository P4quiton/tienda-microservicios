import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, test } from 'node:test';
import pg from 'pg';
import { cartStore } from '../src/store.js';

const connectionString = process.env.TEST_DATABASE_URL;
const pool = connectionString ? new pg.Pool({ connectionString }) : null;
after(async () => pool?.end());

test('PostgreSQL serializa adiciones y consume el snapshot una sola vez', { skip: !pool }, async () => {
  const store = cartStore(pool);
  const userId = randomUUID();
  const productId = randomUUID();
  const otherProduct = randomUUID();
  const orderId = randomUUID();
  const idempotent = {
    actorId: userId,
    userId,
    key: randomUUID(),
    productId,
    quantity: 2,
    available: async () => 10,
  };
  const results = await Promise.all([store.add(idempotent), store.add(idempotent)]);
  assert.deepEqual(results[0], results[1]);
  assert.equal(results[0].items[0].cantidad, 2);
  await assert.rejects(store.add({ ...idempotent, quantity: 3 }), { status: 409 });

  const snapshot = await store.prepareCheckout(userId, orderId);
  assert.equal(snapshot.items[0].cantidad, 2);
  await assert.rejects(store.prepareCheckout(userId, randomUUID()), { status: 503 });
  await Promise.all([
    store.add({ ...idempotent, key: randomUUID(), quantity: 1 }),
    store.add({ ...idempotent, key: randomUUID(), productId: otherProduct, quantity: 2 }),
  ]);
  assert.deepEqual(await store.prepareCheckout(userId, orderId), snapshot);

  const confirmations = await Promise.all([
    store.finishCheckout(userId, orderId), store.finishCheckout(userId, orderId),
  ]);
  assert.deepEqual(confirmations[0], confirmations[1]);
  assert.deepEqual(Object.fromEntries(confirmations[0].items.map((line) => [line.producto_id, line.cantidad])), {
    [productId]: 1, [otherProduct]: 2,
  });
  assert.deepEqual(await store.list(userId), confirmations[0]);
  const nextOrderId = randomUUID();
  await store.prepareCheckout(userId, nextOrderId);
  await store.cancelCheckout(userId, nextOrderId);
  await store.cancelCheckout(userId, nextOrderId);
  assert.deepEqual(await store.list(userId), confirmations[0]);
  await assert.rejects(store.finishCheckout(userId, nextOrderId), { status: 409 });
  const lastOrderId = randomUUID();
  await store.prepareCheckout(userId, lastOrderId);
  assert.deepEqual(await store.finishCheckout(userId, lastOrderId), { usuario_id: userId, items: [] });
});

test('la disponibilidad excluye el snapshot pendiente y limita nuevas unidades', { skip: !pool }, async () => {
  const store = cartStore(pool);
  const userId = randomUUID();
  const productId = randomUUID();
  const addition = { actorId: userId, userId, productId, key: randomUUID(), quantity: 2, available: async () => 2 };
  await store.add(addition);
  const snapshot = await store.checkout(userId);
  const expected = { version: snapshot.version, items: snapshot.items };
  await store.prepareCheckout(userId, randomUUID(), expected);

  const next = { ...addition, key: randomUUID(), quantity: 1, available: async () => 1 };
  assert.equal((await store.add(next)).items[0].cantidad, 3);
  await assert.rejects(store.add({ ...next, key: randomUUID() }), { status: 409 });
  await assert.rejects(store.prepareCheckout(userId, randomUUID(), expected), { status: 409 });
  const current = await store.checkout(userId);
  await assert.rejects(store.prepareCheckout(userId, randomUUID(), current), { status: 503 });
});
