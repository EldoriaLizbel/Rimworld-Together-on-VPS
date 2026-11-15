import { getSessionUser } from "../../../../src/server/auth";
import { fail, handle, json } from "../../../../src/server/http";

export const dynamic = "force-dynamic";

const routes = {
  GET: new Set(["overview", "config", "players", "logs", "worker-health", "online-history"]),
  PATCH: new Set(["config", "password"]),
  DELETE: new Set(["config"]),
  POST: new Set(["restart", "factory-reset", "player-reset"]),
};

const forward = handle(async (request, { params }) => {
  const { action } = params;
  if (!routes[request.method]?.has(action)) return fail(404, "Unknown game operation");
  const user = await getSessionUser(request);
  if (!user) return fail(401, "Not signed in");
  if (action !== "overview" && user.role !== "superuser") return fail(403, "Super-user only");
  const headers = {
    Authorization: `Bearer ${process.env.RIMWORLD_API_TOKEN}`,
    "X-Rimworld-User": encodeURIComponent(user.username),
  };
  let body;
  if (request.method !== "GET" && request.headers.get("sec-fetch-site") === "cross-site") {
    return fail(403, "Cross-site request rejected");
  }
  if (request.method === "PATCH" || action === "player-reset") {
    if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
      return fail(415, "Expected JSON settings");
    }
    body = await request.text();
    if (body.length > 180000) return fail(413, "Request is too large");
    headers["Content-Type"] = "application/json";
  }
  const target = new URL(`/${action}`, process.env.RIMWORLD_API_URL);
  if (action === "logs") {
    for (const key of ["limit", "before"]) {
      const value = request.nextUrl.searchParams.get(key);
      if (value) target.searchParams.set(key, value);
    }
  }
  if (action === "online-history" && request.nextUrl.searchParams.has("period")) {
    target.searchParams.set("period", request.nextUrl.searchParams.get("period"));
  }
  if ((["restart", "factory-reset"].includes(action) || (action === "config" && request.method === "DELETE")) && request.nextUrl.searchParams.has("staged_id")) {
    target.searchParams.set("staged_id", request.nextUrl.searchParams.get("staged_id"));
  }
  try {
    const response = await fetch(target, {
      method: request.method, headers, body, cache: "no-store", signal: AbortSignal.timeout(8000),
    });
    const data = await response.json();
    if (!response.ok) {
      return fail(response.status, typeof data.detail === "string" ? data.detail : "The app server rejected the request");
    }
    return json(data, response.status);
  } catch {
    return fail(503, "The game app server is unavailable");
  }
});

export { forward as GET, forward as PATCH, forward as POST, forward as DELETE };
