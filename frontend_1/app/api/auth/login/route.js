import { verifyLogin, createSessionToken, cookieOptions, SESSION_COOKIE } from "../../../../src/server/auth";
import { json, fail, handle } from "../../../../src/server/http";

export const dynamic = "force-dynamic";

export const POST = handle(async (request) => {
  const body = await request.json().catch(() => ({}));
  const username = typeof body.username === "string" ? body.username.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!username || !password) return fail(400, "Username and password are required");

  const user = await verifyLogin(username, password);
  if (!user) return fail(401, "Invalid username or password");

  const res = json({ user });
  res.cookies.set(SESSION_COOKIE, createSessionToken(user.username), cookieOptions());
  return res;
});
