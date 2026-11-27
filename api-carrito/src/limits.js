// Límites de uso: rate limiting y tamaño de cuerpo.
// Origen: variables de entorno -> loadLimits -> createApp (src/app.js) -> contadores en memoria.
// Alcance: los contadores viven en este proceso; con varias réplicas el límite es POR INSTANCIA.
// Retirada: borrar este módulo y sus usos en app.js (rateLimit / anonymousHit).
import { ApiError } from './errors.js';

const WINDOW_MS = 60_000;

function positiveInteger(env, name, fallback) {
  const raw = env[name];
  if (raw === undefined) return fallback;
  if (!/^[1-9]\d*$/.test(raw) || !Number.isSafeInteger(Number(raw))) {
    throw new Error(`${name} debe ser un entero positivo`);
  }
  return Number(raw);
}

// consulta/mutacion: peticiones por minuto y por titular; interna: por identidad de servicio.
// RATE_LIMIT_CHECKOUT_POR_MIN no aplica a Carrito y se ignora.
export function loadLimits(env) {
  return {
    consulta: positiveInteger(env, 'RATE_LIMIT_CONSULTA_POR_MIN', 120),
    mutacion: positiveInteger(env, 'RATE_LIMIT_MUTACION_POR_MIN', 30),
    interna: positiveInteger(env, 'RATE_LIMIT_INTERNA_POR_MIN', 300),
    maxJsonBytes: positiveInteger(env, 'MAX_JSON_BYTES', 262144),
  };
}

// Ventana fija de un minuto por (cubo, clave). Devuelve hit(bucket, key) que lanza 429 al exceder.
export function createRateLimiter({ limits, now = Date.now }) {
  const counters = new Map();
  let nextSweep = now() + WINDOW_MS;

  function sweep(time) {
    if (time < nextSweep) return;
    for (const [id, entry] of counters) if (entry.resetAt <= time) counters.delete(id);
    nextSweep = time + WINDOW_MS;
  }

  return function hit(bucket, key) {
    const time = now();
    sweep(time);
    const id = `${bucket}\u0000${key}`;
    let entry = counters.get(id);
    if (!entry || entry.resetAt <= time) {
      entry = { count: 0, resetAt: time + WINDOW_MS };
      counters.set(id, entry);
    }
    entry.count += 1;
    if (entry.count > limits[bucket]) {
      const error = new ApiError(429, 'Demasiadas solicitudes');
      error.retryAfter = Math.max(1, Math.ceil((entry.resetAt - time) / 1000));
      throw error;
    }
  };
}
