import { query } from "../../../src/server/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    await query("SELECT 1 FROM dashboard_sessions LIMIT 1");
    const api = await fetch(new URL("/healthz", process.env.RIMWORLD_API_URL), {
      signal: AbortSignal.timeout(1500), cache: "no-store",
    });
    if (!api.ok || (await api.json()).contract !== 2) throw new Error("API contract unavailable");
    return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ status: "unavailable" }, { status: 503 });
  }
}
