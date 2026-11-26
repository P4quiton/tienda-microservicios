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
  });
}
