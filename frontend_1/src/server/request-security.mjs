const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export function allowOrigin(request, configured) {
  if (SAFE.has(request.method)) return true;
  if (["cross-site", "same-site"].includes(request.headers.get("sec-fetch-site"))) return false;
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || origin === "null" || !host) return false;
  try {
    const parsed = new URL(origin);
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.origin !== origin) return false;
    return configured ? parsed.origin === new URL(configured).origin : parsed.host === host.toLowerCase();
  } catch {
    return false;
  }
}

export async function boundedJsonBody(request, max) {
  if (!/^application\/json(?:\s*;|\s*$)/i.test(request.headers.get("content-type") || "")) return { status: 415 };
  if (!request.body) return { status: 400 };
  const reader = request.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0;
  let text = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > max) {
        await reader.cancel();
        return { status: 413 };
      }
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
    return { value: JSON.parse(text), text };
  } catch {
    return { status: 400 };
  } finally {
    reader.releaseLock();
  }
}
