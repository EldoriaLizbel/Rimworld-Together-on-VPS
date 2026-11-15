import { getPool } from "../../../../src/server/db";
import {
  hashPassword, PUBLIC_COLS, SUPERUSER,
  createSessionToken, cookieOptions, SESSION_COOKIE,
} from "../../../../src/server/auth";
import { json, fail, handle, requireSuperuser } from "../../../../src/server/http";
import { parseUserBody, mapDbError, decodeParam, BadRequest } from "../../../../src/server/users";

export const dynamic = "force-dynamic";

/** Locks the super-user rows so two admins can't both demote/delete the last one. */
async function otherSuperusers(client, username) {
  const { rows } = await client.query(
    "SELECT username FROM user_profile WHERE role = $1 AND username <> $2 FOR UPDATE", [SUPERUSER, username]);
  return rows.length;
}

async function inTx(fn) {
  const client = await getPool().connect();
  try {
    await client.query("BEGIN");
    const out = await fn(client);
    await client.query("COMMIT");
    return out;
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}

/** Update a dashboard account. Blank password keeps its existing value. */
export const PUT = handle(async (request, { params }) => {
  const [me, deny] = await requireSuperuser(request);
  if (deny) return deny;
  const target = decodeParam(params.username);
  try {
    const u = parseUserBody(await request.json().catch(() => ({})), "update");
    const newHash = u.password ? await hashPassword(u.password) : null;

    const user = await inTx(async (client) => {
      const cur = await client.query("SELECT role FROM user_profile WHERE username = $1 FOR UPDATE", [target]);
      if (!cur.rows[0]) throw new BadRequest("User not found", 404);
      if (target === me.username && u.role !== cur.rows[0].role)
        throw new BadRequest("You can't change your own role", 409);
      if (cur.rows[0].role === SUPERUSER && u.role !== SUPERUSER && (await otherSuperusers(client, target)) === 0)
        throw new BadRequest("Can't demote the last super-user", 409);

      const { rows } = await client.query(
        `UPDATE user_profile SET
           username   = $2,
           nickname   = $3,
           password   = COALESCE($4, password),
           role       = $5
         WHERE username = $1
         RETURNING ${PUBLIC_COLS}`,
        [target, u.username, u.nickname, newHash, u.role]);
      return rows[0];
    });

    const res = json({ user });
    /* renamed yourself → re-issue the session cookie for the new username */
    if (target === me.username && user.username !== me.username)
      res.cookies.set(SESSION_COOKIE, createSessionToken(user.username), cookieOptions());
    return res;
  } catch (err) {
    const e = mapDbError(err);
    return fail(e.status, e.message);
  }
});

/** Delete a user (super-user only). You can't delete yourself or the last super-user. */
export const DELETE = handle(async (request, { params }) => {
  const [me, deny] = await requireSuperuser(request);
  if (deny) return deny;
  const target = decodeParam(params.username);
  if (target === me.username) return fail(409, "You can't delete the account you're signed in with");
  try {
    await inTx(async (client) => {
      const cur = await client.query("SELECT role FROM user_profile WHERE username = $1 FOR UPDATE", [target]);
      if (!cur.rows[0]) throw new BadRequest("User not found", 404);
      if (cur.rows[0].role === SUPERUSER && (await otherSuperusers(client, target)) === 0)
        throw new BadRequest("Can't delete the last super-user", 409);
      await client.query("DELETE FROM user_profile WHERE username = $1", [target]);
    });
    return json({ ok: true });
  } catch (err) {
    const e = mapDbError(err);
    return fail(e.status, e.message);
  }
});
