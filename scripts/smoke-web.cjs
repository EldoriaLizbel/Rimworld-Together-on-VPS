const net = require("node:net");
const { Client } = require("pg");

async function verify() {
  const get = (url, options) => fetch(url, { signal: AbortSignal.timeout(5000), ...options });
  let response = await get("http://127.0.0.1:3000/api/health");
  if (!response.ok) throw Error("Dashboard dependency readiness failed");
  response = await get("http://api:8000/healthz");
  if (!response.ok || (await response.json()).contract !== 2) throw Error("FastAPI contract check failed");
  response = await get("http://127.0.0.1:3000/api/game/config");
  if (response.status !== 401) throw Error("Unauthenticated admin access was not denied");
  const db = new Client({ connectionString: process.env.DATABASE_URL, connectionTimeoutMillis: 4000 });
  await db.connect();
  try { await db.query("SELECT username FROM user_profile LIMIT 1"); } finally { await db.end(); }
  console.log("Web: health, Web → API contract, auth rejection, and authenticated PostgreSQL query passed");
}
verify().catch((error) => { console.error("Dashboard smoke failed:", error.name); process.exitCode = 1; });
