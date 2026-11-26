import express from 'express';
import { authentication, uuidV4 } from './auth.js';
import { ApiError } from './errors.js';

function readUUID(value, field) {
  if (typeof value !== 'string' || !uuidV4.test(value)) {
    throw new ApiError(422, 'Se requiere un UUID v4', field);
  }
  return value.toLowerCase();
}

const DATABASE_DOWN_CODES = ['ECONNREFUSED', 'ECONNRESET', 'ETIMEDOUT', 'ENOTFOUND', 'EHOSTUNREACH', 'ENETUNREACH',
  '57P01', '57P02', '57P03', '57014', '53300'];
const DATABASE_DOWN_MESSAGES = [
  'timeout exceeded when trying to connect', 'Connection terminated', 'Client has encountered a connection error',
  'Cannot use a pool after calling end', 'Client was closed',
];

// Los errores de conexión del driver no siempre traen código: se reconocen también por mensaje.
function isDatabaseUnavailable(error) {
  if (error instanceof ApiError) return false;
  return error.code?.startsWith('08') || DATABASE_DOWN_CODES.includes(error.code) ||
    error.errors?.some?.((inner) => DATABASE_DOWN_CODES.includes(inner.code)) ||
    DATABASE_DOWN_MESSAGES.some((text) => error.message?.includes(text));
}

function success(res, data) {
  res.json({ success: true, message: 'OK', data });
}

function exactObject(value, names, field) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join(',') !== names.join(',')) {
    throw new ApiError(422, 'Cuerpo inválido para ' + field, field);
  }
  return value;
}

function readVersion(value) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new ApiError(422, 'Se requiere un entero no negativo', 'version_original');
  }
  return value;
}

// Líneas del snapshot: exactamente producto_id, cantidad y linea_id; sin repetir linea_id.
function readLines(items) {
  if (!Array.isArray(items) || !items.length) throw new ApiError(422, 'Se requiere al menos un artículo', 'items');
  const lines = items.map((item) => {
    exactObject(item, ['cantidad', 'linea_id', 'producto_id'], 'items');
    if (!Number.isInteger(item.cantidad) || item.cantidad < 1 || item.cantidad > 2147483647) {
      throw new ApiError(422, 'Artículo inválido', 'items');
    }
    return {
      producto_id: readUUID(item.producto_id, 'producto_id'),
      cantidad: item.cantidad,
      linea_id: readUUID(item.linea_id, 'linea_id'),
    };
  });
  if (new Set(lines.map((line) => line.linea_id)).size !== lines.length) {
    throw new ApiError(422, 'Líneas duplicadas', 'items');
  }
  return lines;
}

export function createApp({ store, available, publicKey, serviceToken }) {
  const app = express();
  const auth = authentication({ publicKey, serviceToken });

  app.disable('x-powered-by');
  app.disable('etag');
  app.use(express.json({ limit: '16kb' }));

  app.get('/health', (_req, res) => res.json({ status: 'ok', service: 'api-carrito' }));
  app.get('/ready', async (_req, res) => {
    try {
      await store.ready();
      res.json({ status: 'ok', service: 'api-carrito' });
    } catch {
      res.status(503).json({ status: 'unavailable', service: 'api-carrito' });
    }
  });

  app.use('/api/carrito', (_req, res, next) => {
    res.set('Cache-Control', 'no-store');
    next();
  });

  app.get('/api/carrito/:userId', async (req, res) => {
    // Primero la identidad (401/403) y después la validación del parámetro (422).
    if (req.get('X-Service-Token') !== undefined) auth.service(req);
    else await auth.owner(req, req.params.userId.toLowerCase());
    const userId = readUUID(req.params.userId, 'usuario_id');
    success(res, await store.list(userId));
  });

  app.post('/api/carrito/:userId/agregar', async (req, res) => {
    const actorId = await auth.owner(req, req.params.userId.toLowerCase());
    const userId = readUUID(req.params.userId, 'usuario_id');
    const key = readUUID(req.get('Idempotency-Key'), 'Idempotency-Key');
    const body = req.body;
    if (!body || typeof body !== 'object' || Array.isArray(body) ||
        Object.keys(body).some((name) => !['producto_id', 'cantidad'].includes(name))) {
      throw new ApiError(422, 'Se requieren producto_id y cantidad', 'body');
    }
    const productId = readUUID(body.producto_id, 'producto_id');
    if (!Number.isInteger(body.cantidad) || body.cantidad < 1 || body.cantidad > 2147483647) {
      throw new ApiError(422, 'Se requiere una cantidad entera positiva', 'cantidad');
    }
    success(res, await store.add({
      actorId, userId, key, productId, quantity: body.cantidad, available,
    }));
  });

  // Operaciones internas de Pedidos: identidad (401), usuario (422), Idempotency-Key (422) y cuerpo (422), en ese orden.
  function internal(method, action, parseBody, run) {
    app[method]('/api/carrito/:userId/' + action, async (req, res) => {
      auth.service(req);
      const userId = readUUID(req.params.userId, 'usuario_id');
      const key = readUUID(req.get('Idempotency-Key'), 'Idempotency-Key');
      success(res, await run({ userId, key, ...parseBody(req.body) }));
    });
  }

  internal('delete', 'vaciar', () => ({}), (input) => store.clear(input));
  internal('post', 'iniciar', (body) => {
    exactObject(body, ['pedido_id', 'version_original'], 'body');
    return { orderId: readUUID(body.pedido_id, 'pedido_id'), originalVersion: readVersion(body.version_original) };
  }, (input) => store.start(input));
  internal('post', 'finalizar', (body) => {
    exactObject(body, ['items', 'pedido_id', 'version_original'], 'body');
    return {
      orderId: readUUID(body.pedido_id, 'pedido_id'),
      originalVersion: readVersion(body.version_original),
      items: readLines(body.items),
    };
  }, (input) => store.finish(input));
  internal('post', 'liberar', (body) => {
    exactObject(body, ['pedido_id'], 'body');
    return { orderId: readUUID(body.pedido_id, 'pedido_id') };
  }, (input) => store.release(input));

  app.use((_req, _res, next) => next(new ApiError(404, 'Ruta inexistente')));

  app.use((error, _req, res, _next) => {
    let reply = error;
    if (error.type?.startsWith('entity.')) reply = new ApiError(400, 'JSON incorrecto');
    else if (!(error instanceof ApiError) && error.status >= 400 && error.status < 500) {
      // Errores de cliente de Express/body-parser (codificación, charset, ruta mal codificada...).
      reply = new ApiError(400, 'Solicitud incorrecta');
    }
    if (isDatabaseUnavailable(error)) reply = new ApiError(503, 'Base de datos no disponible');
    if (!(reply instanceof ApiError)) reply = new ApiError(500, 'Error interno');
    res.status(reply.status).json({ success: false, message: reply.message, errors: reply.errors });
  });

  return app;
}
