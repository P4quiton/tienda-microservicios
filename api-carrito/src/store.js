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

// Identidad registrada para las operaciones internas (par Pedidos -> Carrito).
const CALLER = 'pedidos';

// jsonb no conserva el orden de las claves: se reconstruye la forma canónica del contrato
// para que una repetición idempotente devuelva exactamente lo mismo que la primera respuesta.
function lines(items) {
  return items.map((item) => ({ producto_id: item.producto_id, cantidad: item.cantidad, linea_id: item.linea_id }));
}

function canonical(cart) {
  return { usuario_id: cart.usuario_id, items: lines(cart.items), version: cart.version };
}

// Una sola sentencia: versión e items provienen de la misma instantánea.
async function list(db, userId) {
  const rows = await db.query(
    `SELECT c.version, i.producto_id, i.cantidad, i.linea_id
     FROM carritos c LEFT JOIN carrito_items i USING (usuario_id)
     WHERE c.usuario_id = $1 ORDER BY i.producto_id`,
    [userId],
  );
  return {
    usuario_id: userId,
    items: rows.rows.filter((row) => row.producto_id).map(({ producto_id, cantidad, linea_id }) => ({ producto_id, cantidad, linea_id })),
    version: Number(rows.rows[0]?.version ?? 0),
  };
}

async function lockCart(db, userId) {
  await db.query('INSERT INTO carritos (usuario_id) VALUES ($1) ON CONFLICT DO NOTHING', [userId]);
  const cart = await db.query('SELECT version FROM carritos WHERE usuario_id = $1 FOR UPDATE', [userId]);
  return Number(cart.rows[0].version);
}

async function bumpVersion(db, userId) {
  await db.query('UPDATE carritos SET version = version + 1 WHERE usuario_id = $1', [userId]);
}

async function findOrder(db, orderId) {
  const result = await db.query(
    'SELECT usuario_id, version, items, estado, resultado FROM carrito_compras WHERE pedido_id = $1',
    [orderId],
  );
  const row = result.rows[0];
  return row && { ...row, version: Number(row.version) };
}

function fingerprint(parts) {
  return createHash('sha256').update(JSON.stringify(parts)).digest('hex');
}

// Orden de bloqueos (siempre el mismo, evita interbloqueos): clave -> pedido -> fila del carrito.
// Operación interna idempotente: misma clave y solicitud devuelve el resultado registrado; otra solicitud, 409.
function internalOperation(pool, { operation, key, orderId, parts, run }) {
  const hash = fingerprint([operation, ...parts]);
  return transaction(pool, async (db) => {
    await db.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [CALLER + ':' + key]);
    const previous = await db.query(
      'SELECT operacion, hash, resultado FROM carrito_operaciones WHERE identidad = $1 AND clave = $2',
      [CALLER, key],
    );
    if (previous.rowCount) {
      if (previous.rows[0].hash !== hash) throw new ApiError(409, 'Clave usada con otra solicitud');
      return previous.rows[0].resultado;
    }
    if (orderId) await db.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', ['pedido:' + orderId]);
    const result = await run(db);
    await db.query(
      'INSERT INTO carrito_operaciones (identidad, clave, operacion, hash, resultado) VALUES ($1, $2, $3, $4, $5)',
      [CALLER, key, operation, hash, JSON.stringify(result)],
    );
    return result;
  });
}

function sameLines(snapshotItems, items) {
  const byLine = new Map(snapshotItems.map((item) => [item.linea_id, item]));
  return byLine.size === items.length && items.every((item) => {
    const kept = byLine.get(item.linea_id);
    return kept && kept.producto_id === item.producto_id && kept.cantidad === item.cantidad;
  });
}

function requireSameCart(order, userId) {
  if (order.usuario_id !== userId) throw new ApiError(409, 'Pedido asociado a otro carrito');
}

export function cartStore(pool) {
  return {
    list: (userId) => list(pool, userId),

    ready: () => pool.query('SELECT 1 FROM carritos LIMIT 1'),

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
          const stored = previous.rows[0].resultado;
          // Resultados anteriores al contrato 1.1.0 no traen version ni linea_id: se responde el estado actual.
          return Number.isInteger(stored.version) && stored.items.every((item) => item.linea_id)
            ? canonical(stored) : list(db, userId);
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

        // Si la línea existe se conserva su linea_id; si es nueva recibe uno propio (default de la columna).
        await db.query(
          `INSERT INTO carrito_items (usuario_id, producto_id, cantidad) VALUES ($1, $2, $3)
           ON CONFLICT (usuario_id, producto_id) DO UPDATE SET cantidad = EXCLUDED.cantidad`,
          [userId, productId, total],
        );
        await bumpVersion(db, userId);
        const result = await list(db, userId);
        await db.query(
          'INSERT INTO carrito_adiciones (actor_id, clave, hash, resultado) VALUES ($1, $2, $3, $4)',
          [actorId, key, hash, JSON.stringify(result)],
        );
        return result;
      });
    },

    // Vaciado total fuera de checkout activo. La versión sube solo si cambia el contenido.
    clear({ userId, key }) {
      return internalOperation(pool, {
        operation: 'vaciar', key, parts: [userId],
        run: async (db) => {
          await lockCart(db, userId);
          const active = await db.query(
            "SELECT 1 FROM carrito_compras WHERE usuario_id = $1 AND estado = 'pendiente'", [userId],
          );
          if (active.rowCount) throw new ApiError(409, 'El carrito tiene un checkout activo');
          const removed = await db.query('DELETE FROM carrito_items WHERE usuario_id = $1', [userId]);
          if (removed.rowCount) await bumpVersion(db, userId);
          return list(db, userId);
        },
      });
    },

    // Captura el snapshot inmutable del pedido. Repetir el mismo pedido devuelve el snapshot original.
    start({ userId, key, orderId, originalVersion }) {
      return internalOperation(pool, {
        operation: 'iniciar', key, orderId, parts: [userId, orderId, originalVersion],
        run: async (db) => {
          const version = await lockCart(db, userId);
          const stored = await findOrder(db, orderId);
          if (stored) {
            requireSameCart(stored, userId);
            if (stored.estado === 'cancelado') throw new ApiError(409, 'Checkout liberado');
            if (stored.version !== originalVersion) throw new ApiError(409, 'La versión del carrito no coincide');
            return { pedido_id: orderId, version_original: stored.version, items: lines(stored.items) };
          }
          const cart = await list(db, userId);
          if (version !== originalVersion) throw new ApiError(409, 'La versión del carrito cambió');
          if (!cart.items.length) throw new ApiError(409, 'El carrito está vacío');
          const active = await db.query(
            "SELECT 1 FROM carrito_compras WHERE usuario_id = $1 AND estado = 'pendiente'", [userId],
          );
          if (active.rowCount) throw new ApiError(409, 'El carrito ya tiene un checkout activo');
          await db.query(
            'INSERT INTO carrito_compras (pedido_id, usuario_id, version, items) VALUES ($1, $2, $3, $4)',
            [orderId, userId, version, JSON.stringify(cart.items)],
          );
          return { pedido_id: orderId, version_original: version, items: cart.items };
        },
      });
    },

    // Retira las cantidades del snapshot por linea_id y conserva todo lo añadido después.
    finish({ userId, key, orderId, originalVersion, items }) {
      return internalOperation(pool, {
        operation: 'finalizar', key, orderId,
        parts: [userId, orderId, originalVersion, [...items].sort((a, b) => a.linea_id.localeCompare(b.linea_id))],
        run: async (db) => {
          await lockCart(db, userId);
          const snapshot = await findOrder(db, orderId);
          if (!snapshot) throw new ApiError(409, 'No existe un checkout iniciado para el pedido');
          requireSameCart(snapshot, userId);
          if (snapshot.version !== originalVersion || !sameLines(snapshot.items, items)) {
            throw new ApiError(409, 'La versión o artículos del snapshot no coinciden');
          }
          if (snapshot.estado === 'cancelado') throw new ApiError(409, 'Checkout liberado');
          if (snapshot.estado === 'confirmado') return canonical(snapshot.resultado);

          for (const item of snapshot.items) {
            const reduced = await db.query(
              `UPDATE carrito_items SET cantidad = cantidad - $4
               WHERE usuario_id = $1 AND linea_id = $2 AND producto_id = $3 AND cantidad > $4`,
              [userId, item.linea_id, item.producto_id, item.cantidad],
            );
            if (reduced.rowCount) continue;
            const removed = await db.query(
              'DELETE FROM carrito_items WHERE usuario_id = $1 AND linea_id = $2 AND producto_id = $3 AND cantidad = $4',
              [userId, item.linea_id, item.producto_id, item.cantidad],
            );
            if (!removed.rowCount) throw new ApiError(409, 'Los artículos comprados ya no coinciden con el carrito');
          }
          await bumpVersion(db, userId);
          const result = await list(db, userId);
          await db.query(
            "UPDATE carrito_compras SET estado = 'confirmado', resultado = $2 WHERE pedido_id = $1",
            [orderId, JSON.stringify(result)],
          );
          return result;
        },
      });
    },

    // Cierra el checkout sin tocar artículos. Sin snapshot, registra el cierre para impedir un inicio tardío.
    release({ userId, key, orderId }) {
      return internalOperation(pool, {
        operation: 'liberar', key, orderId, parts: [userId, orderId],
        run: async (db) => {
          const version = await lockCart(db, userId);
          const stored = await findOrder(db, orderId);
          if (!stored) {
            await db.query(
              "INSERT INTO carrito_compras (pedido_id, usuario_id, version, items, estado) VALUES ($1, $2, $3, '[]', 'cancelado')",
              [orderId, userId, version],
            );
          } else {
            requireSameCart(stored, userId);
            if (stored.estado === 'confirmado') throw new ApiError(409, 'Checkout ya finalizado');
            await db.query("UPDATE carrito_compras SET estado = 'cancelado' WHERE pedido_id = $1", [orderId]);
          }
          return list(db, userId);
        },
      });
    },
  };
}
