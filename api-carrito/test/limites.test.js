// Rate limiting y tamaño de cuerpo (decisión del equipo). Los límites se inyectan con loadLimits(env).
import assert from 'node:assert/strict';
import { generateKeyPairSync, randomUUID } from 'node:crypto';
import { once } from 'node:events';
import http from 'node:http';
import { after, describe, test } from 'node:test';
import { SignJWT } from 'jose';
import { createApp } from '../src/app.js';
import { loadLimits } from '../src/limits.js';

const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const SERVICE = 'token-solo-pruebas';
const servers = [];
let clock = 1_000_000;

const sign = (sub, role = 'cliente') => new SignJWT({ role }).setProtectedHeader({ alg: 'RS256' }).setSubject(sub)
  .setIssuer('api-usuarios').setAudience('tienda-microservicios').setIssuedAt().setExpirationTime('1h').sign(privateKey);

async function listen(env = {}) {
  const cart = (id) => ({ usuario_id: id, items: [], version: 0 });
  const app = createApp({
    publicKey, serviceToken: SERVICE, limits: loadLimits(env), now: () => clock,
    store: {
      list: async () => cart('x'), add: async () => cart('x'), start: async () => cart('x'),
      clear: async () => cart('x'), release: async () => cart('x'), finish: async () => cart('x'),
      ready: async () => {},
    },
  });
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  servers.push(server);
  return 'http://127.0.0.1:' + server.address().port;
}
after(() => Promise.all(servers.map((s) => new Promise((r) => s.close(r)))));

const get = (base, user, token) => fetch(`${base}/api/carrito/${user}`, { headers: { Authorization: 'Bearer ' + token } });
const add = (base, user, token, body = { producto_id: randomUUID(), cantidad: 1 }) => fetch(`${base}/api/carrito/${user}/agregar`, {
  method: 'POST', body: typeof body === 'string' ? body : JSON.stringify(body),
  headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json', 'Idempotency-Key': randomUUID() },
});
const internal = (base, user, action = 'liberar') => fetch(`${base}/api/carrito/${user}/${action}`, {
  method: 'POST', body: JSON.stringify({ pedido_id: randomUUID() }),
  headers: { 'X-Service-Token': SERVICE, 'Content-Type': 'application/json', 'Idempotency-Key': randomUUID() },
});

async function assertTooMany(res) {
  assert.equal(res.status, 429);
  assert.match(res.headers.get('retry-after'), /^[1-9]\d*$/);
  const body = await res.json();
  assert.equal(body.success, false);
  assert.equal(typeof body.message, 'string');
  assert.deepEqual(body.errors, {});
}

describe('configuración', () => {
  test('valores por defecto del equipo', () => {
    assert.deepEqual(loadLimits({}), { consulta: 120, mutacion: 30, interna: 300, maxJsonBytes: 262144 });
  });
  test('se leen del entorno y se rechazan valores inválidos', () => {
    const l = loadLimits({ RATE_LIMIT_CONSULTA_POR_MIN: '7', RATE_LIMIT_MUTACION_POR_MIN: '8', RATE_LIMIT_INTERNA_POR_MIN: '9', MAX_JSON_BYTES: '1024' });
    assert.deepEqual(l, { consulta: 7, mutacion: 8, interna: 9, maxJsonBytes: 1024 });
    for (const bad of ['0', '-1', 'abc', '1.5', '']) {
      assert.throws(() => loadLimits({ RATE_LIMIT_CONSULTA_POR_MIN: bad }), /RATE_LIMIT_CONSULTA_POR_MIN/);
    }
    assert.throws(() => loadLimits({ MAX_JSON_BYTES: '0' }), /MAX_JSON_BYTES/);
  });
});

describe('rate limiting', () => {
  test('consultas con JWT: 429 al exceder, por identidad y con ventana que se renueva', async () => {
    const base = await listen({ RATE_LIMIT_CONSULTA_POR_MIN: '3' });
    const a = randomUUID();
    const b = randomUUID();
    const ta = await sign(a);
    for (let i = 0; i < 3; i++) assert.equal((await get(base, a, ta)).status, 200);
    await assertTooMany(await get(base, a, ta));
    assert.equal((await get(base, b, await sign(b))).status, 200, 'otra identidad no se ve afectada');
    clock += 61_000;
    assert.equal((await get(base, a, ta)).status, 200, 'nueva ventana');
  });

  test('Retry-After refleja el tiempo restante de la ventana', async () => {
    const base = await listen({ RATE_LIMIT_CONSULTA_POR_MIN: '1' });
    const u = randomUUID();
    const t = await sign(u);
    await get(base, u, t);
    clock += 20_000;
    const res = await get(base, u, t);
    assert.equal(res.status, 429);
    assert.equal(Number(res.headers.get('retry-after')), 40);
  });

  test('mutaciones con JWT usan su propio cupo, independiente de las consultas', async () => {
    const base = await listen({ RATE_LIMIT_MUTACION_POR_MIN: '2', RATE_LIMIT_CONSULTA_POR_MIN: '50' });
    const u = randomUUID();
    const t = await sign(u);
    assert.equal((await add(base, u, t)).status, 200);
    assert.equal((await add(base, u, t)).status, 200);
    await assertTooMany(await add(base, u, t));
    assert.equal((await get(base, u, t)).status, 200);
  });

  test('un admin se limita por su propio sub, no por el usuario consultado', async () => {
    const base = await listen({ RATE_LIMIT_CONSULTA_POR_MIN: '1' });
    const admin = randomUUID();
    const ta = await sign(admin, 'admin');
    assert.equal((await get(base, randomUUID(), ta)).status, 200);
    assert.equal((await get(base, randomUUID(), ta)).status, 429);
  });

  test('interna: lecturas y operaciones de Pedidos comparten cupo por identidad de servicio', async () => {
    const base = await listen({ RATE_LIMIT_INTERNA_POR_MIN: '3' });
    const u = randomUUID();
    assert.equal((await internal(base, u, 'liberar')).status, 200);
    assert.equal((await fetch(`${base}/api/carrito/${u}`, { headers: { 'X-Service-Token': SERVICE } })).status, 200);
    assert.equal((await internal(base, u, 'liberar')).status, 200);
    await assertTooMany(await internal(base, u, 'liberar'));
    await assertTooMany(await fetch(`${base}/api/carrito/${u}`, { headers: { 'X-Service-Token': SERVICE } }));
  });

  test('autentica primero: sin credencial o con credencial mala sigue 401 dentro del límite', async () => {
    const base = await listen({ RATE_LIMIT_CONSULTA_POR_MIN: '3', RATE_LIMIT_INTERNA_POR_MIN: '1' });
    const u = randomUUID();
    const t = await sign(u);
    for (let i = 0; i < 3; i++) await get(base, u, t);
    assert.equal((await get(base, u, t)).status, 429); // cupo del titular agotado
    assert.equal((await fetch(`${base}/api/carrito/${u}`)).status, 401);
    assert.equal((await fetch(`${base}/api/carrito/${u}`, { headers: { 'X-Service-Token': 'mal' } })).status, 401);
  });

  test('sin autenticar se limita por IP: los fallos repetidos acaban en 429', async () => {
    const base = await listen({ RATE_LIMIT_CONSULTA_POR_MIN: '3' });
    const u = randomUUID();
    for (let i = 0; i < 3; i++) assert.equal((await fetch(`${base}/api/carrito/${u}`)).status, 401);
    await assertTooMany(await fetch(`${base}/api/carrito/${u}`));
  });

  test('/health y /ready están exentos', async () => {
    const base = await listen({ RATE_LIMIT_CONSULTA_POR_MIN: '1', RATE_LIMIT_MUTACION_POR_MIN: '1', RATE_LIMIT_INTERNA_POR_MIN: '1' });
    for (let i = 0; i < 10; i++) {
      assert.equal((await fetch(base + '/health')).status, 200);
      assert.equal((await fetch(base + '/ready')).status, 200);
    }
  });
});

describe('tamaño del cuerpo', () => {
  function rawPost(base, { headers, chunks }) {
    return new Promise((resolve, reject) => {
      const url = new URL(base);
      const req = http.request({ host: url.hostname, port: url.port, method: 'POST', path: `/api/carrito/${randomUUID()}/agregar`, headers }, (res) => {
        let text = '';
        res.on('data', (c) => { text += c; });
        res.on('end', () => resolve({ status: res.statusCode, text }));
      });
      req.on('error', (e) => (e.code === 'EPIPE' || e.code === 'ECONNRESET' ? resolve({ status: 'cortado' }) : reject(e)));
      for (const chunk of chunks) req.write(chunk);
      req.end();
    });
  }

  test('Content-Length mayor al máximo => 413 con el formato de error', async () => {
    const base = await listen({ MAX_JSON_BYTES: '1024' });
    const u = randomUUID();
    const res = await add(base, u, await sign(u), JSON.stringify({ producto_id: randomUUID(), cantidad: 1, relleno: 'x'.repeat(2000) }));
    assert.equal(res.status, 413);
    const body = await res.json();
    assert.equal(body.success, false);
    assert.deepEqual(body.errors, {});
  });

  test('cuerpo real mayor al máximo en streaming (sin Content-Length) => 413', async () => {
    const base = await listen({ MAX_JSON_BYTES: '1024' });
    const u = randomUUID();
    const res = await rawPost(base, {
      headers: { 'Content-Type': 'application/json', 'Transfer-Encoding': 'chunked', Authorization: 'Bearer ' + await sign(u), 'Idempotency-Key': randomUUID() },
      chunks: ['{"relleno":"', 'x'.repeat(600), 'x'.repeat(600), '"}'],
    });
    assert.equal(res.status, 413, res.text);
    assert.equal(JSON.parse(res.text).success, false);
  });

  test('un cuerpo dentro del máximo no se rechaza por tamaño', async () => {
    const base = await listen({ MAX_JSON_BYTES: '4096' });
    const u = randomUUID();
    const res = await add(base, u, await sign(u), JSON.stringify({ producto_id: randomUUID(), cantidad: 1, relleno: 'x'.repeat(2000) }));
    assert.equal(res.status, 422); // campo extra: validación, no tamaño
  });

  test('el máximo por defecto es 256 KiB', async () => {
    const base = await listen({});
    const u = randomUUID();
    const t = await sign(u);
    const near = JSON.stringify({ producto_id: randomUUID(), cantidad: 1, relleno: 'x'.repeat(200_000) });
    assert.equal((await add(base, u, t, near)).status, 422);
    const over = JSON.stringify({ producto_id: randomUUID(), cantidad: 1, relleno: 'x'.repeat(270_000) });
    assert.equal((await add(base, u, t, over)).status, 413);
  });
});
