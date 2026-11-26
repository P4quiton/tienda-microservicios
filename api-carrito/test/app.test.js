import assert from 'node:assert/strict';
import { generateKeyPairSync, randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { after, before, test } from 'node:test';
import { SignJWT } from 'jose';
import { createApp } from '../src/app.js';
import { catalogAvailability } from '../src/catalog.js';

const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const userId = randomUUID();
const productId = randomUUID();
const key = randomUUID();
const cart = { usuario_id: userId, items: [{ producto_id: productId, cantidad: 2, linea_id: randomUUID() }], version: 1 };
const calls = [];
let ready = true;
let items = cart.items;
let server;
let base;

async function token(subject = userId, role = 'cliente') {
  return new SignJWT({ role })
    .setProtectedHeader({ alg: 'RS256' })
    .setSubject(subject)
    .setIssuer('api-usuarios')
    .setAudience('tienda-microservicios')
    .setIssuedAt()
    .setExpirationTime('1h')
    .sign(privateKey);
}

before(async () => {
  const app = createApp({
    publicKey,
    serviceToken: 'token-solo-pruebas',
    store: {
      list: async (id) => ({ usuario_id: id, items, version: cart.version }),
      ready: async () => {
        if (!ready) throw new Error('No disponible');
      },
      add: async (input) => {
        calls.push(input);
        return cart;
      },
      clear: async ({ userId: id }) => {
        items = [];
        return { usuario_id: id, items, version: 2 };
      },
    },
  });
  server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  base = 'http://127.0.0.1:' + server.address().port;
});
after(async () => {
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
});

test('health y ready distinguen proceso activo de base disponible', async () => {
  const healthy = await fetch(base + '/health');
  assert.equal(healthy.status, 200);
  assert.deepEqual(await healthy.json(), { status: 'ok', service: 'api-carrito' });
  assert.equal((await fetch(base + '/ready')).status, 200);
  ready = false;
  const unavailable = await fetch(base + '/ready');
  assert.equal(unavailable.status, 503);
  assert.deepEqual(await unavailable.json(), { status: 'unavailable', service: 'api-carrito' });
});

test('consulta admite titular, admin y Pedidos, rechaza credenciales ajenas o inválidas', async () => {
  const url = base + '/api/carrito/' + userId;
  const owner = await fetch(url, { headers: { Authorization: 'Bearer ' + await token() } });
  assert.equal(owner.status, 200);
  assert.deepEqual((await owner.json()).data, cart);
  const admin = await fetch(url, { headers: { Authorization: 'Bearer ' + await token(randomUUID(), 'admin') } });
  assert.equal(admin.status, 200);
  const other = await fetch(url, { headers: { Authorization: 'Bearer ' + await token(randomUUID()) } });
  assert.equal(other.status, 403);
  assert.equal((await fetch(url)).status, 401);
  assert.equal((await fetch(url, { headers: { Authorization: 'Bearer inválido' } })).status, 401);
  assert.equal((await fetch(url, { headers: { 'X-Service-Token': 'incorrecto' } })).status, 401);
  assert.equal((await fetch(url, { headers: { 'X-Service-Token': 'token-solo-pruebas' } })).status, 200);
});

test('agregar valida cuerpo, identidad y clave antes de cambiar el carrito', async () => {
  const url = base + '/api/carrito/' + userId + '/agregar';
  const headers = {
    Authorization: 'Bearer ' + await token(),
    'Content-Type': 'application/json',
    'Idempotency-Key': key,
  };
  const send = (body, requestHeaders = headers) =>
    fetch(url, { method: 'POST', headers: requestHeaders, body });
  assert.equal((await send('{invalid')).status, 400);
  assert.equal((await send(JSON.stringify({ producto_id: productId, cantidad: 0 }))).status, 422);
  assert.equal((await send(JSON.stringify({ producto_id: productId, cantidad: 2, precio: 0 }))).status, 422);
  const body = JSON.stringify({ producto_id: productId, cantidad: 2 });
  assert.equal((await send(body, { ...headers, 'Idempotency-Key': 'incorrecta' })).status, 422);
  assert.equal((await send(body, { ...headers, Authorization: 'Bearer ' + await token(randomUUID()) })).status, 403);
  assert.equal((await send(body)).status, 200);
  assert.equal(calls.length, 1);
  assert.deepEqual(
    { ...calls[0] },
    { actorId: userId, userId, key, productId, quantity: 2, available: undefined },
  );
});

test('vaciar exige identidad interna e Idempotency-Key y devuelve el carrito vacío con su versión', async () => {
  const url = base + '/api/carrito/' + userId + '/vaciar';
  assert.equal((await fetch(url, {
    method: 'DELETE', headers: { Authorization: 'Bearer ' + await token() },
  })).status, 401);
  const options = { method: 'DELETE', headers: { 'X-Service-Token': 'token-solo-pruebas', 'Idempotency-Key': key } };
  const emptied = await fetch(url, options);
  assert.equal(emptied.status, 200);
  assert.deepEqual((await emptied.json()).data, { usuario_id: userId, items: [], version: 2 });
});

test('consulta de catálogo utiliza los contratos y diferencia faltantes de fallos', async () => {
  const base = 'http://localhost';
  const available = catalogAvailability({
    productsUrl: base,
    inventoryUrl: base,
    fetchJson: async (url) => Response.json({
      success: true,
      data: url.pathname.startsWith('/api/productos/')
        ? { id: productId }
        : { producto_id: productId, disponibles: 3 },
    }),
  });
  assert.equal(await available(productId), 3);
  const missing = catalogAvailability({
    productsUrl: base, inventoryUrl: base, fetchJson: async () => new Response(null, { status: 404 }),
  });
  await assert.rejects(missing(productId), { status: 404 });
  const unavailable = catalogAvailability({
    productsUrl: base, inventoryUrl: base, fetchJson: async () => new Response(null, { status: 500 }),
  });
  await assert.rejects(unavailable(productId), { status: 503 });
});
