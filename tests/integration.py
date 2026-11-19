"""Live integration against disposable Docker projects only; never reads .rwt-deploy."""
import argparse
import contextlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ops  # noqa: E402

PASSWORD = "test-only-generated-for-an-isolated-db"
SECRET = "d" * 64
WRONG = "sdfghjkl-incorrect-fixture"


def free_ports(count):
    with contextlib.ExitStack() as stack:
        sockets = [stack.enter_context(socket.socket()) for _ in range(count)]
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]


def env(path, values):
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    path.chmod(0o600)


def fixture(root, project, ports):
    root.mkdir(mode=0o700)
    (root / "game").mkdir(mode=0o755)
    (root / "game").chmod(0o755)
    env(root / "compose.env", dict(
        COMPOSE_PROJECT_NAME=project, RWT_GAME_DATA=(root / "game").as_posix(),
        RWT_WEB_ENV_FILE=(root / "web.env").as_posix(),
        RWT_POSTGRES_ENV_FILE=(root / "postgres.env").as_posix(),
        RIMWORLD_API_DB_PASSWORD=SECRET, RIMWORLD_API_TOKEN=SECRET,
        RIMWORLD_HOST_BIND="127.0.0.1", RIMWORLD_HOST_PORT=ports[0],
        RIMWORLD_WEB_BIND="127.0.0.1", RIMWORLD_WEB_PORT=ports[1],
        POSTGRES_VERSION="16.14-bookworm@sha256:64154d0babcb1741988719e703419af0382b19953706149f9872fbd0f438efa8",
    ))
    env(root / "postgres.env", dict(POSTGRES_USER="app_user", POSTGRES_DB="app_db",
        POSTGRES_PASSWORD=PASSWORD, RIMWORLD_WEB_DB_PASSWORD=PASSWORD, RIMWORLD_ADMIN_PASSWORD=PASSWORD))
    env(root / "web.env", dict(DATABASE_URL=f"postgresql://rimworld_web:{PASSWORD}@postgres:5432/app_db",
                             SESSION_SECRET=SECRET, COOKIE_SECURE="false"))
    return ops.Stack(root)


def http(base, path, expected, *, method="GET", payload=None, cookie=None, origin=None):
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    if method != "GET":
        headers["Origin"] = origin or base
    if payload is not None:
        headers["Content-Type"] = "application/json"
    call = urllib.request.Request(base + path, headers=headers, method=method,
                                  data=json.dumps(payload).encode() if payload is not None else None)
    try:
        response = urllib.request.urlopen(call, timeout=12)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        assert response.status == expected, (path, response.status, expected, raw[:250])
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "no-store"
        return json.loads(raw), response.headers.get("Set-Cookie", "")


def auth(base):
    login = {"username": "rimworldtogether", "password": PASSWORD}
    http(base, "/api/game/config", 401)
    http(base, "/api/auth/login", 403, method="POST", payload=login, origin="https://different.invalid")
    _, cookie = http(base, "/api/auth/login", 200, method="POST", payload=login)
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" not in cookie
    token = cookie.split(";")[0]
    http(base, "/api/auth/me", 200, cookie=token)
    http(base, "/api/game/config", 200, cookie=token)
    data, _ = http(base, "/api/game/data-tables", 200, cookie=token)
    assert len(data["tables"]) == 5
    for entry in data["tables"]:
        http(base, "/api/game/data-rows?table=" + entry["name"], 200, cookie=token)
    http(base, "/api/game/data-rows?table=user_profile", 404, cookie=token)
    http(base, "/api/game/data-tables", 401)
    http(base, "/api/game/factory-reset", 422, method="POST", payload={}, cookie=token)
    http(base, "/api/users", 201, method="POST", payload={"username": "regular", "role": "user", "password": PASSWORD},
         cookie=token)
    _, player = http(base, "/api/auth/login", 200, method="POST", payload={"username": "regular", "password": PASSWORD})
    player = player.split(";")[0]
    http(base, "/api/game/overview", 200, cookie=player)
    http(base, "/api/game/data-tables", 403, cookie=player)
    http(base, "/api/game/restart", 403, method="POST", payload={"confirm": "restart"}, cookie=player)
    http(base, "/api/auth/logout", 200, method="POST", cookie=token)
    http(base, "/api/auth/me", 401, cookie=token)
    for _ in range(8):
        http(base, "/api/auth/login", 401, method="POST", payload={"username": "unknown", "password": WRONG})
    http(base, "/api/auth/login", 429, method="POST", payload={"username": "unknown", "password": WRONG})


def cleanup(projects):
    # Project names are random and dedicated to this test. No all-project pruning.
    for project in projects:
        for listing, removal in ((["ps", "-aq"], ["rm", "-f"]), (["network", "ls", "-q"], ["network", "rm"]),
                                 (["volume", "ls", "-q"], ["volume", "rm"])):
            ids = subprocess.check_output(["docker", *listing, "--filter", f"label=com.docker.compose.project={project}"],
                                          text=True).split()
            if ids:
                subprocess.run(["docker", *removal, *ids], check=True)


def variant(stack, service, label, dockerfile_suffix=""):
    source = stack.state()["active"][service]["ref"]
    new_tag = f"{stack.project}-{service}-{label}"
    content = f'FROM {source}\nLABEL rwt.test="{label}"\n{dockerfile_suffix}'
    stack.command("build", "-q", "-t", new_tag, "-", body=content.encode())
    return ops.pin(stack, service, stack.image_id(new_tag))


def candidate(service, ref, letter):
    version = letter * 40
    return {"commit": version, "images": {service: ref}, "schema": [8, 8]}


def migration_transaction(stack, root):
    stack.sql("CREATE DATABASE migration_fixture;")
    alternate = root / "migration-fixture"
    shutil.copytree(ops.db.DIRECTORY, alternate)
    final = alternate / "007_dashboard_security.sql"
    final.write_text(final.read_text().replace("BEGIN;", "BEGIN;\nCREATE TABLE test_atomic_marker(id int);\nSELECT 1/0;", 1))

    def empty_db(source, allow_fail=False):
        return stack.compose("exec", "-T", "-e", "POSTGRES_DB=migration_fixture", "postgres", "sh", "-c",
                             ops.PSQL, body=source.encode(), capture=True, allowed=allow_fail)

    assert empty_db(ops.db.script("apply", directory=alternate), True).returncode != 0
    state = empty_db("SELECT max(version) FROM schema_migrations; "
                     "SELECT to_regclass('public.test_atomic_marker') IS NULL;").stdout.decode().splitlines()
    assert state == ["6", "t"]
    assert b"verified 007 baseline=false" in empty_db(ops.db.script("apply")).stdout


def reset_acceptance(stack, base):
    account_count = stack.sql("SELECT count(*) FROM user_profile;")
    marker = stack.game / "Assets/Saves/reset-fixture.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(b"old-player-save")
    user = stack.game / "Assets/Users/reset-fixture.json"
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('{"Username":"reset-fixture"}')
    modfile = stack.game / "Configs/ModConfig.json"
    mods = json.loads(modfile.read_text())
    mods["ModConfigs"] = [{"ModID": "reset.fixture", "Name": "Old world mod"}]
    modfile.write_text(json.dumps(mods))
    stack.sql("INSERT INTO player_data (username) VALUES ('reset-fixture') ON CONFLICT DO NOTHING;")
    _, cookie = http(base, "/api/auth/login", 200, method="POST",
                     payload={"username": "rimworldtogether", "password": PASSWORD})
    cookie = cookie.split(";")[0]
    http(base, "/api/game/factory-reset", 422, method="POST", payload={"confirm": "factory-reset"}, cookie=cookie)
    result, _ = http(base, "/api/game/factory-reset", 202, method="POST",
                     payload={"confirm": "factory-reset", "erase_world": "RESET WORLD"}, cookie=cookie)
    reset_id = result["operation"]["id"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        overview, _ = http(base, "/api/game/overview", 200, cookie=cookie)
        operation = overview.get("operation") or {}
        if operation.get("id") == reset_id and operation.get("status") == "applied" and overview["status"] == "ready":
            break
        time.sleep(2)
    else:
        raise AssertionError("World reset did not become ready")
    assert overview["world_initialized"] is False
    assert overview["mods"] == []
    assert overview["players"] == 0
    assert not user.exists() and not marker.exists()
    archived = stack.game / ".factory-resets" / reset_id
    assert (archived / "Assets/Saves/reset-fixture.json").read_bytes() == b"old-player-save"
    assert json.loads((archived / "Configs/ModConfig.json").read_text())["ModConfigs"][0]["ModID"] == "reset.fixture"
    assert stack.sql("SELECT count(*) FROM player_data;") == "0"
    assert stack.sql("SELECT count(*) FROM user_profile;") == account_count
    assert stack.sql("SELECT world_reset_id::text FROM world_config;").replace("-", "") == reset_id
    assert stack.sql(f"SELECT count(*) FROM player_online_sample WHERE boot_id <> '{overview['boot_id']}';") == "0"
    for name in ("Site", "Road"):
        assert json.loads((stack.game / f"Configs/Actions/{name}.json").read_text())["IsEnabled"] is True
    # Another normal restart must not purge the new generation again.
    stack.sql("INSERT INTO player_data (username) VALUES ('new-generation-marker');")
    http(base, "/api/game/restart", 202, method="POST", payload={"confirm": "restart"}, cookie=cookie)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        current, _ = http(base, "/api/game/overview", 200, cookie=cookie)
        if current["status"] == "ready" and current["boot_id"] != overview["boot_id"]:
            break
        time.sleep(2)
    else:
        raise AssertionError("Normal restart did not complete")
    assert stack.sql("SELECT count(*) FROM player_data WHERE username='new-generation-marker';") == "1"
    print("World reset passed: archived files, cleared mods/game players/history, preserved dashboard accounts and repeat restart")


def test_live(root, project, recovered, ports):
    stack = fixture(root / "source", project, ports)
    options = argparse.Namespace(scope="all", maintenance=False, dry_run=True)
    ops.apply_release(stack, options, local=True)
    assert not stack.containers("postgres")
    options.dry_run = False
    ops.apply_release(stack, options, local=True)
    assert json.loads((stack.game / "Configs/Actions/Site.json").read_text())["IsEnabled"] is True
    assert json.loads((stack.game / "Configs/Actions/Road.json").read_text())["IsEnabled"] is True
    assert stack.schema("status") == [f"applied {i:03}" for i in range(1, 9)]
    assert stack.sql("SELECT count(*) FROM schema_migrations;") == "8"
    migration_transaction(stack, root)
    # Legacy schema from 9f114b0: no migration ledger or session tables. The
    # disposable fixture proves baseline inspection preserves an existing account.
    stack.sql("""INSERT INTO user_profile (username, nickname, role) VALUES ('preserved','fixture','user');
                 DROP TABLE dashboard_sessions, dashboard_login_budget; ALTER TABLE world_config DROP COLUMN world_reset_id; DROP TABLE schema_migrations;""")
    statuses = stack.schema("status")
    assert statuses[0] == "baseline 001" and statuses[-1] == "pending 008"
    assert stack.schema("apply")[-1] == "verified 008 baseline=false"
    assert stack.sql("SELECT nickname FROM user_profile WHERE username='preserved';") == "fixture"
    assert stack.schema("apply") == []
    try:
        stack.sql("UPDATE schema_migrations SET checksum='broken' WHERE version=8;")
        try:
            stack.schema("apply")
            raise AssertionError("Checksum drift was accepted")
        except ValueError:
            pass
    finally:
        checksum = ops.db.migrations()[-1][1]
        stack.sql(f"UPDATE schema_migrations SET checksum='{checksum}' WHERE version=8;")
    base = f"http://127.0.0.1:{ports[1]}"
    auth(base)
    ops.external("127.0.0.1", ports[0])
    original = {key: stack.containers(key) for key in ("rimworld", "api", "postgres")}
    web_image = stack.state()["active"]["web"]["ref"]
    changed = variant(stack, "web", "variant")
    web_target = candidate("web", changed, "f")
    web_only = argparse.Namespace(scope="web", dry_run=False, version=web_target["commit"], maintenance=False)
    scratch = root / "source/game/fixture-preserved.sav"
    scratch.write_bytes(b"test fixture standing in for persisted save bytes")
    ops.apply_release(stack, web_only, target=web_target)
    assert stack.containers("web")["Image"] == stack.image_id(changed)
    web_now = stack.containers("web")["Id"]
    ops.apply_release(stack, web_only, target=web_target)
    assert stack.containers("web")["Id"] == web_now
    assert json.loads((stack.folder / "deployments.jsonl").read_text().splitlines()[-1])["status"] == "no-op"
    ops.rollback(stack, web_only)
    assert stack.containers("web")["Image"] == stack.image_id(web_image)
    failed = variant(stack, "web", "failure", 'CMD ["node","-e","process.exit(1)"]\n')
    try:
        ops.apply_release(stack, web_only, target=candidate("web", failed, "e"))
        raise AssertionError("The failing dashboard became active")
    except ValueError:
        pass
    assert json.loads((stack.folder / "deployments.jsonl").read_text().splitlines()[-1])["status"] == "application-rollback-passed"
    assert stack.containers("web")["Image"] == stack.image_id(web_image)
    for key, container in original.items():
        now = stack.containers(key)
        assert now["Id"] == container["Id"] and now["State"]["StartedAt"] == container["State"]["StartedAt"]
    assert scratch.read_bytes().startswith(b"test fixture")
    api_next = variant(stack, "api", "variant")
    api_only = argparse.Namespace(scope="api", dry_run=False, maintenance=False)
    ops.apply_release(stack, api_only, target=candidate("api", api_next, "d"))
    assert stack.containers("rimworld")["State"]["StartedAt"] == original["rimworld"]["State"]["StartedAt"]
    assert stack.containers("postgres")["Id"] == original["postgres"]["Id"]
    game_next = variant(stack, "rimworld", "variant")
    game_change = argparse.Namespace(scope="rimworld", dry_run=False, maintenance=False)
    game_target = candidate("rimworld", game_next, "c")
    try:
        ops.apply_release(stack, game_change, target=game_target)
        raise AssertionError("Game update without maintenance was accepted")
    except ValueError as error:
        assert "--maintenance" in str(error)
    game_change.maintenance = True
    ops.apply_release(stack, game_change, target=game_target)
    last_event = json.loads((stack.folder / "deployments.jsonl").read_text().splitlines()[-1])
    full = last_event["backup"]
    assert stack.containers("rimworld")["Image"] == stack.image_id(game_next)
    _, metadata = ops.backups.verify(ops.backup_root(stack), full)
    assert metadata["schema"] == 8
    request = argparse.Namespace(backup=full, confirm=full, new_project=recovered, scope="full",
                                 game_port=ports[3], web_port=ports[4], start=True)
    ops.restore(stack, request)
    isolated = ops.Stack(stack.folder / "recovery" / recovered)
    assert isolated.sql("SELECT nickname FROM user_profile WHERE username='preserved';") == "fixture"
    assert (isolated.game / scratch.name).read_bytes() == scratch.read_bytes()
    assert not (isolated.folder / "restore-incomplete").exists()
    assert stack.sql("SELECT nickname FROM user_profile WHERE username='preserved';") == "fixture"
    isolated.smoke(ops.scopes(isolated, "all"))
    reset_acceptance(isolated, f"http://127.0.0.1:{ports[4]}")
    print("Live integration passed: legacy migration, checksum rejection, login, no-op, web/API/game scopes, failure rollback and full restore", flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    run_id = uuid.uuid4().hex[:8]
    names = ("rwt-ci-" + run_id, "rwt-recovery-" + run_id)
    with tempfile.TemporaryDirectory(prefix="rwt-ci-") as temporary:
        try:
            test_live(Path(temporary).resolve(), *names, free_ports(5))
        finally:
            cleanup(names)
