import asyncio
import os
import secrets
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from typing import Annotated, Literal
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from rwt_files import (
    GAME_USERNAME, REQUEST, STAGED, available_fields, now, password_digest, prepare_updates,
    read_json, read_settings, revision, setting_target, validate_change, write_json,
)
from sync import GAME, current_state, follow
from worker import host_resources, interpret_log, service_checks


@asynccontextmanager
async def lifespan(app):
    pool = AsyncConnectionPool(open=False, min_size=1, max_size=5, timeout=5, kwargs={"row_factory": dict_row})
    async with pool:
        await pool.wait(timeout=30)
        app.state.pool = pool
        app.state.operation_lock = asyncio.Lock()
        task = asyncio.create_task(follow(pool))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="RimWorld Together app server", lifespan=lifespan)
TOKEN = os.environ["RIMWORLD_API_TOKEN"]


async def user(
    request: Request,
    authorization: Annotated[str, Header()] = "",
    x_rimworld_user: Annotated[str, Header()] = "",
):
    if not secrets.compare_digest(authorization.encode(), f"Bearer {TOKEN}".encode()) or not x_rimworld_user:
        raise HTTPException(401, "Not signed in")
    async with request.app.state.pool.connection() as conn:
        result = await conn.execute("SELECT role FROM user_profile WHERE username = %s", (unquote(x_rimworld_user),))
        account = await result.fetchone()
    if not account:
        raise HTTPException(401, "Not signed in")
    return account["role"]


async def administrator(role: Annotated[str, Depends(user)]):
    if role != "superuser":
        raise HTTPException(403, "Super-user only")


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str = Field(max_length=140)
    key: str = Field(max_length=80)
    value: StrictBool | StrictInt | StrictFloat | StrictStr


class ConfigurationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    staged_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    changes: list[Change] = Field(min_length=1, max_length=512)


@app.get("/healthz")
async def health(request: Request):
    async with request.app.state.pool.connection() as conn:
        await conn.execute("SELECT revision FROM world_config LIMIT 1")
        await conn.execute("SELECT sampled_at FROM worker_sample LIMIT 1")
    return {"status": "ok"}


@app.get("/overview", dependencies=[Depends(user)])
async def overview(request: Request):
    boot, pending, game_status = current_state()
    async with request.app.state.pool.connection() as conn:
        config = await (await conn.execute("""
            SELECT settings -> 'Configs/ServerConfig.json' AS server, world_initialized, boot_id
            FROM world_config
            """)).fetchone()
        counts = await (await conn.execute("SELECT count(*) AS registered FROM player_data")).fetchone()
    server = (config or {}).get("server") or {}
    if game_status == "ready" and (not config or not config["boot_id"] or config["boot_id"].hex != boot["id"]):
        game_status = "starting"
    operation = {"id": pending["id"], "kind": pending["kind"], "status": "pending"} if pending else boot.get("operation")
    if pending and pending["kind"] != "player-reset" and game_status != "restarting":
        operation.update(status="waiting", message="The game has not picked up the operation")
    return {
        "status": game_status, "boot_id": boot.get("id"), "started_at": boot.get("started_at"),
        "heartbeat_at": boot.get("heartbeat_at"), "version": boot.get("version"), "operation": operation,
        "server": {
            "name": server.get("Name"), "description": server.get("Description"), "max_players": server.get("MaxPlayers"),
            "bind_ip": server.get("IP"), "port": server.get("Port"),
            "host_address": os.environ.get("RIMWORLD_PUBLIC_HOST") or os.environ["RIMWORLD_HOST_BIND"],
            "host_port": int(os.environ["RIMWORLD_HOST_PORT"]),
        },
        "world_initialized": bool(config and config["world_initialized"]), "players": counts["registered"],
    }


@app.get("/config", dependencies=[Depends(administrator)])
async def configuration(request: Request):
    async with request.app.state.pool.connection() as conn:
        snapshot = await (await conn.execute("SELECT revision, settings, updated_at FROM world_config")).fetchone()
    staged = read_json(STAGED) or {}
    return {
        "snapshot": snapshot, "editable": available_fields(snapshot["settings"]) if snapshot else {},
        "staged": staged_view(staged),
    }


@app.get("/players", dependencies=[Depends(administrator)])
async def players(request: Request):
    async with request.app.state.pool.connection() as conn:
        result = await conn.execute("""
            SELECT username, colony_name, colonist_count, settlement_tiles, last_login, last_save
            FROM player_data ORDER BY lower(username), username
            """)
    rows = await result.fetchall()
    for row in rows:
        row["can_reset"] = GAME_USERNAME.fullmatch(row["username"]) is not None
    return {"players": rows}


@app.get("/logs", dependencies=[Depends(administrator)])
async def logs(request: Request, limit: Annotated[int, Query(ge=1, le=200)] = 100, before: int | None = None):
    boot, _, _ = current_state()
    if not (epoch := boot.get("epoch")):
        return {"logs": [], "next": None, "epoch": None}
    async with request.app.state.pool.connection() as conn:
        result = await conn.execute("""
            SELECT id, occurred_at, category, description FROM server_log AS log
            WHERE epoch = %s AND occurred_at >= now() - interval '7 days' AND (
                %s::bigint IS NULL OR (log.occurred_at, log.id) <
                (SELECT occurred_at, id FROM server_log WHERE id = %s AND epoch = log.epoch)
            )
            ORDER BY occurred_at DESC, id DESC LIMIT %s
            """, (epoch, before, before, limit + 1))
        rows = await result.fetchall()
    for row in rows[:limit]:
        row["category"], row["interpretation"] = interpret_log(row["description"], row["category"])
    return {"logs": rows[:limit], "next": rows[limit - 1]["id"] if len(rows) > limit else None, "epoch": epoch}


@app.get("/worker-health", dependencies=[Depends(administrator)])
async def worker_health(request: Request):
    _, _, game_status = current_state()
    checks, host = await asyncio.gather(
        service_checks(request.app.state.pool, game_status), asyncio.to_thread(host_resources),
    )
    return {"services": checks, "host": host, "checked_at": now()}


@app.get("/online-history", dependencies=[Depends(administrator)])
async def online_history(request: Request, period: Literal["24h", "3d", "7d"] = "24h"):
    end = now()
    start = end - timedelta(days={"24h": 1, "3d": 3, "7d": 7}[period])
    async with request.app.state.pool.connection() as conn:
        result = await conn.execute("""
            SELECT sampled_at, player_count, online_players
            FROM player_online_sample WHERE sampled_at >= %s ORDER BY sampled_at
            """, (start,))
        samples = await result.fetchall()
        resources = await (await conn.execute("""
            SELECT sampled_at, ram_used_bytes, ram_available_bytes, game_boot_id, game_uptime_seconds
            FROM worker_sample WHERE sampled_at >= %s ORDER BY sampled_at
            """, (start,))).fetchall()
    return {"start": start, "end": end, "samples": samples, "resources": resources}


def staged_view(staged):
    return {
        "id": staged.get("id"), "password_pending": "digest" in staged,
        "changes": [{key: change[key] for key in ("file", "key", "value")} for change in staged.get("changes", [])],
    }


def persist_stage(staged):
    if staged.get("changes") or "digest" in staged:
        staged["id"] = uuid.uuid4().hex
        write_json(STAGED, staged, mode=0o600)
        return staged_view(staged)
    STAGED.unlink(missing_ok=True)
    return staged_view({})


def require_idle(ready=False):
    boot, pending, game_status = current_state()
    if pending or (ready and game_status != "ready"):
        raise HTTPException(409, "Wait until the game server is ready and has no pending operation")
    return boot


def checked_stage(staged_id):
    staged = read_json(STAGED) or {}
    if staged.get("id") != staged_id:
        raise HTTPException(409, "Saved settings changed. Review them before continuing.")
    return staged


async def enqueue(boot, kind, **payload):
    operation = {
        "id": uuid.uuid4().hex, "base_boot": boot["id"], "requested_at": now().isoformat(),
        "kind": kind, **payload,
    }
    await asyncio.to_thread(write_json, REQUEST, operation, mode=0o600)
    return {"operation": {"id": operation["id"], "kind": operation["kind"], "status": "pending"}}


@app.patch("/config", dependencies=[Depends(administrator)])
async def change_configuration(update: ConfigurationUpdate, request: Request):
    async with request.app.state.operation_lock:
        require_idle()
        staged = checked_stage(update.staged_id)
        settings = await asyncio.to_thread(read_settings, GAME)
        if revision(settings) != update.revision:
            raise HTTPException(409, "Settings changed. Review the latest saved values before saving again.")
        merged = {(item["file"], item["key"]): item for item in staged.get("changes", [])}
        try:
            keys = set()
            for change in update.changes:
                validate_change(change.file, change.key, change.value)
                pair = (change.file, change.key)
                if pair in keys:
                    raise ValueError("Each setting can appear only once")
                keys.add(pair)
                document, field = setting_target(settings.get(change.file), change.key)
                if document[field] == change.value:
                    merged.pop(pair, None)
                else:
                    merged[pair] = {**change.model_dump(), "previous": document[field]}
            staged["changes"] = list(merged.values())
            await asyncio.to_thread(prepare_updates, GAME, staged["changes"])
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"staged": await asyncio.to_thread(persist_stage, staged)}


@app.delete("/config", dependencies=[Depends(administrator)])
async def discard_configuration(request: Request, staged_id: str | None = None):
    async with request.app.state.operation_lock:
        require_idle()
        checked_stage(staged_id)
        return {"staged": await asyncio.to_thread(persist_stage, {})}


@app.patch("/password", dependencies=[Depends(administrator)])
async def change_password(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"password"}:
            raise ValueError("Invalid password request")
        digest = password_digest(body["password"])
    except ValueError as error:
        raise HTTPException(422, "Provide a password of up to 64 printable ASCII characters without spaces, or an empty value to clear it.") from error
    async with request.app.state.operation_lock:
        require_idle()
        staged = read_json(STAGED) or {}
        staged["digest"] = digest
        return {"staged": await asyncio.to_thread(persist_stage, staged)}


@app.post("/restart", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(administrator)])
async def restart(request: Request, staged_id: str | None = None):
    async with request.app.state.operation_lock:
        boot = require_idle(ready=True)
        staged = checked_stage(staged_id)
        if staged:
            try:
                await asyncio.to_thread(prepare_updates, GAME, staged.get("changes", []))
            except ValueError as error:
                raise HTTPException(409, f"Saved changes conflict with the live settings. {error}") from error
            changes = {"changes": staged.get("changes", []), "staged_id": staged["id"]}
            if "digest" in staged:
                changes["digest"] = staged["digest"]
            return await enqueue(boot, "configuration", **changes)
        return await enqueue(boot, "restart")


class PlayerReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)


@app.post("/factory-reset", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(administrator)])
async def factory_reset(request: Request, staged_id: str | None = None):
    async with request.app.state.operation_lock:
        boot = require_idle(ready=True)
        checked_stage(staged_id)
        return await enqueue(boot, "factory-reset", staged_id=staged_id)


@app.post("/player-reset", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(administrator)])
async def reset_player(target: PlayerReset, request: Request):
    if not GAME_USERNAME.fullmatch(target.username):
        raise HTTPException(422, "This username cannot be passed to the game console")
    async with request.app.state.operation_lock:
        boot = require_idle(ready=True)
        path = GAME / "Assets/Users" / f"{target.username}.json"
        player = read_json(path) if path.resolve() == path else None
        if not player or player.get("Username") != target.username:
            raise HTTPException(404, "Game player not found")
        return await enqueue(boot, "player-reset", username=target.username)
