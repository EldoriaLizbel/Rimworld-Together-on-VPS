import { verifyLogin, startSession, endSession, permitLogin, cookieOptions, SESSION_COOKIE } from "../../../../src/server/auth";
import { json, fail, handle, readBody } from "../../../../src/server/http";

export const dynamic = "force-dynamic";

export const POST = handle(async (request) => {
  const [data, error] = await readBody(request, 4096);
  if (error) return error;
  const body = data.value || {};
  const username = typeof body.username === "string" ? body.username.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!/^[A-Za-z0-9._@-]{1,64}$/.test(username) || !password || Buffer.byteLength(password, "utf8") > 72) {
    return fail(400, "Provide a valid username and password");
  }
  if (!await permitLogin(username)) return fail(429, "Too many sign-in attempts. Try again later.");

  const user = await verifyLogin(username, password);
  if (!user) return fail(401, "Invalid username or password");

  const res = json({ user });
  await endSession(request);
  res.cookies.set(SESSION_COOKIE, await startSession(user.username), cookieOptions());
  return res;
});
