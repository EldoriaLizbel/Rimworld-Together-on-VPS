/* ══ user_profile validation + DB error mapping (server only) ════════ */
import { ROLES } from "./auth";

const USERNAME_RE = /^[A-Za-z0-9._@-]{1,64}$/;

export class BadRequest extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}

const str = (v) => (typeof v === "string" ? v.trim() : "");

/**
 * Normalises a user form body.
 * mode "create": username, password, role required
 * mode "update": password blank = keep the current one
 */
export function parseUserBody(body, mode) {
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new BadRequest("Expected an account object");
  if ("created_at" in body || "last_login" in body) throw new BadRequest("Account timestamps are managed automatically");
  const out = {
    username:   str(body.username),
    nickname:   str(body.nickname) || null,
    password:   typeof body.password === "string" ? body.password : "",
    role:       str(body.role),
  };
  if (!USERNAME_RE.test(out.username))
    throw new BadRequest("Username: 1–64 characters, letters, digits and . _ @ - only");
  if (out.nickname && out.nickname.length > 100) throw new BadRequest("Nickname is too long (max 100)");
  if (!ROLES.includes(out.role)) throw new BadRequest(`Role must be one of: ${ROLES.join(", ")}`);
  if (mode === "create" && !out.password) throw new BadRequest("Password is required");
  if (out.password.length > 72) throw new BadRequest("Password is too long (max 72)"); // bcrypt limit
  return out;
}

/** Maps PostgreSQL errors to a 4xx message, or rethrows. */
export function mapDbError(err) {
  if (err instanceof BadRequest) return err;
  if (err?.code === "23505") return new BadRequest("That username already exists", 409);
  throw err;
}

export const decodeParam = (p) => {
  try { return decodeURIComponent(p); } catch { return p; }
};
