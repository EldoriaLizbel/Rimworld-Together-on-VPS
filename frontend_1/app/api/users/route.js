import { query } from "../../../src/server/db";
import { hashPassword, PUBLIC_COLS } from "../../../src/server/auth";
import { json, fail, handle, requireSuperuser } from "../../../src/server/http";
import { parseUserBody, mapDbError } from "../../../src/server/users";

export const dynamic = "force-dynamic";

/** List users (super-user only). The password hash is never returned. */
export const GET = handle(async (request) => {
  const [, deny] = await requireSuperuser(request);
  if (deny) return deny;
  const { rows } = await query(`SELECT ${PUBLIC_COLS} FROM user_profile ORDER BY created_at, username`);
  return json({ users: rows });
});

/** Create a user (super-user only). Password is bcrypt-hashed before INSERT. */
export const POST = handle(async (request) => {
  const [, deny] = await requireSuperuser(request);
  if (deny) return deny;
  try {
    const u = parseUserBody(await request.json().catch(() => ({})), "create");
    const { rows } = await query(
      `INSERT INTO user_profile (username, nickname, password, role)
       VALUES ($1, $2, $3, $4)
       RETURNING ${PUBLIC_COLS}`,
      [u.username, u.nickname, await hashPassword(u.password), u.role]);
    return json({ user: rows[0] }, 201);
  } catch (err) {
    const e = mapDbError(err);
    return fail(e.status, e.message);
  }
});
