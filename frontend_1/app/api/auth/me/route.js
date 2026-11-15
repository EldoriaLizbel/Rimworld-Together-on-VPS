import { getSessionUser } from "../../../../src/server/auth";
import { json, fail, handle } from "../../../../src/server/http";

export const dynamic = "force-dynamic";

export const GET = handle(async (request) => {
  const user = await getSessionUser(request);
  return user ? json({ user }) : fail(401, "Not signed in");
});
