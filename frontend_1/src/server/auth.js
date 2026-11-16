/* ══ Password hashing + session cookie (server only) ══════════════════
   Passwords: bcrypt (one-way hash). A hash can't be decoded back to the
   password — at login, bcrypt.compare() hashes the typed password with
   the salt stored inside the hash and checks whether the results match.

   Session: httpOnly cookie "rimworld_session" = base64url(payload).HMAC-SHA256.
   The payload only carries the username + expiry; the user's role is
   re-read from PostgreSQL on every request, so edits/deletes apply at once. */
import crypto from "node:crypto";
import bcrypt from "bcryptjs";
import { query } from "./db.js";

export const SESSION_COOKIE = "rimworld_session";
const SESSION_TTL_S = 60 * 60 * 8; // 8 hours
const BCRYPT_COST = 12;

export const ROLES = ["superuser", "user"];
export const SUPERUSER = "superuser";

/* compared against when the username doesn't exist, so a wrong username
   takes as long as a wrong password (no user enumeration via timing) */
const DUMMY_HASH = bcrypt.hashSync("not-a-real-password", BCRYPT_COST);

export const hashPassword = (plain) => bcrypt.hash(plain, BCRYPT_COST);

function secret() {
  const s = process.env.SESSION_SECRET;
  if (!s || s.length < 32) throw new Error("SESSION_SECRET must be set (>= 32 chars)");
  return s;
}

const b64url = (buf) => Buffer.from(buf).toString("base64url");
const sign = (data) => crypto.createHmac("sha256", secret()).update(data).digest("base64url");

export function createSessionToken(username) {
  const payload = b64url(JSON.stringify({ u: username, n: crypto.randomBytes(24).toString("hex"),
    exp: Math.floor(Date.now() / 1000) + SESSION_TTL_S }));
  return `${payload}.${sign(payload)}`;
}

export function readSessionToken(token) {
  if (!token || typeof token !== "string") return null;
  const [payload, sig, extra] = token.split(".");
  if (!payload || !sig || extra !== undefined) return null;
  const expected = Buffer.from(sign(payload));
  const given = Buffer.from(sig);
  if (expected.length !== given.length || !crypto.timingSafeEqual(expected, given)) return null;
  try {
    const { u, n, exp } = JSON.parse(Buffer.from(payload, "base64url").toString());
    if (typeof u !== "string" || !/^[a-f0-9]{48}$/.test(n) || !Number.isInteger(exp) || exp <= Date.now() / 1000) return null;
    return u;
  } catch {
    return null;
  }
}

export const cookieOptions = () => ({
  httpOnly: true,
  sameSite: "lax",
  secure: process.env.COOKIE_SECURE === "true",
  path: "/",
  maxAge: SESSION_TTL_S,
});

const PUBLIC_COLS = "username, nickname, role, created_at, last_login";
const tokenHash = (value) => crypto.createHash("sha256").update(value).digest("hex");

export async function startSession(username) {
  const token = createSessionToken(username);
  await query("DELETE FROM dashboard_sessions WHERE expires_at <= now()");
  await query(
    "INSERT INTO dashboard_sessions (token_hash, username, expires_at) VALUES ($1, $2, now() + interval '8 hours')",
    [tokenHash(token), username]);
  return token;
}

export async function endSession(request) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (readSessionToken(token)) await query("DELETE FROM dashboard_sessions WHERE token_hash = $1", [tokenHash(token)]);
}

export async function permitLogin(username) {
  await query("DELETE FROM dashboard_login_budget WHERE expires_at <= now()");
  const account = `user:${tokenHash(username)}`;
  // Charge the bounded global budget first. A stream of new usernames cannot grow this table without bound.
  for (const [bucket, limit, seconds] of [["global", 40, 60], [account, 8, 300]]) {
    const { rowCount } = await query(`
      INSERT INTO dashboard_login_budget (bucket, attempts, expires_at)
        VALUES ($1, 1, now() + $3::integer * interval '1 second')
      ON CONFLICT (bucket) DO UPDATE SET attempts = dashboard_login_budget.attempts + 1
        WHERE dashboard_login_budget.attempts < $2
      RETURNING attempts`, [bucket, limit, seconds]);
    if (!rowCount) return false;
  }
  return true;
}

/** Verify username + password against user_profile. Returns the user or null. */
export async function verifyLogin(username, password) {
  const { rows } = await query(`SELECT ${PUBLIC_COLS}, password FROM user_profile WHERE username = $1`, [username]);
  const row = rows[0];
  const ok = await bcrypt.compare(password, row?.password || DUMMY_HASH);
  if (!row || !row.password || !ok) return null;
  const upd = await query(
    `UPDATE user_profile SET last_login = now() WHERE username = $1 RETURNING ${PUBLIC_COLS}`, [username]);
  return upd.rows[0];
}

/** The signed-in user (fresh from the DB), or null. */
export async function getSessionUser(request) {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const username = readSessionToken(token);
  if (!username) return null;
  const { rows } = await query(`SELECT ${PUBLIC_COLS} FROM user_profile
    WHERE username = $1 AND EXISTS (SELECT 1 FROM dashboard_sessions
      WHERE token_hash = $2 AND dashboard_sessions.username = user_profile.username AND expires_at > now())`,
  [username, tokenHash(token)]);
  return rows[0] || null;
}

export { PUBLIC_COLS };
