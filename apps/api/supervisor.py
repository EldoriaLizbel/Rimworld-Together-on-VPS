"""Run the official game binary and mirror its Docker output for the app server."""
import json
import hashlib
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

from rwt_files import (
    ANSI, BOOT, GAME_USERNAME, IDENTIFIER, LOGINS, LOGIN_LINE, LOG_PREFIX, REQUEST, SPOOL, STAGED, WORLD,
    apply_password, now, prepare_password, prepare_updates, read_json, read_settings, restore_factory_defaults,
    revision, write_json, write_settings_batch,
)

GAME = Path("/Data")
READY = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \| Listening for users at (.+):(\d+)$")
VERSION = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \| Server version (\S+)")
stop = threading.Event()


def listening(port):
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        for line in table.read_text().splitlines()[1:] if table.exists() else ():
            columns = line.split()
            if columns[3] == "0A" and int(columns[1].rsplit(":", 1)[1], 16) == port:
                return True
    return False


class GameLog:
    def __init__(self, state):
        self.directory = SPOOL / state["epoch"]
        self.directory.mkdir(parents=True, exist_ok=True)
        self.boot_id = state["id"]
        self.version = None
        self.port = None
        self.reset_player = None

    def record(self, line, management=False):
        print(line, flush=True)
        text = ANSI.sub("", line).strip()
        if not text:
            return
        timestamp = now()
        file = self.directory / f"{timestamp.date()}_{self.boot_id}.jsonl"
        message = LOG_PREFIX.sub("", text)
        level = "warning" if "\x1b[33m" in line else ("error" if "\x1b[31m" in line else "info")
        category = "management" if management else level
        entry = {"at": timestamp.isoformat(), "line": message[:16384], "category": category}
        with file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\n")
        if match := LOGIN_LINE.match(message):
            username = match[1]
            digest = hashlib.sha256(username.encode()).hexdigest()
            LOGINS.mkdir(exist_ok=True)
            write_json(LOGINS / f"{digest}.json", {"username": username, "at": entry["at"]})
        if message.startswith("[Reset player] > "):
            self.reset_player = message.removeprefix("[Reset player] > ")
        if match := VERSION.match(text):
            self.version = match[1]
        if match := READY.match(text):
            self.port = int(match[2])

    def capture(self, stdout):
        for line in stdout:
            self.record(line.rstrip("\r\n"))

    def prune(self, directory_only=False):
        cutoff = (now() - timedelta(days=7)).date().isoformat()
        for directory in SPOOL.iterdir():
            if not directory.is_dir() or not IDENTIFIER.fullmatch(directory.name):
                continue
            if directory != self.directory or not directory_only:
                for file in directory.glob("*.jsonl"):
                    if directory != self.directory or file.name[:10] < cutoff:
                        file.unlink(missing_ok=True)
            if directory != self.directory and not any(directory.iterdir()):
                directory.rmdir()


def initialize():
    previous = read_json(BOOT) or {}
    server_config = GAME / "Configs/ServerConfig.json"
    if not server_config.exists() and not server_config.is_symlink():
        server_config.parent.mkdir(exist_ok=True)
        write_json(server_config, {"EnableServerBrowser": False, "EnableServerTelemetry": False})
    request = read_json(REQUEST)
    old_result = previous.get("operation")
    result = old_result
    changed = False
    if request and (not old_result or request["id"] != old_result["id"]):
        result = {"id": request["id"], "status": "applied", "kind": request["kind"]}
        try:
            if request["base_boot"] != previous.get("id"):
                raise ValueError("The server boot changed before the request could be handled")
            if request["kind"] == "configuration":
                documents = prepare_updates(GAME, request["changes"])
                if "digest" in request:
                    path, document = prepare_password(GAME, request["digest"])
                    documents[path] = document
                write_settings_batch(documents)
                if request.get("staged_id") and (read_json(STAGED) or {}).get("id") == request["staged_id"]:
                    STAGED.unlink(missing_ok=True)
                changed = True
            elif request["kind"] == "password":
                apply_password(GAME, request["digest"])
                changed = True
            elif request["kind"] == "factory-reset":
                if (read_json(STAGED) or {}).get("id") != request.get("staged_id"):
                    raise ValueError("The staged configuration changed before reset")
                restore_factory_defaults(GAME)
                STAGED.unlink(missing_ok=True)
                changed = True
            elif request["kind"] != "restart":
                raise ValueError("Unsupported management operation")
        except (OSError, ValueError, KeyError, TypeError):
            result["status"] = "rejected"
            result["message"] = "The active settings did not match the queued operation"

    try:
        settings = read_settings(GAME)
    except (OSError, ValueError):
        settings = None  # Let the official server handle its own invalid files.
    world_exists = (GAME / WORLD).is_file()
    fingerprint = revision(settings) if settings else None
    if fingerprint and previous.get("fingerprint") and previous["world_initialized"] == world_exists:
        changed = changed or previous["fingerprint"] != fingerprint
    boot_id = uuid.uuid4().hex
    state = {
        "id": boot_id, "epoch": boot_id if changed else previous.get("epoch", boot_id),
        "status": "starting", "started_at": now().isoformat(),
        "operation": result, "world_initialized": world_exists,
        "fingerprint": fingerprint,
    }
    write_json(BOOT, state)
    if request:
        REQUEST.unlink(missing_ok=True)
    return state


def run():
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    state = initialize()
    output = GameLog(state)
    output.prune(directory_only=True)
    output.record("Starting RimWorld Together", management=True)
    if operation := state["operation"]:
        output.record(f"Management operation {operation['kind']} {operation['status']} ({operation['id']})", management=True)
    process = subprocess.Popen(
        ["/App/Server/RTServer"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
    )
    reader = threading.Thread(target=output.capture, args=(process.stdout,), daemon=True)
    reader.start()
    next_prune = 0
    last_refresh = 0
    requested = False
    active_reset = None
    while process.poll() is None and not stop.is_set():
        request = read_json(REQUEST)
        tick = time.monotonic()
        if request and request["base_boot"] == state["id"]:
            if request["kind"] != "player-reset":
                output.record("Restart requested by the server dashboard", management=True)
                requested = True
                break
            username = request.get("username", "")
            if active_reset is None and GAME_USERNAME.fullmatch(username):
                output.reset_player = None
                try:
                    process.stdin.write(f"resetplayer {username}\n")
                    process.stdin.flush()
                    active_reset = tick + 30
                except OSError:
                    active_reset = tick
            applied = output.reset_player == username and bool(username)
            if applied or active_reset is None or tick >= active_reset:
                result = {"id": request["id"], "kind": "player-reset", "status": "applied" if applied else "rejected"}
                if not applied:
                    result["message"] = "The game did not confirm the reset. Check Server log before retrying."
                state["operation"] = result
                write_json(BOOT, state)
                REQUEST.unlink(missing_ok=True)
                active_reset = None
        if tick >= last_refresh + 2:
            status = "ready" if output.port and listening(output.port) else "starting"
            if status == "ready" and (state["status"] != "ready" or not state["world_initialized"] and (GAME / WORLD).exists()):
                try:
                    settings = read_settings(GAME)
                    state["world_initialized"] = WORLD in settings
                    state["fingerprint"] = revision(settings)
                except (ValueError, OSError):
                    pass  # A game-side write may be in progress.
            state.update(status=status, heartbeat_at=now().isoformat(), version=output.version, port=output.port)
            write_json(BOOT, state)
            last_refresh = tick
        if tick >= next_prune:
            output.prune()
            next_prune = tick + 3600
        stop.wait(0.25)

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    reader.join(timeout=3)
    state.update(status="restarting" if requested else ("stopped" if stop.is_set() else "failed"))
    write_json(BOOT, state)
    output.record(f"Game process exited with {process.returncode}", management=True)
    return 0 if stop.is_set() else 1


if __name__ == "__main__":
    sys.exit(run())
