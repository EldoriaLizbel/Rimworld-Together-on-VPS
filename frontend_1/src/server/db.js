/* ══ PostgreSQL connection (server only) ══════════════════════════════
   DATABASE_URL = postgresql://<user>:<pass>@postgres:5432/app_db
   The app container joins the internal docker network `app_network`,
   so the hostname `postgres` resolves to the database container. */
import pg from "pg";

/* timestamp without time zone (OID 1114): keep the DB's wall-clock value
   as a string — otherwise node would reinterpret it in the container's TZ */
pg.types.setTypeParser(1114, (v) => v);

const g = globalThis;

export function getPool() {
  if (!g.__llPool) {
    if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is not set");
    g.__llPool = new pg.Pool({
      connectionString: process.env.DATABASE_URL,
      max: 5,
      idleTimeoutMillis: 30_000,
      connectionTimeoutMillis: 4000,
      statement_timeout: 5000,
      query_timeout: 6500,
    });
  }
  return g.__llPool;
}

export const query = (text, params) => getPool().query(text, params);
