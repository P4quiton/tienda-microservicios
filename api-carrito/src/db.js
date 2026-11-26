import pg from 'pg';

export function openPool(env = process.env) {
  return new pg.Pool({
    host: env.DB_HOST,
    port: Number(env.DB_PORT ?? 5432),
    database: env.DB_DATABASE,
    user: env.DB_USERNAME,
    password: env.DB_PASSWORD,
    connectionTimeoutMillis: 2000,
    statement_timeout: 3000,
    // Cliente: statement_timeout lo aplica el servidor y no corta una BD congelada (pausada/colgada tras
    // haber conectado); sin esto /ready y las rutas esperaban indefinidamente en vez de responder 503.
    query_timeout: 5000,
  });
}
