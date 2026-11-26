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

function checkoutPayload(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body) ||
      Object.keys(body).sort().join(',') !== 'items,pedido_id,version' ||
      typeof body.version !== 'string' || !/^(0|[1-9][0-9]*)$/.test(body.version) ||
      !Array.isArray(body.items) || !body.items.length) {
    throw new ApiError(422, 'Se requieren pedido_id, version e items válidos', 'body');
  }
  const orderId = readUUID(body.pedido_id, 'pedido_id');
  const items = body.items.map((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item) ||
        Object.keys(item).sort().join(',') !== 'cantidad,producto_id' ||
        !Number.isInteger(item.cantidad) || item.cantidad < 1 || item.cantidad > 2147483647) {
      throw new ApiError(422, 'Artículo inválido', 'items');
    }
    return { producto_id: readUUID(item.producto_id, 'producto_id'), cantidad: item.cantidad };
  });
  items.sort((a, b) => a.producto_id.localeCompare(b.producto_id));
  if (items.some((item, i) => i && item.producto_id === items[i - 1].producto_id)) {
    throw new ApiError(422, 'Productos duplicados', 'items');
  }
  return { orderId, expected: { version: body.version, items } };
}

export function createApp({ store, available, publicKey, serviceToken, enableDraftCartCheckout = false }) {
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

  if (enableDraftCartCheckout) {
    app.get('/api/carrito/:userId/checkout', async (req, res) => {
      auth.service(req);
      const userId = readUUID(req.params.userId, 'usuario_id');
      success(res, await store.checkout(userId));
    });
    for (const [action, method] of [
      ['preparar', 'prepareCheckout'], ['confirmar', 'finishCheckout'], ['cancelar', 'cancelCheckout'],
    ]) {
      app.post('/api/carrito/:userId/checkout/' + action, async (req, res) => {
        auth.service(req);
        const userId = readUUID(req.params.userId, 'usuario_id');
        const { orderId, expected } = checkoutPayload(req.body);
        success(res, await store[method](userId, orderId, expected));
      });
    }
  }

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

  app.delete('/api/carrito/:userId/vaciar', async (req, res) => {
    auth.service(req);
    const userId = readUUID(req.params.userId, 'usuario_id');
    const cart = await store.list(userId);
    if (cart.items.length) {
      throw new ApiError(409, 'Se requiere identificar la versión del carrito comprada');
    }
    success(res, cart);
  });

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
