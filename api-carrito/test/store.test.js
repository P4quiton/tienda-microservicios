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
  assert.equal(results[0].version, 1);
  await assert.rejects(store.add({ ...idempotent, quantity: 3 }), { status: 409 });

  const start = (id, version) => store.start({ userId, key: randomUUID(), orderId: id, originalVersion: version });
  const finish = (id, snapshot, key = randomUUID()) => store.finish({
    userId, key, orderId: id, originalVersion: snapshot.version_original, items: snapshot.items,
  });
  const snapshot = await start(orderId, 1);
  assert.equal(snapshot.items[0].cantidad, 2);
  await assert.rejects(start(randomUUID(), 1), { status: 409 });
  await Promise.all([
    store.add({ ...idempotent, key: randomUUID(), quantity: 1 }),
    store.add({ ...idempotent, key: randomUUID(), productId: otherProduct, quantity: 2 }),
  ]);
  assert.deepEqual(await start(orderId, 1), snapshot);

  const confirmations = await Promise.all([finish(orderId, snapshot), finish(orderId, snapshot)]);
  assert.deepEqual(confirmations[0], confirmations[1]);
  assert.deepEqual(Object.fromEntries(confirmations[0].items.map((line) => [line.producto_id, line.cantidad])), {
    [productId]: 1, [otherProduct]: 2,
  });
  assert.deepEqual(await store.list(userId), confirmations[0]);
  const next = confirmations[0];
  const nextOrderId = randomUUID();
  const second = await start(nextOrderId, next.version);
  await store.release({ userId, key: randomUUID(), orderId: nextOrderId });
  await store.release({ userId, key: randomUUID(), orderId: nextOrderId });
  assert.deepEqual(await store.list(userId), next);
  await assert.rejects(finish(nextOrderId, second), { status: 409 });
  const lastOrderId = randomUUID();
  const last = await start(lastOrderId, next.version);
  const emptied = await finish(lastOrderId, last);
  assert.deepEqual(emptied, { usuario_id: userId, items: [], version: next.version + 1 });
});

test('la disponibilidad excluye el snapshot pendiente y limita nuevas unidades', { skip: !pool }, async () => {
  const store = cartStore(pool);
  const userId = randomUUID();
  const productId = randomUUID();
  const addition = { actorId: userId, userId, productId, key: randomUUID(), quantity: 2, available: async () => 2 };
  const cart = await store.add(addition);
  await store.start({ userId, key: randomUUID(), orderId: randomUUID(), originalVersion: cart.version });

  const next = { ...addition, key: randomUUID(), quantity: 1, available: async () => 1 };
  assert.equal((await store.add(next)).items[0].cantidad, 3);
  await assert.rejects(store.add({ ...next, key: randomUUID() }), { status: 409 });
  await assert.rejects(
    store.start({ userId, key: randomUUID(), orderId: randomUUID(), originalVersion: cart.version }),
    { status: 409 },
  );
});
