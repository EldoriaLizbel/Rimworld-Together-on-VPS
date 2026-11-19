import { getSessionUser } from "../../../../src/server/auth";
import { fail, handle, json, readBody } from "../../../../src/server/http";

export const dynamic = "force-dynamic";

const routes = {
  GET: new Set(["overview", "config", "players", "logs", "worker-health", "online-history", "data-tables", "data-rows"]),
  PATCH: new Set(["config", "password"]),
  DELETE: new Set(["config"]),
  POST: new Set(["restart", "factory-reset", "player-reset"]),
};

const forward = handle(async (request, { params }) => {
  const { action } = await params;
  if (!routes[request.method]?.has(action)) return fail(404, "Unknown game operation");
  const user = await getSessionUser(request);
  if (!user) return fail(401, "Not signed in");
  if (action !== "overview" && user.role !== "superuser") return fail(403, "Super-user only");
  const headers = {
    Authorization: `Bearer ${process.env.RIMWORLD_API_TOKEN}`,
    "X-Rimworld-User": encodeURIComponent(user.username),
  };
  let body;
  if (request.method === "PATCH" || request.method === "POST") {
    const [data, error] = await readBody(request, 180000);
    if (error) return error;
    body = data.text;
    headers["Content-Type"] = "application/json";
  }
  const target = new URL(`/${action}`, process.env.RIMWORLD_API_URL);
  if (action === "data-rows") {
    const table = request.nextUrl.searchParams.get("table") || "";
    const allowed = new Set(["world_config", "server_log", "player_data", "player_online_sample", "worker_sample"]);
    if (!allowed.has(table)) return fail(404, "Unknown server data table");
    target.pathname = `/data-rows/${table}`;
    target.searchParams.set("page", request.nextUrl.searchParams.get("page") || "0");
  }
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
      method: request.method, headers, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
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
