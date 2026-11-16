import { cookieOptions, endSession, SESSION_COOKIE } from "../../../../src/server/auth";
import { json, handle } from "../../../../src/server/http";

export const dynamic = "force-dynamic";

export const POST = handle(async (request) => {
  await endSession(request);
  const res = json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { ...cookieOptions(), maxAge: 0 });
  return res;
});
