// Suite QA hostil: ataca el servicio por HTTP real. Las pruebas con base de datos
// se omiten sin TEST_DATABASE_URL (PostgreSQL 17 desechable con la migración aplicada).
import assert from 'node:assert/strict';
import { generateKeyPairSync, randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import http from 'node:http';
import { after, before, describe, test } from 'node:test';
import { SignJWT, base64url } from 'jose';
import pg from 'pg';
import { createApp } from '../src/app.js';
import { cartStore } from '../src/store.js';

const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const other = generateKeyPairSync('rsa', { modulusLength: 2048 });
const SERVICE = 'token-pedidos-qa';
const connectionString = process.env.TEST_DATABASE_URL;
const pool = connectionString ? new pg.Pool({ connectionString }) : null;
const servers = [];
// Las pruebas de migración crean BD temporales: se omiten si el rol no tiene CREATEDB ni es superusuario.
let skipScratch = !pool && 'sin TEST_DATABASE_URL';
if (pool) {
  try {
    const { rows } = await pool.query('SELECT rolcreatedb OR rolsuper AS ok FROM pg_roles WHERE rolname = current_user');
    if (!rows[0]?.ok) skipScratch = 'el rol de prueba no puede crear bases de datos (requiere CREATEDB)';
  } catch (error) {
    skipScratch = `no se pudo comprobar CREATEDB: ${error.message}`;
  }
}

async function listen(options) {
  const server = createApp({ publicKey, serviceToken: SERVICE, ...options }).listen(0, '127.0.0.1');
  await once(server, 'listening');
  servers.push(server);
  return 'http://127.0.0.1:' + server.address().port;
}

function jwt({ sub = randomUUID(), role = 'cliente', key = privateKey, alg = 'RS256', iss = 'api-usuarios',
  aud = 'tienda-microservicios', iat, exp = '1h', claims = {} } = {}) {
  let signer = new SignJWT({ role, ...claims }).setProtectedHeader({ alg }).setIssuer(iss).setAudience(aud);
  if (sub !== null) signer = signer.setSubject(sub);
  signer = iat === undefined ? signer.setIssuedAt() : signer.setIssuedAt(iat);
  if (exp !== null) signer = signer.setExpirationTime(exp);
  return signer.sign(key);
}

const add = (base, user, token, body, key = randomUUID(), extra = {}) =>
  fetch(`${base}/api/carrito/${user}/agregar`, {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json', 'Idempotency-Key': key, ...extra },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });

// Petición cruda para enviar rutas o cabeceras que fetch normalizaría.
function raw(base, { method = 'GET', path, headers = {}, body }) {
  return new Promise((resolve, reject) => {
    const url = new URL(base);
    const req = http.request({ host: url.hostname, port: url.port, method, path, headers }, (res) => {
      let text = '';
      res.on('data', (c) => { text += c; });
      res.on('end', () => resolve({ status: res.statusCode, text }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

after(async () => {
  await Promise.all(servers.map((s) => new Promise((r) => s.close(r))));
  await pool?.end();
});

describe('validación de entrada (sin BD)', () => {
  const user = randomUUID();
  const product = randomUUID();
  let base;
  let calls = 0;
  before(async () => {
    base = await listen({
      store: {
        list: async (id) => ({ usuario_id: id, items: [] }),
        ready: async () => {},
        add: async () => { calls += 1; return { usuario_id: user, items: [] }; },
      },
    });
  });

  test('cuerpos malformados o de tipo erroneo nunca producen 5xx ni cambian el carrito', async () => {
    const token = await jwt({ sub: user });
    const bodies = ['{', '{"producto_id":', '[]', 'null', '"texto"', '42', '{"a":1}{"b":2}', '',
      '{"producto_id":"' + product + '","cantidad":1,"cantidad":2,"x":1}'];
    for (const body of bodies) {
      const res = await add(base, user, token, body);
      assert.ok([400, 422].includes(res.status), `cuerpo ${body} => ${res.status}`);
    }
    const invalid = [
      { producto_id: product, cantidad: '2' }, { producto_id: product, cantidad: 1.5 },
      { producto_id: product, cantidad: true }, { producto_id: product, cantidad: null },
      { producto_id: product, cantidad: -1 }, { producto_id: product, cantidad: 0 },
      { producto_id: product, cantidad: 2147483648 }, { producto_id: product, cantidad: 1e400 },
      { producto_id: product }, { cantidad: 1 }, { producto_id: product, cantidad: 1, precio: '10.00' },
      { producto_id: product, cantidad: 1, usuario_id: randomUUID() }, { producto_id: product, cantidad: [1] },
      { producto_id: [product], cantidad: 1 }, { producto_id: 7, cantidad: 1 },
      { producto_id: product, cantidad: 1, ['__proto__']: { admin: true } },
      JSON.parse('{"producto_id":"' + product + '","cantidad":1,"__proto__":{"x":1}}'),
    ];
    for (const body of invalid) {
      const text = JSON.stringify(body);
      const res = await add(base, user, token, text.includes('1e400') ? text : text);
      assert.equal(res.status, 422, text);
    }
    assert.equal((await add(base, user, token, '{"producto_id":"' + product + '","cantidad":1e400}')).status, 422);
    assert.equal(calls, 0);
  });

  test('UUID que no son v4 se rechazan en ruta, cuerpo y cabecera', async () => {
    const token = await jwt({ sub: user });
    const notV4 = ['6ba7b810-9dad-11d1-80b4-00c04fd430c8', '00000000-0000-0000-0000-000000000000',
      '123e4567-e89b-52d3-a456-426614174000', '{' + product + '}', product + 'x', 'not-a-uuid', product.replace(/-/g, '')];
    for (const bad of notV4) {
      assert.equal((await add(base, user, token, { producto_id: bad, cantidad: 1 })).status, 422, bad);
      assert.equal((await add(base, user, token, { producto_id: product, cantidad: 1 }, bad)).status, 422, bad);
      const res = await fetch(`${base}/api/carrito/${encodeURIComponent(bad)}`, { headers: { 'X-Service-Token': SERVICE } });
      assert.equal(res.status, 422, bad);
    }
    assert.equal(calls, 0);
  });

  test('cuerpos enormes y codificaciones raras se rechazan con 4xx controlado', async () => {
    const token = await jwt({ sub: user });
    const huge = JSON.stringify({ producto_id: product, cantidad: 1, relleno: 'x'.repeat(20_000) });
    assert.equal((await add(base, user, token, huge)).status, 400);
    const enormous = JSON.stringify({ producto_id: product, cantidad: 1, relleno: 'x'.repeat(5_000_000) });
    const res = await add(base, user, token, enormous);
    assert.ok(res.status >= 400 && res.status < 500, 'estado ' + res.status);
    const headers = { Authorization: 'Bearer ' + token, 'Idempotency-Key': randomUUID() };
    const path = `/api/carrito/${user}/agregar`;
    const body = JSON.stringify({ producto_id: product, cantidad: 1 });
    for (const type of ['text/plain', 'application/json; charset=utf-32', 'application/json; charset=nope', 'application/x-www-form-urlencoded']) {
      const r = await raw(base, { method: 'POST', path, headers: { ...headers, 'Content-Type': type }, body });
      assert.ok(r.status >= 400 && r.status < 500, `${type} => ${r.status} ${r.text}`);
      assert.doesNotMatch(r.text, /at .*\.js|node_modules/);
    }
    const gz = await raw(base, { method: 'POST', path, headers: { ...headers, 'Content-Type': 'application/json', 'Content-Encoding': 'br' }, body });
    assert.ok(gz.status >= 400 && gz.status < 500, 'Content-Encoding desconocido => ' + gz.status);
  });

  test('rutas con codificación porcentual inválida devuelven 4xx, no 500', async () => {
    for (const path of ['/api/carrito/%E0%A4%A', '/api/carrito/%', '/api/carrito/%00', '/%zz']) {
      const r = await raw(base, { path, headers: { 'X-Service-Token': SERVICE } });
      assert.ok(r.status >= 400 && r.status < 500, `${path} => ${r.status} ${r.text}`);
      assert.equal(JSON.parse(r.text).success, false);
    }
  });

  test('inyección SQL en ruta, cuerpo y cabeceras se rechaza antes de llegar a la BD', async () => {
    const token = await jwt({ sub: user });
    const sqli = ["' OR '1'='1", "1; DROP TABLE carritos;--", user + "' --", "\\x00"];
    for (const payload of sqli) {
      assert.equal((await add(base, user, token, { producto_id: payload, cantidad: 1 })).status, 422);
      assert.equal((await add(base, user, token, { producto_id: product, cantidad: payload })).status, 422);
      assert.equal((await add(base, user, token, { producto_id: product, cantidad: 1 }, payload)).status, 422);
      const res = await fetch(`${base}/api/carrito/${encodeURIComponent(payload)}`, { headers: { 'X-Service-Token': SERVICE } });
      assert.equal(res.status, 422);
    }
  });
});

describe('JWT y credenciales internas (sin BD)', () => {
  const user = randomUUID();
  let base;
  before(async () => {
    base = await listen({ store: {
      list: async (id) => ({ usuario_id: id, items: [], version: 0 }), ready: async () => {},
      clear: async ({ userId }) => ({ usuario_id: userId, items: [], version: 0 }),
    } });
  });
  const get = (headers) => fetch(`${base}/api/carrito/${user}`, { headers });
  const bearer = (t) => get({ Authorization: 'Bearer ' + t });

  test('tokens manipulados, expirados o mal firmados dan 401', async () => {
    const good = await jwt({ sub: user });
    assert.equal((await bearer(good)).status, 200);
    const [h, p, s] = good.split('.');
    const forgedPayload = base64url.encode(JSON.stringify({ ...JSON.parse(Buffer.from(p, 'base64url')), role: 'admin', sub: randomUUID() }));
    const none = (payload) => base64url.encode('{"alg":"none","typ":"JWT"}') + '.' + payload + '.';
    const hs256 = async () => {
      const { createHmac } = await import('node:crypto');
      const head = base64url.encode('{"alg":"HS256","typ":"JWT"}');
      const pem = publicKey.export({ type: 'spki', format: 'pem' });
      return head + '.' + p + '.' + createHmac('sha256', pem).update(head + '.' + p).digest('base64url');
    };
    const cases = {
      'payload alterado': `${h}.${forgedPayload}.${s}`,
      'alg=none': none(p), 'alg=none sin punto final': none(p).slice(0, -1),
      'HS256 con clave pública como secreto': await hs256(),
      'firma de otra clave': await jwt({ sub: user, key: other.privateKey }),
      'RS384': await jwt({ sub: user, alg: 'RS384' }),
      'PS256': await jwt({ sub: user, alg: 'PS256' }),
      'expirado': await jwt({ sub: user, iat: Math.floor(Date.now() / 1000) - 7200, exp: Math.floor(Date.now() / 1000) - 3600 }),
      'iat futuro': await jwt({ sub: user, iat: Math.floor(Date.now() / 1000) + 3600, exp: Math.floor(Date.now() / 1000) + 7200 }),
      'vigencia de 2 horas': await jwt({ sub: user, exp: '2h' }),
      'sin exp': await jwt({ sub: user, exp: null }),
      'emisor ajeno': await jwt({ sub: user, iss: 'otro' }), 'audiencia ajena': await jwt({ sub: user, aud: 'otra' }),
      'sin sub': await jwt({ sub: null }), 'sub no v4': await jwt({ sub: '6ba7b810-9dad-11d1-80b4-00c04fd430c8' }),
      'rol desconocido': await jwt({ sub: user, role: 'superadmin' }), 'rol no cadena': await jwt({ sub: user, role: ['admin'] }),
      'truncado': good.slice(0, -10), 'sin firma': `${h}.${p}.`, 'dos puntos': `${h}.${p}`, 'vacío': '',
      'basura': 'a.b.c',
    };
    for (const [name, token] of Object.entries(cases)) {
      const res = token === '' ? await get({ Authorization: 'Bearer ' }) : await bearer(token);
      assert.equal(res.status, 401, name);
    }
    assert.equal((await get({ Authorization: 'Basic ' + good })).status, 401);
    assert.equal((await get({ Authorization: good })).status, 401);
    assert.equal((await get({ Authorization: 'Bearer ' + good + ' extra' })).status, 401);
  });

  test('titularidad: otro usuario recibe 403, admin sí accede', async () => {
    assert.equal((await bearer(await jwt({ sub: randomUUID() }))).status, 403);
    assert.equal((await bearer(await jwt({ sub: randomUUID(), role: 'admin' }))).status, 200);
    assert.equal((await bearer(await jwt({ sub: user.toUpperCase() }))).status, 200);
  });

  test('X-Service-Token ausente, vacío, parcial o de otro par se rechaza', async () => {
    const attempts = ['', ' ', SERVICE.slice(0, -1), SERVICE + 'x', SERVICE.toUpperCase(), 'token-pedidos-otro-par', 'a'.repeat(100_000 % 8000)];
    for (const value of attempts) assert.equal((await get({ 'X-Service-Token': value })).status, 401, JSON.stringify(value));
    assert.equal((await get({ Authorization: 'Bearer ' + SERVICE })).status, 401);
    assert.equal((await get({ 'X-Service-Token': SERVICE })).status, 200);
    const del = (headers) => fetch(`${base}/api/carrito/${user}/vaciar`, { method: 'DELETE', headers: { 'Idempotency-Key': randomUUID(), ...headers } });
    assert.equal((await del({})).status, 401);
    assert.equal((await del({ Authorization: 'Bearer ' + await jwt({ sub: user, role: 'admin' }) })).status, 401);
    assert.equal((await del({ 'X-Service-Token': 'otro' })).status, 401);
    assert.equal((await del({ 'X-Service-Token': SERVICE })).status, 200);
  });

  test('sin token interno configurado nunca se acepta una credencial vacía', async () => {
    const open = await listen({ serviceToken: '', store: { list: async (id) => ({ usuario_id: id, items: [] }) } });
    for (const value of ['', 'x']) {
      assert.equal((await fetch(`${open}/api/carrito/${user}`, { headers: { 'X-Service-Token': value } })).status, 401);
    }
  });

  test('un fallo de autenticación no depende de que la ruta sea válida (401 antes que 422)', async () => {
    const res = await fetch(`${base}/api/carrito/no-uuid/agregar`, { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' } });
    assert.equal(res.status, 401);
  });
});

describe('BD no disponible', () => {
  test('/health vive y /ready, consulta y agregar devuelven 503 con la BD caída o colgada', async () => {
    const user = randomUUID();
    const product = randomUUID();
    for (const options of [{ host: '127.0.0.1', port: 1 }, { host: '10.255.255.1', port: 5432 }]) {
      const dead = new pg.Pool({ ...options, user: 'x', database: 'x', connectionTimeoutMillis: 300 });
      dead.on('error', () => {});
      const base = await listen({ store: cartStore(dead), available: async () => 5 });
      assert.equal((await fetch(base + '/health')).status, 200);
      assert.equal((await fetch(base + '/ready')).status, 503);
      const list = await fetch(`${base}/api/carrito/${user}`, { headers: { 'X-Service-Token': SERVICE } });
      assert.equal(list.status, 503, JSON.stringify(options));
      const res = await add(base, user, await jwt({ sub: user }), { producto_id: product, cantidad: 1 });
      assert.equal(res.status, 503, JSON.stringify(options));
      await dead.end().catch(() => {});
    }
  });
});

describe('concurrencia e idempotencia (PostgreSQL real)', { skip: !pool }, () => {
  let base;
  let limit = 1000;
  before(async () => { base = await listen({ store: cartStore(pool), available: async () => limit }); });
  const qty = async (user) => (await pool.query('SELECT COALESCE(sum(cantidad),0)::int AS n FROM carrito_items WHERE usuario_id=$1', [user])).rows[0].n;

  test('misma clave y mismo cuerpo en paralelo: un solo efecto y respuestas idénticas', async () => {
    const user = randomUUID(); const product = randomUUID(); const key = randomUUID();
    const token = await jwt({ sub: user });
    const results = await Promise.all(Array.from({ length: 30 }, () => add(base, user, token, { producto_id: product, cantidad: 3 }, key)));
    assert.ok(results.every((r) => r.status === 200));
    const bodies = await Promise.all(results.map(async (r) => JSON.stringify((await r.json()).data)));
    assert.equal(new Set(bodies).size, 1, 'el resultado repetido debe ser idéntico (incluido el orden de claves)');
    assert.equal(await qty(user), 3);
    assert.equal((await pool.query('SELECT count(*)::int n FROM carrito_adiciones WHERE clave=$1', [key])).rows[0].n, 1);
  });

  test('misma clave con cuerpos distintos en paralelo: exactamente un 200 y el resto 409', async () => {
    const user = randomUUID(); const product = randomUUID(); const key = randomUUID();
    const token = await jwt({ sub: user });
    const results = await Promise.all(Array.from({ length: 20 }, (_, i) => add(base, user, token, { producto_id: product, cantidad: i + 1 }, key)));
    const statuses = results.map((r) => r.status).sort();
    assert.equal(statuses.filter((s) => s === 200).length, 1);
    assert.equal(statuses.filter((s) => s === 409).length, 19);
    const applied = await qty(user);
    assert.ok(applied >= 1 && applied <= 20);
  });

  test('claves distintas en paralelo suman sin perder actualizaciones', async () => {
    const user = randomUUID(); const product = randomUUID();
    const token = await jwt({ sub: user });
    const results = await Promise.all(Array.from({ length: 40 }, () => add(base, user, token, { producto_id: product, cantidad: 1 })));
    assert.ok(results.every((r) => r.status === 200));
    assert.equal(await qty(user), 40);
  });

  test('la disponibilidad se respeta bajo carrera: no se excede el tope', async () => {
    const user = randomUUID(); const product = randomUUID();
    const token = await jwt({ sub: user });
    limit = 5;
    try {
      const results = await Promise.all(Array.from({ length: 20 }, () => add(base, user, token, { producto_id: product, cantidad: 1 })));
      assert.equal(results.filter((r) => r.status === 200).length, 5);
      assert.equal(results.filter((r) => r.status === 409).length, 15);
      assert.equal(await qty(user), 5);
    } finally { limit = 1000; }
  });

  test('misma clave desde dos carritos del mismo admin: no se duplica ni se mezcla', async () => {
    const admin = randomUUID(); const a = randomUUID(); const b = randomUUID(); const product = randomUUID(); const key = randomUUID();
    const token = await jwt({ sub: admin, role: 'admin' });
    const results = await Promise.all([a, b].flatMap((u) => Array.from({ length: 5 }, () => add(base, u, token, { producto_id: product, cantidad: 1 }, key))));
    const ok = results.filter((r) => r.status === 200).length;
    assert.equal(ok, 5);
    assert.equal(results.filter((r) => r.status === 409).length, 5);
    assert.equal((await qty(a)) + (await qty(b)), 1);
  });

  test('usuario A no puede agregar ni leer en el carrito de B y la BD queda intacta', async () => {
    const a = randomUUID(); const b = randomUUID(); const product = randomUUID();
    const res = await add(base, b, await jwt({ sub: a }), { producto_id: product, cantidad: 1 });
    assert.equal(res.status, 403);
    assert.equal(await qty(b), 0);
    assert.equal((await pool.query('SELECT count(*)::int n FROM carritos WHERE usuario_id=$1', [b])).rows[0].n, 0);
    assert.equal((await fetch(`${base}/api/carrito/${b}`, { headers: { Authorization: 'Bearer ' + await jwt({ sub: a }) } })).status, 403);
  });

  test('inyección SQL no altera el esquema ni los datos', async () => {
    const before = (await pool.query("SELECT count(*)::int n FROM information_schema.tables WHERE table_name LIKE 'carrit%'")).rows[0].n;
    const user = randomUUID();
    await add(base, user, await jwt({ sub: user }), { producto_id: "'; DROP TABLE carrito_items;--", cantidad: 1 });
    await fetch(`${base}/api/carrito/${encodeURIComponent("' OR 1=1;--")}`, { headers: { 'X-Service-Token': SERVICE } });
    const after = (await pool.query("SELECT count(*)::int n FROM information_schema.tables WHERE table_name LIKE 'carrit%'")).rows[0].n;
    assert.equal(after, before);
  });
});

describe('migraciones y /ready sin esquema (PostgreSQL real)', { skip: skipScratch }, () => {
  const sql = readFileSync(new URL('../migrations/001-carrito.sql', import.meta.url), 'utf8');
  const names = ['ready', 'serie', 'virgen'].map((n) => `qa_${n}_${randomUUID().replaceAll('-', '').slice(0, 10)}`);
  const scratch = (name) => new pg.Pool({ connectionString: connectionString.replace(/\/[^/]*$/, '/' + name) });
  before(async () => { for (const name of names) await pool.query(`CREATE DATABASE ${name}`); });
  after(async () => { for (const name of names) await pool.query(`DROP DATABASE IF EXISTS ${name}`); });

  test('/ready devuelve 503 mientras falta la migración y 200 después; /health siempre vive', async () => {
    const db = scratch(names[0]);
    const base = await listen({ store: cartStore(db), available: async () => 1 });
    try {
      assert.equal((await fetch(base + '/health')).status, 200);
      assert.equal((await fetch(base + '/ready')).status, 503);
      await db.query(sql);
      assert.equal((await fetch(base + '/ready')).status, 200);
    } finally { await db.end(); }
  });

  test('aplicar la migración dos veces, en serie y en paralelo, no falla ni duplica', async () => {
    const db = scratch(names[1]);
    try {
      await db.query(sql);
      await db.query(sql);
      const runs = await Promise.allSettled(Array.from({ length: 8 }, () => db.query(sql)));
      assert.deepEqual(runs.filter((r) => r.status === 'rejected').map((r) => r.reason.message), []);
      const tables = await db.query("SELECT count(*)::int n FROM information_schema.tables WHERE table_name LIKE 'carrit%'");
      assert.equal(tables.rows[0].n, 4);
    } finally { await db.end(); }
  });

  test('migración en paralelo sobre una BD virgen tampoco falla', async () => {
    const db = scratch(names[2]);
    try {
      const runs = await Promise.allSettled(Array.from({ length: 8 }, () => db.query(sql)));
      assert.deepEqual(runs.filter((r) => r.status === 'rejected').map((r) => r.reason.message), []);
    } finally { await db.end(); }
  });
});
