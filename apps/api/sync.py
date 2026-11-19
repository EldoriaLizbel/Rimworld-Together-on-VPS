import asyncio
import hashlib
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from rwt_files import BOOT, IDENTIFIER, LOGINS, REQUEST, SPOOL, WORLD, now, open_game_file, read_json, read_settings, revision
from save_summary import summary
from worker import sample_online, sample_resources

GAME = Path("/game")
STREAM = re.compile(r"\d{4}-\d{2}-\d{2}_([0-9a-f]{32})\.jsonl")
LOG = logging.getLogger(__name__)


def current_state():
    boot = read_json(BOOT) or {}
    pending = read_json(REQUEST)
    heartbeat = boot.get("heartbeat_at")
    fresh = heartbeat and now() - datetime.fromisoformat(heartbeat) < timedelta(seconds=10)
    status = boot.get("status", "offline")
    if status == "ready" and not fresh:
        status = "offline"
    elif status == "starting" and now() - datetime.fromisoformat(boot["started_at"]) > timedelta(seconds=30):
        status = "failed"
    if pending and pending["kind"] != "player-reset" and now() - datetime.fromisoformat(pending["requested_at"]) < timedelta(seconds=45):
        status = "restarting"
    return boot, pending, status


def safe_read(path):
    try:
        data = read_json(path) if not path.is_symlink() else None
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def read_players(game=GAME, reset_id=None):
    login_directory = LOGINS / reset_id if reset_id else LOGINS
    settlements = defaultdict(set)
    for file in (game / "Assets/Settlements").glob("*.json"):
        data = safe_read(file)
        if isinstance(data.get("Username"), str) and type(data.get("Tile")) is int:
            settlements[data["Username"]].add(data["Tile"])
    players = []
    for file in (game / "Assets/Users").glob("*.json"):
        username = safe_read(file).get("Username")
        if not isinstance(username, str) or not username or username != file.stem:
            continue
        login = safe_read(login_directory / f"{hashlib.sha256(username.encode()).hexdigest()}.json")
        save = game / "Assets/Saves" / file.name
        tiles = tuple(sorted(settlements[username]))
        name = count = last_save = None
        try:
            if not save.is_symlink():
                stat = save.stat()
                last_save = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                name, count = summary(save, stat.st_mtime_ns, stat.st_size, tiles)
        except FileNotFoundError:
            pass
        players.append((username, list(tiles), login.get("at"), last_save, name, count))
    return players


def read_streams(epoch, offsets, cutoff):
    if not IDENTIFIER.fullmatch(epoch):
        return []
    entries = []
    first_day = cutoff.date().isoformat()
    for path in sorted((SPOOL / epoch).glob("*.jsonl")):
        match = STREAM.fullmatch(path.name)
        if not match or path.name[:10] < first_day:
            continue
        stream_name = f"{epoch}/{path.name}"
        try:
            with open_game_file(path) as source:
                source.seek(offsets.get(stream_name, 0))
                while line := source.readline():
                    if not line.endswith(b"\n"):
                        break
                    try:
                        item = json.loads(line)
                        timestamp = datetime.fromisoformat(item["at"])
                        if timestamp >= cutoff:
                            entries.append((epoch, match[1], stream_name, source.tell(), timestamp,
                                            item["category"], item["line"].replace("\x00", "")))
                    except (KeyError, TypeError, ValueError):
                        LOG.warning("Skipping an invalid game log record in %s", stream_name)
                    if len(entries) >= 2000:
                        return entries
        except (FileNotFoundError, ValueError):
            continue  # The supervisor may have expired the stream.
    return entries


async def synchronize(pool):
    boot, pending, status = current_state()
    if pending and pending.get("kind") == "factory-reset":
        return
    settings = None
    if status == "ready":
        try:
            settings = await asyncio.to_thread(read_settings, GAME)
        except (OSError, ValueError):
            LOG.warning("RimWorld settings are temporarily unreadable")
    players = await asyncio.to_thread(read_players, GAME, boot.get("world_reset_id")) if status == "ready" else []
    cutoff = now() - timedelta(days=7)
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            reset_id = boot.get("world_reset_id")
            if settings and reset_id:
                await cur.execute("SELECT world_reset_id FROM world_config FOR UPDATE")
                stored = await cur.fetchone()
                if not stored or not stored["world_reset_id"] or stored["world_reset_id"].hex != reset_id:
                    # Same transaction as the replacement snapshot. Dashboard
                    # authentication tables are outside the game data lifecycle.
                    await cur.execute("""
                        DELETE FROM player_data;
                        DELETE FROM player_online_sample;
                        DELETE FROM worker_sample;
                        DELETE FROM server_log;
                        DELETE FROM world_config;
                        """)
            if settings:
                await cur.execute("""
                    INSERT INTO world_config (revision, settings, world_initialized, boot_id, world_reset_id) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (singleton) DO UPDATE SET revision = EXCLUDED.revision,
                        settings = EXCLUDED.settings, world_initialized = EXCLUDED.world_initialized,
                        boot_id = EXCLUDED.boot_id, world_reset_id = EXCLUDED.world_reset_id, updated_at = now()
                    WHERE (world_config.revision, world_config.boot_id)
                    IS DISTINCT FROM (EXCLUDED.revision, EXCLUDED.boot_id)
                    """, (revision(settings), Jsonb(settings), WORLD in settings, boot["id"], reset_id))
            if players:
                await cur.executemany("""
                    INSERT INTO player_data (username, settlement_tiles, last_login, last_save, colony_name, colonist_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (username) DO UPDATE SET settlement_tiles = EXCLUDED.settlement_tiles,
                        last_login = GREATEST(player_data.last_login, EXCLUDED.last_login),
                        last_save = EXCLUDED.last_save, colony_name = EXCLUDED.colony_name,
                        colonist_count = EXCLUDED.colonist_count, updated_at = now()
                    WHERE (player_data.settlement_tiles, player_data.last_login, player_data.last_save,
                        player_data.colony_name, player_data.colonist_count)
                    IS DISTINCT FROM (EXCLUDED.settlement_tiles,
                        GREATEST(player_data.last_login, EXCLUDED.last_login), EXCLUDED.last_save,
                        EXCLUDED.colony_name, EXCLUDED.colonist_count)
                    """, players)
            if epoch := boot.get("epoch"):
                await cur.execute("SELECT stream, max(byte_offset) AS position FROM server_log WHERE epoch = %s GROUP BY stream", (epoch,))
                offsets = {row["stream"]: row["position"] for row in await cur.fetchall()}
                entries = await asyncio.to_thread(read_streams, epoch, offsets, cutoff)
                # A boot may have occurred while the old files were being read.
                if (read_json(BOOT) or {}).get("epoch") == epoch:
                    if entries:
                        await cur.executemany("""
                            INSERT INTO server_log (epoch, boot_id, stream, byte_offset, occurred_at, category, description)
                            VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (stream, byte_offset) DO NOTHING
                            """, entries)
                    await cur.execute("DELETE FROM server_log WHERE epoch <> %s OR occurred_at < %s", (epoch, cutoff))
            else:
                await cur.execute("DELETE FROM server_log WHERE occurred_at < %s", (cutoff,))
            current_boot, _, current_status = current_state()
            if current_boot.get("id") == boot.get("id"):
                observed_at = now()
                await sample_online(cur, current_boot, current_status, observed_at)
                await sample_resources(cur, current_boot, current_status, observed_at)


async def follow(pool):
    while True:
        try:
            await synchronize(pool)
        except Exception:
            LOG.exception("Unable to synchronize RimWorld data, retrying")
        await asyncio.sleep(3)
