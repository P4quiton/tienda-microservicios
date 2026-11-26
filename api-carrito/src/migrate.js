import { readdir, readFile } from 'node:fs/promises';
import { openPool } from './db.js';

const pool = openPool();
const folder = new URL('../migrations/', import.meta.url);

// Cada migración es idempotente y se aplica en orden de nombre (001, 002...).
try {
  const files = (await readdir(folder)).filter((name) => name.endsWith('.sql')).sort();
  for (const file of files) await pool.query(await readFile(new URL(file, folder), 'utf8'));
} finally {
  await pool.end();
}
