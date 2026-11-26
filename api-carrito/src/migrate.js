import { readFile } from 'node:fs/promises';
import { openPool } from './db.js';

const pool = openPool();

try {
  const sql = await readFile(new URL('../migrations/001-carrito.sql', import.meta.url), 'utf8');
  await pool.query(sql);
} finally {
  await pool.end();
}
