/* ══ Small helpers for route handlers (server only) ══════════════════ */
import { NextResponse } from "next/server";
import { getSessionUser, SUPERUSER } from "./auth";
import { allowOrigin, boundedJsonBody } from "./request-security.mjs";

export const json = (data, status = 200) => NextResponse.json(data, { status, headers: { "Cache-Control": "no-store" } });
export const fail = (status, error) => json({ error }, status);
export const readBody = async (request, max = 8192) => {
  const result = await boundedJsonBody(request, max);
  return result.status ? [null, fail(result.status, {
    400: "Invalid JSON request", 413: "Request is too large", 415: "Expected JSON",
  }[result.status])] : [result, null];
};

/** Wraps a handler: catches DB/unknown errors so they never leak details. */
export const handle = (fn) => async (request, ctx) => {
  try {
    if (!allowOrigin(request, process.env.DASHBOARD_ORIGIN)) return fail(403, "Cross-origin request rejected");
    return await fn(request, ctx);
  } catch (err) {
    console.error("[api] Request failed", request.method, err?.name);
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
