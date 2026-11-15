/* ══ Small helpers for route handlers (server only) ══════════════════ */
import { NextResponse } from "next/server";
import { getSessionUser, SUPERUSER } from "./auth";

export const json = (data, status = 200) => NextResponse.json(data, { status });
export const fail = (status, error) => NextResponse.json({ error }, { status });

/** Wraps a handler: catches DB/unknown errors so they never leak details. */
export const handle = (fn) => async (request, ctx) => {
  try {
    return await fn(request, ctx);
  } catch (err) {
    console.error("[api]", request.method, request.nextUrl?.pathname, err);
    return fail(500, "Internal server error");
  }
};

/** Returns [user, null] for a superuser, or [null, errorResponse]. */
export async function requireSuperuser(request) {
  const user = await getSessionUser(request);
  if (!user) return [null, fail(401, "Not signed in")];
  if (user.role !== SUPERUSER) return [null, fail(403, "Super-user only")];
  return [user, null];
}
