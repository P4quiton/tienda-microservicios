import { createHash } from 'node:crypto';
import { ApiError } from './errors.js';

async function transaction(pool, run) {
  const db = await pool.connect();
  try {
    await db.query('BEGIN');
    const result = await run(db);
    await db.query('COMMIT');
    return result;
  } catch (error) {
    await db.query('ROLLBACK').catch(() => {});
    throw error;
  } finally {
    db.release();
  }
}

// jsonb no conserva el orden de las claves: se reconstruye la forma canónica del contrato
// para que una repetición idempotente devuelva exactamente lo mismo que la primera respuesta.
function lines(items) {
  return items.map((item) => ({ producto_id: item.producto_id, cantidad: item.cantidad }));
}

function canonical(cart) {
  return { usuario_id: cart.usuario_id, items: lines(cart.items) };
}

async function list(db, userId) {
  const items = await db.query(
    'SELECT producto_id, cantidad FROM carrito_items WHERE usuario_id = $1 ORDER BY producto_id',
    [userId],
  );
  return { usuario_id: userId, items: items.rows };
}

async function lockCart(db, userId) {
  await db.query('INSERT INTO carritos (usuario_id) VALUES ($1) ON CONFLICT DO NOTHING', [userId]);
  const cart = await db.query('SELECT version FROM carritos WHERE usuario_id = $1 FOR UPDATE', [userId]);
  return cart.rows[0].version;
}

async function bumpVersion(db, userId) {
  await db.query('UPDATE carritos SET version = version + 1 WHERE usuario_id = $1', [userId]);
}

async function findSnapshot(db, userId, orderId) {
  const result = await db.query(
    'SELECT usuario_id, version, items, estado, resultado FROM carrito_compras WHERE pedido_id = $1 AND usuario_id = $2',
    [orderId, userId],
  );
  return result.rows[0];
}

function matchesSnapshot(snapshot, expected) {
  return !expected || (String(snapshot.version) === expected.version &&
    snapshot.items.length === expected.items.length &&
    snapshot.items.every((item, i) => item.producto_id === expected.items[i].producto_id &&
      item.cantidad === expected.items[i].cantidad));
}

function requireSnapshot(snapshot, expected) {
  if (!snapshot || !matchesSnapshot(snapshot, expected)) {
    throw new ApiError(409, 'La versión o artículos del carrito no coinciden');
  }
}

export function cartStore(pool) {
  return {
    list: (userId) => list(pool, userId),

    ready: () => pool.query('SELECT 1 FROM carritos LIMIT 1'),

    checkout(userId) {
      return transaction(pool, async (db) => {
        const version = await lockCart(db, userId);
        const cart = await list(db, userId);
        return { carrito_id: userId, version: String(version), items: cart.items };
      });
    },

    add({ actorId, userId, key, productId, quantity, available }) {
      const hash = createHash('sha256').update(JSON.stringify([userId, productId, quantity])).digest('hex');
      return transaction(pool, async (db) => {
        // La clave también se serializa entre carritos del mismo actor.
        await db.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [actorId + ':' + key]);
        const previous = await db.query(
          'SELECT hash, resultado FROM carrito_adiciones WHERE actor_id = $1 AND clave = $2',
          [actorId, key],
        );
        if (previous.rowCount) {
          if (previous.rows[0].hash !== hash) throw new ApiError(409, 'Clave usada con otra solicitud');
          return canonical(previous.rows[0].resultado);
        }

        await lockCart(db, userId);
        const existing = await db.query(
          'SELECT cantidad FROM carrito_items WHERE usuario_id = $1 AND producto_id = $2',
          [userId, productId],
        );
        const total = (existing.rows[0]?.cantidad ?? 0) + quantity;
        if (total > 2147483647) throw new ApiError(422, 'Cantidad fuera del rango permitido', 'cantidad');
        const pending = await db.query(
          "SELECT items FROM carrito_compras WHERE usuario_id = $1 AND estado = 'pendiente'",
          [userId],
        );
        const committed = pending.rows[0]?.items.find((item) => item.producto_id === productId)?.cantidad ?? 0;
        if (total - committed > await available(productId)) throw new ApiError(409, 'Disponibilidad insuficiente');

        await db.query(
          `INSERT INTO carrito_items (usuario_id, producto_id, cantidad) VALUES ($1, $2, $3)
           ON CONFLICT (usuario_id, producto_id) DO UPDATE SET cantidad = EXCLUDED.cantidad`,
          [userId, productId, total],
        );
        await bumpVersion(db, userId);
        const result = await list(db, userId);
        await db.query(
          'INSERT INTO carrito_adiciones (actor_id, clave, hash, resultado) VALUES ($1, $2, $3, $4)',
          [actorId, key, hash, result],
        );
        return result;
      });
    },

    prepareCheckout(userId, orderId, expected) {
      return transaction(pool, async (db) => {
        await db.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', ['pedido:' + orderId]);
        const version = await lockCart(db, userId);
        const stored = await findSnapshot(db, userId, orderId);
        if (stored) {
          requireSnapshot(stored, expected);
          if (stored.estado === 'cancelado') throw new ApiError(409, 'Compra cancelada');
          return { version: stored.version, usuario_id: userId, items: lines(stored.items) };
        }
        const otherOrder = await db.query('SELECT 1 FROM carrito_compras WHERE pedido_id = $1', [orderId]);
        if (otherOrder.rowCount) throw new ApiError(409, 'Pedido asociado a otro carrito');
        const cart = await list(db, userId);
        if (!cart.items.length) throw new ApiError(409, 'El carrito está vacío');
        requireSnapshot({ version, items: cart.items }, expected);
        const pending = await db.query(
          "SELECT 1 FROM carrito_compras WHERE usuario_id = $1 AND estado = 'pendiente'",
          [userId],
        );
        if (pending.rowCount) throw new ApiError(503, 'El carrito ya tiene una compra en curso');
        await db.query(
          'INSERT INTO carrito_compras (pedido_id, usuario_id, version, items) VALUES ($1, $2, $3, $4)',
          [orderId, userId, version, JSON.stringify(cart.items)],
        );
        return { version, ...cart };
      });
    },

    finishCheckout(userId, orderId, expected) {
      return transaction(pool, async (db) => {
        await lockCart(db, userId);
        const snapshot = await findSnapshot(db, userId, orderId);
        requireSnapshot(snapshot, expected);
        if (snapshot.estado === 'cancelado') throw new ApiError(409, 'Compra pendiente inexistente');
        if (snapshot.estado === 'confirmado') return canonical(snapshot.resultado);

        for (const item of snapshot.items) {
          const removed = await db.query(
            'DELETE FROM carrito_items WHERE usuario_id = $1 AND producto_id = $2 AND cantidad = $3',
            [userId, item.producto_id, item.cantidad],
          );
          if (removed.rowCount) continue;
          const updated = await db.query(
            `UPDATE carrito_items SET cantidad = cantidad - $3
             WHERE usuario_id = $1 AND producto_id = $2 AND cantidad > $3`,
            [userId, item.producto_id, item.cantidad],
          );
          if (!updated.rowCount) throw new ApiError(409, 'Los artículos comprados ya no coinciden con el carrito');
        }
        await bumpVersion(db, userId);
        const result = await list(db, userId);
        await db.query(
          "UPDATE carrito_compras SET estado = 'confirmado', resultado = $2 WHERE pedido_id = $1",
          [orderId, result],
        );
        return result;
      });
    },

    cancelCheckout(userId, orderId, expected) {
      return transaction(pool, async (db) => {
        await lockCart(db, userId);
        const snapshot = await findSnapshot(db, userId, orderId);
        requireSnapshot(snapshot, expected);
        if (snapshot.estado === 'confirmado') throw new ApiError(409, 'Compra no cancelable');
        await db.query("UPDATE carrito_compras SET estado = 'cancelado' WHERE pedido_id = $1", [orderId]);
        return { carrito_id: userId, version: String(snapshot.version), items: lines(snapshot.items) };
      });
    },
  };
}
