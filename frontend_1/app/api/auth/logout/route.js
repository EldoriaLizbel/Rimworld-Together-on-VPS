import { cookieOptions, SESSION_COOKIE } from "../../../../src/server/auth";
import { json } from "../../../../src/server/http";

export const dynamic = "force-dynamic";

export async function POST() {
  const res = json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { ...cookieOptions(), maxAge: 0 });
  return res;
}
