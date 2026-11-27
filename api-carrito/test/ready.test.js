// /ready con el pool real de src/db.js: BD arriba -> 200; BD caída -> 503. /health no depende de la BD.
// La prueba con PostgreSQL se omite sin TEST_DATABASE_URL (BD desechable; aplica las migraciones antes).
import './env-limites-altos.js';
import assert from 'node:assert/strict';
import { generateKeyPairSync } from 'node:crypto';
import { once } from 'node:events';
import { readdirSync, readFileSync } from 'node:fs';
import { after, before, describe, test } from 'node:test';
import { createApp } from '../src/app.js';
import { openPool } from '../src/db.js';
import { cartStore } from '../src/store.js';

const { publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const servers = [];

// Levanta la app con un almacén real sobre el pool dado y devuelve la URL base.
async function listen(pool) {
  const app = createApp({
    publicKey,
    serviceToken: 'token-solo-pruebas',
    available: async () => 1,
    store: cartStore(pool),
  });
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  servers.push(server);
  return 'http://127.0.0.1:' + server.address().port;
}

after(async () => {
  await Promise.all(servers.map((server) => new Promise((resolve) => server.close(resolve))));
});

describe('/ready con PostgreSQL real', { skip: !process.env.TEST_DATABASE_URL && 'sin TEST_DATABASE_URL' }, () => {
  let pool;
  let base;

  before(async () => {
    const url = new URL(process.env.TEST_DATABASE_URL);
    pool = openPool({
      DB_HOST: url.hostname,
      DB_PORT: url.port || '5432',
      DB_DATABASE: decodeURIComponent(url.pathname.slice(1)),
      DB_USERNAME: decodeURIComponent(url.username),
      DB_PASSWORD: decodeURIComponent(url.password),
    });
    pool.on('error', () => {});
    const folder = new URL('../migrations/', import.meta.url);
    for (const file of readdirSync(folder).filter((name) => name.endsWith('.sql')).sort()) {
      await pool.query(readFileSync(new URL(file, folder), 'utf8'));
    }
    base = await listen(pool);
  });
  after(async () => { await pool?.end().catch(() => {}); });

  test('BD arriba: /ready responde 200 y /health 200', async () => {
    const ready = await fetch(base + '/ready');
    assert.equal(ready.status, 200);
    assert.deepEqual(await ready.json(), { status: 'ok', service: 'api-carrito' });
    assert.equal((await fetch(base + '/health')).status, 200);
  });
});

describe('/ready sin PostgreSQL alcanzable', () => {
  test('BD caída: /ready responde 503 con JSON y /health sigue en 200 sin tocar la BD', async () => {
    const pool = openPool({ DB_HOST: '127.0.0.1', DB_PORT: '1', DB_DATABASE: 'x', DB_USERNAME: 'x', DB_PASSWORD: 'x' });
    pool.on('error', () => {});
    try {
      const base = await listen(pool);
      const ready = await fetch(base + '/ready');
      assert.equal(ready.status, 503);
      assert.deepEqual(await ready.json(), { status: 'unavailable', service: 'api-carrito' });
      const health = await fetch(base + '/health');
      assert.equal(health.status, 200);
      assert.deepEqual(await health.json(), { status: 'ok', service: 'api-carrito' });
    } finally {
      await pool.end().catch(() => {});
    }
  });
});
