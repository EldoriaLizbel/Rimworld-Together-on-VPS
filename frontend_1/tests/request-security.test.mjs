import assert from "node:assert/strict";
import { test } from "node:test";
import { allowOrigin, boundedJsonBody } from "../src/server/request-security.mjs";
import { createSessionToken, readSessionToken, cookieOptions } from "../src/server/auth.js";
import { parseUserBody } from "../src/server/users.js";

test("only same-origin writes are allowed, with explicit proxy configuration", () => {
  const request = (origin, site) => new Request("http://internal/api", {
    method: "POST", headers: { host: "127.0.0.1:10005", origin, "sec-fetch-site": site },
  });
  assert(allowOrigin(request("http://127.0.0.1:10005", "same-origin")));
  assert(!allowOrigin(request("https://other.invalid", "cross-site")));
  assert(!allowOrigin(request("http://127.0.0.1:10005", "same-site")));
  assert(!allowOrigin(request("http://127.0.0.1:10005/evil", "same-origin")));
  assert(allowOrigin(request("https://dash.invalid", "same-origin"), "https://dash.invalid"));
  assert(!allowOrigin(request("https://dash.invalid", "same-origin")));
});

test("JSON body parsing enforces bytes, media type and JSON syntax", async () => {
  const request = (body, type) => new Request("http://localhost/api", {
    method: "POST", body, headers: { "content-type": type },
  });
  assert.equal((await boundedJsonBody(request('{"x":1}', "application/json"), 12)).value.x, 1);
  assert.equal((await boundedJsonBody(request('"😊😊😊"', "application/json"), 10)).status, 413);
  assert.equal((await boundedJsonBody(request("{}", "application/jsonfoo"), 10)).status, 415);
  assert.equal((await boundedJsonBody(request("not json", "application/json"), 10)).status, 400);
});

test("each login token rotates and rejects tampering or trailing fields", () => {
  process.env.SESSION_SECRET = "temporary-test-value".repeat(3);
  const first = createSessionToken("sample");
  const second = createSessionToken("sample");
  assert.notEqual(first, second);
  assert.equal(readSessionToken(first), "sample");
  assert.equal(readSessionToken(first + ".extra"), null);
  assert.equal(readSessionToken("x" + first), null);
  process.env.COOKIE_SECURE = "true";
  assert.equal(cookieOptions().secure, true);
  assert.equal(cookieOptions().httpOnly, true);
});

test("account changes cannot set managed timestamps or truncate bcrypt passwords", () => {
  const valid = { username: "demo", password: "example", role: "user" };
  assert.equal(parseUserBody(valid, "create").username, "demo");
  assert.throws(() => parseUserBody({ ...valid, created_at: "" }, "update"));
  assert.throws(() => parseUserBody({ ...valid, password: "🙂".repeat(20) }, "create"));
  assert.throws(() => parseUserBody({ ...valid, role: "owner" }, "create"));
});
