// Frontera de confianza de X-Forwarded-For: una IP falsificada por un cliente directo no evade el limitador;
// solo un proxy listado en TRUSTED_PROXIES puede indicar la IP real del cliente.
import assert from 'node:assert/strict';
import { generateKeyPairSync, randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { after, describe, test } from 'node:test';
import { createApp } from '../src/app.js';
import { parseTrustedProxies } from '../src/proxies.js';

const { publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const LIMITS = { consulta: 3, mutacion: 3, interna: 3, maxJsonBytes: 262144 };
const servers = [];

async function listen(trustedProxies) {
  const cart = { usuario_id: 'x', items: [], version: 0 };
  const app = createApp({
    publicKey, serviceToken: 'token-solo-pruebas', limits: LIMITS, trustedProxies,
    store: { list: async () => cart, ready: async () => {} },
  });
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  servers.push(server);
  return `http://127.0.0.1:${server.address().port}/api/carrito/${randomUUID()}`;
}
after(() => Promise.all(servers.map((s) => new Promise((r) => s.close(r)))));

// Sin credencial el fallo 401 cuenta contra la IP que ve el servicio; el cupo de consultas es 3.
const status = async (url, forwardedFor) => (await fetch(url, { headers: { 'X-Forwarded-For': forwardedFor } })).status;
const run = async (url, count, ipFor) => {
  const result = [];
  for (let i = 0; i < count; i += 1) result.push(await status(url, ipFor(i)));
  return result;
};

describe('parseTrustedProxies', () => {
  test('vacío o ausente no confía en nadie', () => {
    assert.deepEqual(parseTrustedProxies(undefined), []);
    assert.deepEqual(parseTrustedProxies(''), []);
    assert.deepEqual(parseTrustedProxies(' , '), []);
  });

  test('acepta IP y CIDR IPv4/IPv6', () => {
    assert.deepEqual(parseTrustedProxies('172.18.0.0/16, 10.0.0.5 ,::1/128'), ['172.18.0.0/16', '10.0.0.5', '::1/128']);
  });

  test('rechaza rangos /0 IPv4 e IPv6', () => {
    for (const raw of ['0.0.0.0/0', '::/0']) {
      assert.throws(() => parseTrustedProxies(raw), /TRUSTED_PROXIES/, raw);
    }
  });

  test('rechaza confianza indiscriminada y valores mal formados', () => {
    for (const raw of ['*', 'true', '1', 'loopback', '10.0.0.1/33', '10.0.0.1/', '::1/129', '10.0.0.1/8/8', 'nginx', '10.0.0.1,*']) {
      assert.throws(() => parseTrustedProxies(raw), /TRUSTED_PROXIES/, raw);
    }
  });
});

describe('limitador frente a X-Forwarded-For', () => {
  test('cliente directo (sin proxies de confianza): rotar la IP falsificada NO evade el 429', async () => {
    const url = await listen([]);
    const codes = await run(url, 5, (i) => `198.51.100.${i + 1}`);
    assert.deepEqual(codes, [401, 401, 401, 429, 429]);
  });

  test('valor por defecto de createApp sin TRUSTED_PROXIES en el entorno: tampoco confía', async () => {
    const previous = process.env.TRUSTED_PROXIES;
    delete process.env.TRUSTED_PROXIES;
    try {
      const url = await listen(undefined);
      assert.deepEqual(await run(url, 4, (i) => `198.51.100.${i + 1}`), [401, 401, 401, 429]);
    } finally {
      if (previous !== undefined) process.env.TRUSTED_PROXIES = previous;
    }
  });

  test('proxy de confianza: se usa la IP reenviada (clientes distintos no se bloquean entre sí)', async () => {
    const url = await listen(['127.0.0.1']);
    const codes = await run(url, 5, (i) => `198.51.100.${i + 1}`);
    assert.deepEqual(codes, [401, 401, 401, 401, 401]);
  });

  test('proxy de confianza: la misma IP reenviada sí se limita', async () => {
    const url = await listen(['127.0.0.1']);
    assert.deepEqual(await run(url, 5, () => '198.51.100.7'), [401, 401, 401, 429, 429]);
  });

  test('proxy de confianza: un X-Forwarded-For previo falsificado por el cliente no sirve para rotar', async () => {
    // Nginx sobrescribe la cabecera, pero aunque llegara "falso, real", express toma la dirección de más a la
    // derecha que no es de confianza (la real); rotar el valor de la izquierda no evade el límite.
    const url = await listen(['127.0.0.1']);
    const codes = await run(url, 5, (i) => `203.0.113.${i + 1}, 198.51.100.7`);
    assert.deepEqual(codes, [401, 401, 401, 429, 429]);
  });

  test('un proxy que no está en la lista no es de confianza aunque exista la lista', async () => {
    const url = await listen(['10.99.0.0/16']);
    assert.deepEqual(await run(url, 4, (i) => `198.51.100.${i + 1}`), [401, 401, 401, 429]);
  });
});
