import asyncio
import os
import platform
import re
from datetime import datetime, timedelta
from http.client import HTTPConnection, HTTPException
from pathlib import Path

from psycopg import Error
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout

SESSION_EVENT = re.compile(r"^\[(Log in|Log out)\] > (.+?) \| [^\r\n]+$")
PLAYER_EVENT = re.compile(r"^\[(Register|Reset player|Save game|Save Map|Set world|Add settlement)\] > (.+)$")
SAVE_REQUEST = re.compile(r"^User '(.+)' has been forced to save$")


def interpret_log(line, category):
    if match := SESSION_EVENT.fullmatch(line):
        event, username = match.groups()
        action = "logged in" if event == "Log in" else "logged out"
        return "player", f"{username} {action}."
    if match := PLAYER_EVENT.fullmatch(line):
        event, value = match.groups()
        return {
            "Register": ("player", f"{value} registered on the game server."),
            "Reset player": ("player", f"The game server reset active gameplay data for {value}."),
            "Save game": ("save", f"{value} saved their game."),
            "Save Map": ("save", f"{value} uploaded a map save."),
            "Set world": ("world", f"{value} created the shared world. The server received and saved the world settings."),
            "Add settlement": ("world", f"A player established a settlement on tile {value}."),
        }[event]
    if line.startswith("[Server backup] > "):
        return "backup", "The game server completed a full backup of its data."
    if match := SAVE_REQUEST.fullmatch(line):
        return "save", f"The game server requested a save from {match[1]}."
    if category == "management":
        if line == "Restart requested by the server dashboard":
            return "restart", "Restarting the game server. Players may be disconnected."
        if line.startswith("Management operation configuration applied"):
            return "restart", "The configuration was saved and the game server is starting a new log history."
        if line.startswith("Management operation factory-reset applied"):
            return "restart", "Official configuration defaults were restored. A new server log history has started."
        if line.startswith("Management operation restart applied"):
            return "restart", "The game server is starting again with its existing configuration."
    if line.startswith("Listening for users at "):
        return "startup", "The game server began accepting connections."
    return category, None


async def sample_online(cur, boot, status, observed_at):
    await cur.execute("DELETE FROM player_online_sample WHERE sampled_at < %s", (observed_at - timedelta(days=7),))
    if status not in ("ready", "stopped", "failed") or not boot.get("id"):
        return
    await cur.execute("""
        SELECT session_counts, last_log_id FROM player_online_sample
        WHERE boot_id = %s ORDER BY sampled_at DESC LIMIT 1
        """, (boot["id"],))
    previous = await cur.fetchone()
    counts = previous["session_counts"] if previous else {}
    log_id = previous["last_log_id"] if previous else 0
    await cur.execute("""
        SELECT id, description FROM server_log
        WHERE boot_id = %s AND id > %s
          AND (description LIKE '[Log in] > %%' OR description LIKE '[Log out] > %%')
        ORDER BY id
        """, (boot["id"], log_id))
    for row in await cur.fetchall():
        log_id = row["id"]
        if match := SESSION_EVENT.fullmatch(row["description"]):
            event, username = match.groups()
            if event == "Log in":
                counts[username] = counts.get(username, 0) + 1
            elif counts.get(username, 0) > 1:
                counts[username] -= 1
            else:
                counts.pop(username, None)
    online = sorted(counts) if status == "ready" else []
    await cur.execute("""
        INSERT INTO player_online_sample (sampled_at, boot_id, online_players, session_counts, last_log_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (sampled_at) DO UPDATE SET boot_id = EXCLUDED.boot_id,
          online_players = EXCLUDED.online_players, session_counts = EXCLUDED.session_counts,
          last_log_id = EXCLUDED.last_log_id
        WHERE (player_online_sample.boot_id, player_online_sample.online_players,
               player_online_sample.session_counts, player_online_sample.last_log_id)
          IS DISTINCT FROM (EXCLUDED.boot_id, EXCLUDED.online_players, EXCLUDED.session_counts, EXCLUDED.last_log_id)
        """, (observed_at.replace(second=0, microsecond=0), boot["id"], online, Jsonb(counts), log_id))


def http_ready(host, port, path):
    connection = HTTPConnection(host, port, timeout=2)
    try:
        connection.request("GET", path)
        with connection.getresponse() as response:
            return response.status == 200
    except (HTTPException, OSError):
        return False
    finally:
        connection.close()


async def service_checks(pool, game_status):
    async def postgres_ready():
        try:
            async with pool.connection(timeout=2) as conn:
                await asyncio.wait_for(conn.execute("SELECT 1"), timeout=2)
            return True
        except (Error, PoolTimeout, TimeoutError):
            return False

    web, postgres, beekeeper = await asyncio.gather(
        asyncio.to_thread(http_ready, "web", 3000, "/api/health"),
        postgres_ready(),
        asyncio.to_thread(http_ready, "beekeeper", 5800, "/") if os.getenv("BEEKEEPER_ENABLED", "1") == "1"
        else asyncio.sleep(0, result="disabled"),
    )
    game = "healthy" if game_status == "ready" else game_status
    return [
        {"service": service, "status": state if isinstance(state, str) else ("healthy" if state else "unavailable"),
         "check": check}
        for service, state, check in (
            ("web", web, "Next.js HTTP endpoint"),
            ("api", True, "FastAPI response"),
            ("postgres", postgres, "PostgreSQL query"),
            ("rimworld", game, "Game listener and heartbeat"),
            ("beekeeper", beekeeper, "Beekeeper HTTP interface"),
        )
    ]


def host_resources():
    model = None
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "model name" and value.strip():
                model = value.strip()
                break
    except OSError:
        pass

    return {
        "cpu_model": model, "logical_cpus": os.cpu_count(),
        "architecture": platform.machine(), "memory": host_memory(),
    }


def host_memory():
    try:
        fields = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                fields[key] = int(value.split()[0]) * 1024
        total, available = fields["MemTotal"], fields["MemAvailable"]
        if total > 0:
            available = min(total, max(0, available))
            return {"total_bytes": total, "available_bytes": available, "used_bytes": total - available}
    except (OSError, KeyError, ValueError, IndexError):
        pass

    return None


async def sample_resources(cur, boot, status, observed_at):
    minute = observed_at.replace(second=0, microsecond=0)
    await cur.execute("SELECT 1 FROM worker_sample WHERE sampled_at = %s", (minute,))
    if await cur.fetchone():
        return
    memory = await asyncio.to_thread(host_memory) or {}
    uptime = None
    if status == "ready" and boot.get("started_at"):
        uptime = max(0, int((observed_at - datetime.fromisoformat(boot["started_at"])).total_seconds()))
    await cur.execute("""
        INSERT INTO worker_sample (sampled_at, ram_used_bytes, ram_available_bytes, game_boot_id, game_uptime_seconds)
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT (sampled_at) DO NOTHING
        """, (minute, memory.get("used_bytes"), memory.get("available_bytes"), boot.get("id"), uptime))
    await cur.execute("DELETE FROM worker_sample WHERE sampled_at < %s", (observed_at - timedelta(days=7),))
