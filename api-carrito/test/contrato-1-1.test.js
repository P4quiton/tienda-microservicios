// Contrato 1.1.0: version y linea_id, y endpoints internos iniciar/finalizar/liberar/vaciar.
// Las pruebas con base de datos se omiten sin TEST_DATABASE_URL (PostgreSQL 17 con las migraciones aplicadas).
import assert from 'node:assert/strict';
import { generateKeyPairSync, randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { readFileSync, readdirSync } from 'node:fs';
import { after, describe, test } from 'node:test';
import { SignJWT } from 'jose';
import pg from 'pg';
import { createApp } from '../src/app.js';
import { cartStore } from '../src/store.js';

const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const SERVICE = 'token-pedidos-contrato';
const connectionString = process.env.TEST_DATABASE_URL;
const pool = connectionString ? new pg.Pool({ connectionString }) : null;
const servers = [];

async function listen(options) {
  const server = createApp({ publicKey, serviceToken: SERVICE, ...options }).listen(0, '127.0.0.1');
  await once(server, 'listening');
  servers.push(server);
  return 'http://127.0.0.1:' + server.address().port;
}
after(async () => {
  await Promise.all(servers.map((s) => new Promise((r) => s.close(r))));
  await pool?.end();
});

const jwt = (sub) => new SignJWT({ role: 'cliente' }).setProtectedHeader({ alg: 'RS256' }).setSubject(sub)
  .setIssuer('api-usuarios').setAudience('tienda-microservicios').setIssuedAt().setExpirationTime('1h').sign(privateKey);

// Cliente HTTP mínimo sobre una aplicación.
function client(base) {
  const internal = { 'X-Service-Token': SERVICE, 'Content-Type': 'application/json' };
  const call = async (method, path, headers, body) => {
    const res = await fetch(base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    return { status: res.status, body: await res.json() };
  };
  return {
    get: (user) => call('GET', `/api/carrito/${user}`, { 'X-Service-Token': SERVICE }),
    add: async (user, producto_id, cantidad, key = randomUUID()) => call('POST', `/api/carrito/${user}/agregar`,
      { Authorization: 'Bearer ' + await jwt(user), 'Content-Type': 'application/json', 'Idempotency-Key': key },
      { producto_id, cantidad }),
    start: (user, body, key = randomUUID()) => call('POST', `/api/carrito/${user}/iniciar`, { ...internal, 'Idempotency-Key': key }, body),
    finish: (user, body, key = randomUUID()) => call('POST', `/api/carrito/${user}/finalizar`, { ...internal, 'Idempotency-Key': key }, body),
    release: (user, body, key = randomUUID()) => call('POST', `/api/carrito/${user}/liberar`, { ...internal, 'Idempotency-Key': key }, body),
    clear: (user, key = randomUUID()) => call('DELETE', `/api/carrito/${user}/vaciar`, { ...internal, 'Idempotency-Key': key }),
    raw: call,
    internal,
  };
}

const qty = (cart, product) => cart.items.find((line) => line.producto_id === product)?.cantidad;

describe('contrato 1.1.0: validación y credenciales (sin BD)', () => {
  const user = randomUUID();
  const order = randomUUID();
  const line = { producto_id: randomUUID(), cantidad: 1, linea_id: randomUUID() };
  const calls = [];
  const record = (name) => async (input) => { calls.push([name, input]); return { usuario_id: user, items: [], version: 0 }; };
  const store = { start: record('start'), finish: record('finish'), release: record('release'), clear: record('clear') };
  const valid = {
    iniciar: { pedido_id: order, version_original: 3 },
    finalizar: { pedido_id: order, version_original: 3, items: [line] },
    liberar: { pedido_id: order },
  };

  test('las rutas experimentales /checkout/* ya no existen', async () => {
    const c = client(await listen({ store, enableDraftCartCheckout: true }));
    for (const path of ['checkout', 'checkout/preparar', 'checkout/confirmar', 'checkout/cancelar']) {
      const res = await c.raw(path === 'checkout' ? 'GET' : 'POST', `/api/carrito/${user}/${path}`, c.internal, path === 'checkout' ? undefined : {});
      assert.equal(res.status, 404, path);
    }
  });

  test('exigen X-Service-Token de Pedidos: sin credencial, JWT o token ajeno dan 401', async () => {
    const c = client(await listen({ store }));
    const jwtHeader = { Authorization: 'Bearer ' + await jwt(user), 'Content-Type': 'application/json', 'Idempotency-Key': randomUUID() };
    for (const action of ['iniciar', 'finalizar', 'liberar']) {
      const path = `/api/carrito/${user}/${action}`;
      const key = { 'Idempotency-Key': randomUUID() };
      assert.equal((await c.raw('POST', path, { 'Content-Type': 'application/json', ...key }, valid[action])).status, 401, action);
      assert.equal((await c.raw('POST', path, jwtHeader, valid[action])).status, 401, action);
      assert.equal((await c.raw('POST', path, { 'X-Service-Token': 'otro', 'Content-Type': 'application/json', ...key }, valid[action])).status, 401, action);
    }
    assert.equal(calls.length, 0);
  });

  test('exigen Idempotency-Key UUID y cuerpo exacto del contrato (422)', async () => {
    const c = client(await listen({ store }));
    for (const action of ['iniciar', 'finalizar', 'liberar']) {
      const path = `/api/carrito/${user}/${action}`;
      const send = (body, key = randomUUID()) => c.raw('POST', path, { ...c.internal, ...(key && { 'Idempotency-Key': key }) }, body);
      assert.equal((await send(valid[action], null)).status, 422, action + ' sin clave');
      assert.equal((await send(valid[action], 'no-es-uuid')).status, 422, action + ' clave inválida');
      assert.equal((await send({ ...valid[action], precio: 1 })).status, 422, action + ' campo extra');
      assert.equal((await send({ ...valid[action], pedido_id: 'x' })).status, 422, action + ' pedido_id');
      assert.equal((await send({})).status, 422, action + ' vacío');
      assert.equal((await send([])).status, 422, action + ' arreglo');
    }
    const start = (body) => c.start(user, body);
    for (const version_original of ['3', -1, 1.5, null, undefined, 2 ** 60]) {
      assert.equal((await start({ pedido_id: order, version_original })).status, 422, String(version_original));
    }
    const finish = (items) => c.finish(user, { ...valid.finalizar, items });
    for (const items of [[], [{ ...line, linea_id: 'x' }], [{ ...line, cantidad: 0 }], [{ ...line, cantidad: '1' }],
      [{ producto_id: line.producto_id, cantidad: 1 }], [{ ...line, extra: 1 }], [line, line],
      [line, { ...line, producto_id: randomUUID() }], 'texto']) {
      assert.equal((await finish(items)).status, 422, JSON.stringify(items));
    }
    assert.equal((await c.start('no-uuid', valid.iniciar)).status, 422);
    assert.equal(calls.length, 0);
  });

  test('entrega a la capa de datos usuario, clave, pedido y versión', async () => {
    const c = client(await listen({ store }));
    const key = randomUUID();
    assert.equal((await c.start(user, valid.iniciar, key)).status, 200);
    assert.equal((await c.finish(user, valid.finalizar, key)).status, 200);
    assert.equal((await c.release(user, valid.liberar, key)).status, 200);
    assert.equal((await c.clear(user, key)).status, 200);
    assert.deepEqual(calls.map(([name]) => name), ['start', 'finish', 'release', 'clear']);
    assert.deepEqual({ ...calls[0][1] }, { userId: user, key, orderId: order, originalVersion: 3 });
    assert.deepEqual({ ...calls[1][1] }, { userId: user, key, orderId: order, originalVersion: 3, items: [line] });
    assert.deepEqual({ ...calls[2][1] }, { userId: user, key, orderId: order });
    assert.deepEqual({ ...calls[3][1] }, { userId: user, key });
  });

  test('vaciar exige Idempotency-Key y solo Pedidos', async () => {
    const c = client(await listen({ store }));
    assert.equal((await c.raw('DELETE', `/api/carrito/${user}/vaciar`, { 'X-Service-Token': SERVICE })).status, 422);
    assert.equal((await c.raw('DELETE', `/api/carrito/${user}/vaciar`, { 'Idempotency-Key': randomUUID() })).status, 401);
  });
});

describe('contrato 1.1.0 (PostgreSQL real)', { skip: !pool }, () => {
  const available = async () => 1000;
  let c;
  const ready = (async () => { c = client(await listen({ store: cartStore(pool), available })); })();
  const fresh = async () => { await ready; return { user: randomUUID(), product: randomUUID() }; };
  const begin = async (user, order = randomUUID()) => {
    const cart = (await c.get(user)).body.data;
    const res = await c.start(user, { pedido_id: order, version_original: cart.version });
    return { order, cart, res, snapshot: res.body.data };
  };
  const finishBody = (snapshot) => ({ pedido_id: snapshot.pedido_id, version_original: snapshot.version_original, items: snapshot.items });

  test('GET devuelve version 0 vacío; agregar incrementa cantidad y versión y conserva linea_id', async () => {
    const { user, product } = await fresh();
    assert.deepEqual((await c.get(user)).body.data, { usuario_id: user, items: [], version: 0 });
    const first = (await c.add(user, product, 2)).body.data;
    assert.equal(first.version, 1);
    assert.equal(first.items.length, 1);
    assert.match(first.items[0].linea_id, /^[0-9a-f-]{36}$/);
    const key = randomUUID();
    const second = await c.add(user, product, 1, key);
    assert.equal(second.body.data.items[0].cantidad, 3);
    assert.equal(second.body.data.version, 2);
    assert.equal(second.body.data.items[0].linea_id, first.items[0].linea_id);
    assert.deepEqual((await c.add(user, product, 1, key)).body, second.body);
    assert.deepEqual((await c.get(user)).body.data, second.body.data);
  });

  test('aceptación: 2 en compra y 1 añadida durante el pago; aprobado deja 1 y repetir finalizar sigue en 1', async () => {
    const { user, product } = await fresh();
    await c.add(user, product, 2);
    const { snapshot, res } = await begin(user);
    assert.equal(res.status, 200);
    assert.deepEqual(Object.keys(snapshot).sort(), ['items', 'pedido_id', 'version_original']);
    assert.equal(snapshot.version_original, 1);
    await c.add(user, product, 1);
    const key = randomUUID();
    const done = await c.finish(user, finishBody(snapshot), key);
    assert.equal(done.status, 200);
    assert.equal(qty(done.body.data, product), 1);
    assert.equal(done.body.data.version, 3);
    assert.equal(done.body.data.items[0].linea_id, snapshot.items[0].linea_id);
    const sameKey = await c.finish(user, finishBody(snapshot), key);
    const otherKey = await c.finish(user, finishBody(snapshot));
    assert.deepEqual(sameKey.body, done.body);
    assert.deepEqual(otherKey.body, done.body);
    assert.equal(qty((await c.get(user)).body.data, product), 1);
  });

  test('aceptación: cancelado o rechazado conserva las 3 unidades y repetir liberar no cambia nada', async () => {
    const { user, product } = await fresh();
    await c.add(user, product, 2);
    const { snapshot, order } = await begin(user);
    await c.add(user, product, 1);
    const before = (await c.get(user)).body.data;
    const released = await c.release(user, { pedido_id: order });
    assert.equal(released.status, 200);
    assert.deepEqual(released.body.data, before);
    assert.equal(qty(released.body.data, product), 3);
    assert.deepEqual((await c.release(user, { pedido_id: order })).body.data, before);
    assert.equal((await c.finish(user, finishBody(snapshot))).status, 409);
    assert.deepEqual((await c.get(user)).body.data, before);
  });

  test('iniciar: versión distinta, carrito vacío y segundo checkout activo dan 409; repetir devuelve el snapshot original', async () => {
    const { user, product } = await fresh();
    assert.equal((await c.start(user, { pedido_id: randomUUID(), version_original: 0 })).status, 409);
    await c.add(user, product, 2);
    assert.equal((await c.start(user, { pedido_id: randomUUID(), version_original: 0 })).status, 409);
    const { order, snapshot } = await begin(user);
    assert.equal((await c.start(user, { pedido_id: randomUUID(), version_original: 1 })).status, 409);
    await c.add(user, product, 5);
    const again = await c.start(user, { pedido_id: order, version_original: 1 });
    assert.equal(again.status, 200);
    assert.deepEqual(again.body.data, snapshot);
    assert.equal((await c.start(user, { pedido_id: order, version_original: 2 })).status, 409);
    const key = randomUUID();
    const first = await c.start(user, { pedido_id: order, version_original: 1 }, key);
    assert.equal((await c.start(user, { pedido_id: order, version_original: 1 }, key)).status, 200);
    assert.equal((await c.start(user, { pedido_id: randomUUID(), version_original: 1 }, key)).status, 409);
    assert.equal(first.status, 200);
  });

  test('iniciar de un pedido ajeno a otro carrito da 409 y no registra nada', async () => {
    const a = await fresh();
    const b = await fresh();
    await c.add(a.user, a.product, 1);
    await c.add(b.user, b.product, 1);
    const { order } = await begin(a.user);
    assert.equal((await c.start(b.user, { pedido_id: order, version_original: 1 })).status, 409);
    assert.equal((await c.release(b.user, { pedido_id: order })).status, 409);
  });

  test('finalizar valida snapshot, versión original y items exactos (409) sin tocar el carrito', async () => {
    const { user, product } = await fresh();
    await c.add(user, product, 2);
    const { snapshot } = await begin(user);
    const good = finishBody(snapshot);
    const bad = [
      { ...good, version_original: 0 },
      { ...good, pedido_id: randomUUID() },
      { ...good, items: [{ ...good.items[0], cantidad: 1 }] },
      { ...good, items: [{ ...good.items[0], linea_id: randomUUID() }] },
      { ...good, items: [{ ...good.items[0], producto_id: randomUUID() }] },
      { ...good, items: [...good.items, { producto_id: randomUUID(), cantidad: 1, linea_id: randomUUID() }] },
    ];
    for (const body of bad) assert.equal((await c.finish(user, body)).status, 409, JSON.stringify(body));
    assert.equal(qty((await c.get(user)).body.data, product), 2);
    assert.equal((await c.finish(user, good)).status, 200);
  });

  test('finalizar retira por linea_id, conserva otras líneas y adiciones, y una línea retirada recibe linea_id nuevo', async () => {
    const { user, product } = await fresh();
    const other = randomUUID();
    await c.add(user, product, 2);
    const { snapshot } = await begin(user);
    await c.add(user, other, 4);
    const done = (await c.finish(user, finishBody(snapshot))).body.data;
    assert.deepEqual(done.items.map((line) => [line.producto_id, line.cantidad]), [[other, 4]]);
    assert.equal(done.version, 3);
    const again = (await c.add(user, product, 1)).body.data;
    const reborn = again.items.find((line) => line.producto_id === product);
    assert.notEqual(reborn.linea_id, snapshot.items[0].linea_id);
    assert.equal(again.version, 4);
  });

  test('tras finalizar o liberar, el siguiente checkout puede iniciarse; liberar tras finalizar da 409', async () => {
    const { user, product } = await fresh();
    await c.add(user, product, 1);
    const one = await begin(user);
    assert.equal((await c.finish(user, finishBody(one.snapshot))).status, 200);
    assert.equal((await c.release(user, { pedido_id: one.order })).status, 409);
    await c.add(user, product, 1);
    const two = await begin(user);
    assert.equal(two.res.status, 200);
    assert.equal((await c.release(user, { pedido_id: two.order })).status, 200);
    const three = await begin(user);
    assert.equal(three.res.status, 200);
    assert.equal((await c.start(user, { pedido_id: two.order, version_original: two.snapshot.version_original })).status, 409);
  });

  test('liberar sin snapshot registra el cierre: el inicio tardío del mismo pedido se rechaza', async () => {
    const { user, product } = await fresh();
    await c.add(user, product, 1);
    const order = randomUUID();
    const released = await c.release(user, { pedido_id: order });
    assert.equal(released.status, 200);
    assert.equal(qty(released.body.data, product), 1);
    assert.equal((await c.release(user, { pedido_id: order })).status, 200);
    assert.equal((await c.start(user, { pedido_id: order, version_original: 1 })).status, 409);
    assert.equal((await begin(user)).res.status, 200);
  });

  test('vaciar: 409 con checkout activo; fuera de checkout vacía, sube la versión una vez y es idempotente', async () => {
    const { user, product } = await fresh();
    const empty = await c.clear(user);
    assert.deepEqual(empty.body.data, { usuario_id: user, items: [], version: 0 });
    await c.add(user, product, 2);
    const { order } = await begin(user);
    assert.equal((await c.clear(user)).status, 409);
    await c.release(user, { pedido_id: order });
    const key = randomUUID();
    const cleared = await c.clear(user, key);
    assert.equal(cleared.status, 200);
    assert.deepEqual(cleared.body.data, { usuario_id: user, items: [], version: 2 });
    assert.deepEqual((await c.clear(user, key)).body, cleared.body);
    assert.equal((await c.clear(user)).body.data.version, 2);
    const next = (await c.add(user, product, 1)).body.data;
    assert.equal(next.version, 3);
  });

  test('concurrencia: agregar durante finalizar no pierde ni duplica unidades', async () => {
    for (let round = 0; round < 5; round++) {
      const { user, product } = await fresh();
      const other = randomUUID();
      await c.add(user, product, 4);
      const { snapshot } = await begin(user);
      const adds = Array.from({ length: 12 }, (_, i) => c.add(user, i % 2 ? product : other, 1));
      const finishes = Array.from({ length: 4 }, () => c.finish(user, finishBody(snapshot)));
      const results = await Promise.all([...adds, ...finishes]);
      assert.deepEqual(results.map((r) => r.status), Array(16).fill(200));
      const cart = (await c.get(user)).body.data;
      assert.equal(qty(cart, product), 6, 'ronda ' + round);
      assert.equal(qty(cart, other), 6);
      assert.equal(cart.version, 1 + 12 + 1);
      const effects = new Set(results.slice(12).map((r) => JSON.stringify(r.body)));
      assert.equal(effects.size, 1);
    }
  });

  test('concurrencia: iniciar simultáneo del mismo pedido y de pedidos distintos no produce 5xx', async () => {
    const { user, product } = await fresh();
    await c.add(user, product, 1);
    const order = randomUUID();
    const same = await Promise.all(Array.from({ length: 6 }, () => c.start(user, { pedido_id: order, version_original: 1 })));
    assert.deepEqual(same.map((r) => r.status), Array(6).fill(200));
    const other = await fresh();
    await c.add(other.user, other.product, 1);
    const shared = randomUUID();
    const split = await Promise.all([user, other.user].map((u) => c.start(u, { pedido_id: shared, version_original: 1 })));
    assert.ok(split.every((r) => r.status < 500), JSON.stringify(split.map((r) => r.status)));
    const rival = await Promise.all(Array.from({ length: 6 }, () => c.start(other.user, { pedido_id: randomUUID(), version_original: 1 })));
    assert.ok(rival.every((r) => r.status === 200 || r.status === 409));
  });
});

describe('migración 002 (PostgreSQL real)', { skip: !pool && 'sin TEST_DATABASE_URL' }, () => {
  const folder = new URL('../migrations/', import.meta.url);
  const files = readdirSync(folder).filter((name) => name.endsWith('.sql')).sort();
  const name = 'qa_mig_' + randomUUID().replaceAll('-', '').slice(0, 10);
  let skip;
  const open = () => new pg.Pool({ connectionString: connectionString.replace(/\/[^/]*$/, '/' + name) });
  test('rellena linea_id de filas existentes, es idempotente y soporta ejecución paralela', async (t) => {
    const { rows } = await pool.query('SELECT rolcreatedb OR rolsuper AS ok FROM pg_roles WHERE rolname = current_user');
    if (!rows[0].ok) return t.skip('el rol de prueba no puede crear bases de datos');
    await pool.query(`CREATE DATABASE ${name}`);
    const db = open();
    try {
      const first = readFileSync(new URL(files[0], folder), 'utf8');
      await db.query(first);
      const user = randomUUID();
      await db.query('INSERT INTO carritos (usuario_id, version) VALUES ($1, 7)', [user]);
      for (let i = 0; i < 3; i++) {
        await db.query('INSERT INTO carrito_items (usuario_id, producto_id, cantidad) VALUES ($1, $2, 1)', [user, randomUUID()]);
      }
      const all = files.map((file) => readFileSync(new URL(file, folder), 'utf8'));
      for (const sql of all) await db.query(sql);
      for (const sql of all) await db.query(sql);
      const runs = await Promise.allSettled(Array.from({ length: 8 }, async () => { for (const sql of all) await db.query(sql); }));
      assert.deepEqual(runs.filter((r) => r.status === 'rejected').map((r) => r.reason.message), []);
      const lines = await db.query('SELECT count(DISTINCT linea_id)::int AS n, count(*)::int AS total FROM carrito_items');
      assert.deepEqual(lines.rows[0], { n: 3, total: 3 });
      assert.equal((await db.query('SELECT version FROM carritos WHERE usuario_id = $1', [user])).rows[0].version, '7');
    } finally {
      await db.end();
      await pool.query(`DROP DATABASE IF EXISTS ${name}`);
    }
  });
});
