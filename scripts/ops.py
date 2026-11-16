#!/usr/bin/env python3
"""Single-host deployment and recovery. No application container needs the Docker socket."""
import argparse
import contextlib
import datetime as dt
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess as sp
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid

import db
import safe_backup as backups

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "EldoriaLizbel/Rimworld-Together-on-VPS"
REGISTRY = f"ghcr.io/{REPOSITORY.lower()}"
GAME_VERSION = "26.8.31.1"
SERVICES = ("api", "web", "beekeeper", "rimworld")
SCOPES = ("all", "app", *SERVICES)
SHA = re.compile(r"[0-9a-f]{40}")
PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
REF = re.compile(r"(?:ghcr\.io/[a-z0-9/_-]+@sha256:[a-f0-9]{64}|rwt-local/[a-z0-9_-]+:[a-f0-9]{64})")
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}")
KEY = re.compile(r"[A-Z][A-Z0-9_]*")
PSQL = 'exec psql -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
DEPLOY_ID = None


def timestamp():
    return dt.datetime.now(dt.timezone.utc)


def say(message):
    print(f"[{timestamp().isoformat(timespec='seconds')}] {message}", flush=True)


def abort(message):
    raise ValueError(message)


def run(*args, body=None, stdin=None, capture=False, file=None, quiet=False, allowed=False, timeout=120, env=None):
    # Explicit labels at call sites are safe to print; never dump argv/env or container errors by default.
    result = sp.run(args, cwd=ROOT, input=body, stdin=stdin, stdout=sp.PIPE if capture else file,
                    stderr=sp.DEVNULL if quiet else None, timeout=timeout, env=env)
    if result.returncode and not allowed:
        abort(f"{args[0]} operation failed (exit {result.returncode}); see the preceding step and service logs")
    return result


def plain_env(path):
    if not backups.regular(path):
        abort(f"Missing or unsafe {path.name}")
    variables = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not KEY.fullmatch(key) or key in variables or any(ord(c) < 32 for c in value):
            abort(f"Invalid or duplicate setting in {path.name}")
        variables[key] = value
    return variables


def json_file(path, default=None):
    if not path.exists() and not path.is_symlink():
        return default
    if not backups.regular(path):
        abort(f"Unsafe state file: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def store(path, document):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", delete=False) as handle:
        name = Path(handle.name)
        try:
            json.dump(document, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            name.unlink(missing_ok=True)
            raise
    try:
        os.replace(name, path)
    finally:
        name.unlink(missing_ok=True)


@contextlib.contextmanager
def lock(folder):
    path = folder / "operation.lock"
    if path.is_symlink():
        abort("Unsafe deployment lock path")
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                abort("Another deployment, backup, migration or restore holds the lock")
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                abort("Another deployment, backup, migration or restore holds the lock")
        yield  # Lock is released by closing the descriptor, also after an abrupt exit.


def port(value):
    if not re.fullmatch(r"[0-9]{1,5}", str(value)) or not 1 <= int(value) <= 65535:
        abort("An invalid TCP port was configured")
    return int(value)


def state_path(path):
    path = Path(path).absolute()
    if not path.is_dir() or path.is_symlink() or path.resolve() != path:
        abort("Deployment state must be an existing directory without symlinks")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        abort("Deployment state must be private (chmod 700)")
    return path


def read_manifest(version):
    if not SHA.fullmatch(version):
        abort("Release must be a full lowercase 40-character commit SHA")
    url = f"https://github.com/{REPOSITORY}/releases/download/release-{version}/release.json"
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        abort("Release manifest exceeds size limit")
    return manifest(json.loads(raw), version)


def manifest(data, version):
    if (data.get("format") != 1 or data.get("commit") != version or not SHA.fullmatch(version)
            or data.get("platform") != "linux/amd64" or data.get("game") != GAME_VERSION):
        abort("Release commit, platform or upstream game version is incompatible")
    images = data["images"]
    if set(images) != set(SERVICES) or not all(
        re.fullmatch(rf"{REGISTRY}-{service}@sha256:[a-f0-9]{{64}}", images[service]) for service in SERVICES
    ):
        abort("Release does not contain the expected immutable application images")
    low, high = data["schema"]
    if type(low) is not int or type(high) is not int or not 1 <= low <= high:
        abort("Invalid release schema compatibility bounds")
    return data


class Stack:
    def __init__(self, folder, validate_paths=True):
        self.folder = state_path(folder)
        self.envfile = self.folder / "compose.env"
        cfg = self.settings = plain_env(self.envfile)
        self.project = cfg.get("COMPOSE_PROJECT_NAME", "")
        if not PROJECT.fullmatch(self.project):
            abort("Invalid Compose project name")
        self.game = self.folder / "game"
        self.tools = cfg.get("RWT_BEEKEEPER_ENABLED", "1") == "1"
        if cfg.get("RWT_BEEKEEPER_ENABLED", "1") not in ("0", "1"):
            abort("RWT_BEEKEEPER_ENABLED must be 0 or 1")
        self.ports = {
            "rimworld": ("RIMWORLD_HOST_BIND", "RIMWORLD_HOST_PORT", "0.0.0.0", 25555),
            "web": ("RIMWORLD_WEB_BIND", "RIMWORLD_WEB_PORT", "127.0.0.1", 10005),
            **({"beekeeper": ("", "BEEKEEPER_WEB_PORT", "127.0.0.1", 5800)} if self.tools else {}),
        }
        ports = set()
        for bind_key, port_key, default_bind, default_port in self.ports.values():
            try:
                ipaddress.IPv4Address(cfg.get(bind_key, default_bind))
            except ipaddress.AddressValueError:
                abort(f"{bind_key} must be an IPv4 address")
            number = port(cfg.get(port_key, default_port))
            if number in ports:
                abort("Choose distinct published ports")
            ports.add(number)
        if not re.fullmatch(r"[A-Za-z0-9.:-]{0,253}", cfg.get("RIMWORLD_PUBLIC_HOST", "")):
            abort("Invalid public game address")
        for key in ("RIMWORLD_API_TOKEN", "RIMWORLD_API_DB_PASSWORD"):
            if not cfg.get(key):
                abort(f"Missing required {key}")
        if validate_paths:
            for key, expected in (
                ("RWT_GAME_DATA", self.game), ("RWT_WEB_ENV_FILE", self.folder / "web.env"),
                ("RWT_POSTGRES_ENV_FILE", self.folder / "postgres.env"),
            ):
                configured = ROOT / cfg.get(key, "")
                if configured.resolve() != expected or expected.is_symlink():
                    abort(f"{key} must point inside the selected deployment directory")
        web = plain_env(self.folder / "web.env")
        pg = plain_env(self.folder / "postgres.env")
        if not pg.get("POSTGRES_PASSWORD") or not pg.get("RIMWORLD_WEB_DB_PASSWORD") or not pg.get("RIMWORLD_ADMIN_PASSWORD"):
            abort("postgres.env is missing required settings")
        if not pg.get("POSTGRES_USER") or not pg.get("POSTGRES_DB"):
            abort("postgres.env must specify POSTGRES_USER and POSTGRES_DB")
        if cfg.get("RIMWORLD_API_DB_NAME", "app_db") != pg["POSTGRES_DB"]:
            abort("API and postgres.env disagree on the application database")
        if len(web.get("SESSION_SECRET", "")) < 32 or not web.get("DATABASE_URL"):
            abort("web.env must contain DATABASE_URL and a session secret of at least 32 characters")
        if web.get("COOKIE_SECURE", "false") not in ("true", "false"):
            abort("COOKIE_SECURE must be true or false")
        if os.name != "nt":
            for name in backups.ENV_FILES:
                if (self.folder / name).stat().st_mode & 0o077:
                    abort(f"Restrict {name} to owner access (chmod 600)")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("RWT_", "RIMWORLD_", "COMPOSE_"))
                    and k not in cfg and k not in ("TZ", "BEEKEEPER_WEB_PORT", "POSTGRES_VERSION")}
        self.docker = ("docker",)
        if run(*self.docker, "info", capture=True, quiet=True, allowed=True, env=self.env).returncode:
            self.docker = ("sudo", "-n", "docker")
            if run(*self.docker, "info", capture=True, quiet=True, allowed=True, env=self.env).returncode:
                abort("Docker daemon unavailable; check the service or local user access")

    @property
    def path(self):
        return self.folder / "release-state.json"

    def state(self):
        return json_file(self.path, {"active": {}, "previous": {}})

    def command(self, *args, **kwargs):
        return run(*self.docker, *args, env=self.env, **kwargs)

    def compose(self, *args, refs=None, no_init=False, **kwargs):
        base = ("compose", "--ansi", "never", "--env-file", str(self.envfile),
                "-p", self.project, "-f", str(ROOT / "compose.yaml"))
        if not refs and not no_init and self.tools:
            return self.command(*base, *args, **kwargs)
        # Compose needs its stdin for psql/Node reads, so put the non-secret overlay
        # in a private temporary file, never in tracked source.
        with tempfile.TemporaryDirectory(prefix="rwt-compose-") as tmp:
            file = Path(tmp) / "overlay.yaml"
            overlay = ["services:"]
            by_service = {key: ["build: !reset null", f"image: {ref}"] for key, ref in (refs or {}).items()}
            if not self.tools:
                by_service.setdefault("beekeeper", []).append("profiles: [tools]")
            if no_init:
                overlay += ["  postgres:", "    volumes: !override",
                            "      - postgres_data:/var/lib/postgresql/data"]
            for key, lines in by_service.items():
                if key not in SERVICES or any(
                    line.startswith("image: ") and not REF.fullmatch(line[7:]) for line in lines
                ):
                    abort("Invalid image reference in Compose overlay")
                overlay.append(f"  {key}:")
                overlay.extend("    " + line for line in lines)
            file.write_text("\n".join(overlay) + "\n", encoding="utf-8")
            return self.command(*base, "-f", str(file), *args, **kwargs)

    def sql(self, source, quiet=False):
        return self.compose("exec", "-T", "postgres", "sh", "-c", PSQL, body=source.encode("utf-8"),
                            capture=True, quiet=quiet).stdout.decode("utf-8").strip()

    def schema(self, mode, accepted=None):
        result = self.sql(db.script(mode, accepted))
        return [line for line in result.splitlines() if re.match(r"^(applied|pending|baseline|verified) ", line)]

    def containers(self, service):
        result = self.compose("ps", "-a", "-q", service, capture=True, quiet=True).stdout.decode().split()
        if len(result) > 1:
            abort(f"Expected only one {service} container")
        if not result:
            return None
        return json.loads(self.command("inspect", result[0], capture=True).stdout)[0]

    def image_id(self, ref, optional=False):
        result = self.command("image", "inspect", "--format", "{{.Id}}", ref,
                              capture=True, quiet=True, allowed=optional)
        return result.stdout.decode().strip() if result.returncode == 0 else None

    def pg_ready(self):
        row = self.containers("postgres")
        return row and row["State"].get("Health", {}).get("Status") == "healthy"

    def preflight(self, scope=SERVICES, require_pg=False, refs=None):
        if self.command("info", "--format", "{{.OSType}}/{{.Architecture}}", capture=True).stdout.decode().strip() not in (
            "linux/x86_64", "linux/amd64"
        ):
            abort("RimWorld Together requires a Linux x86-64 Docker engine")
        v = self.command("compose", "version", "--short", capture=True).stdout.decode()
        found = re.search(r"(\d+)\.(\d+)\.(\d+)", v)
        if not found or tuple(map(int, found.groups())) < (2, 24, 4):
            abort("Docker Compose 2.24.4 or newer is required")
        if not platform.system() == "Linux":
            say("Warning: non-Linux host; Docker daemon validation is separate")
        elif Path("/etc/os-release").is_file() and 'VERSION_ID="22.04"' not in Path("/etc/os-release").read_text():
            say("Warning: Ubuntu Server 22.04 is the deployment target")
        model = json.loads(self.compose("config", "--format", "json", refs=refs, capture=True, quiet=True).stdout)
        for key in ("api", "postgres"):
            if model["services"][key].get("ports") or model["services"][key].get("network_mode") == "host":
                abort(f"Unexpected public exposure for {key}")
        pg = model["services"]["postgres"]
        if not re.fullmatch(r"postgres:16(?:[.-][\w.-]+)?(?:@sha256:[0-9a-f]{64})?", pg["image"]):
            abort("This checkout supports PostgreSQL major version 16")
        volume = next((v for v in pg["volumes"] if v["target"] == "/var/lib/postgresql/data"), None)
        if not volume or volume["type"] != "volume" or volume["source"] != "postgres_data":
            abort("PostgreSQL must use the project data volume")
        container = self.containers("postgres")
        if container:
            target = next((v for v in container["Mounts"] if v["Destination"] == "/var/lib/postgresql/data"), {})
            if target.get("Name") != model["volumes"]["postgres_data"]["name"]:
                abort("Running Postgres belongs to a different persistence volume")
        elif require_pg:
            abort("Start the existing PostgreSQL project before this operation")
        if not self.game.is_dir() or not os.access(self.game, os.R_OK | os.W_OK):
            abort("Game data directory is not readable/writable by the deployment user")
        disk = shutil.disk_usage(self.folder)
        if disk.free < 1 * 1024**3:
            abort("At least 1 GiB free disk is required to start a deployment")
        say(f"Deployment disk: {disk.free // 1024**2} MiB free")
        host = model["services"]["web"]["ports"][0].get("host_ip")
        if host != "127.0.0.1":
            say("Warning: dashboard exposed outside loopback. Public HTTP is unencrypted; use a trusted HTTPS proxy or SSH tunnel.")
        for service, (bind_key, port_key, default_bind, default_port) in self.ports.items():
            if service not in scope:
                continue
            bind = self.settings.get(bind_key, default_bind)
            number = port(self.settings.get(port_key, default_port))
            existing = self.containers(service)
            mapping = (existing or {}).get("NetworkSettings", {}).get("Ports") or {}
            if any(p["HostPort"] == str(number) for entries in mapping.values() if entries for p in entries):
                if not any(p["HostPort"] == str(number) and p["HostIp"] == bind
                           for entries in mapping.values() if entries for p in entries):
                    say(f"{service} already owns port {number}; bind address will change on recreation")
                continue
            with socket.socket() as probe:
                try:
                    probe.bind((bind, number))
                except OSError:
                    abort(f"{service} cannot bind {bind}:{number}; check for a conflicting process or an unassigned IP")
        engine_ram = self.command("info", "--format", "{{.MemTotal}}", capture=True).stdout.decode().strip()
        if engine_ram.isdecimal() and int(engine_ram) < 4 * 1024**3:
            say("Warning: Docker engine has less than 4 GiB RAM available in total")
        meminfo = Path("/proc/meminfo")
        if meminfo.is_file():
            available = re.search(r"^MemAvailable:\s+(\d+)", meminfo.read_text(), re.M)
            if available and int(available[1]) < 1024**2:
                say("Warning: Linux currently reports less than 1 GiB available RAM")
        for service, ref in (refs or {}).items():
            if not self.image_id(ref, optional=True):
                say(f"{service}: digest not cached; authenticated registry pull will be checked before any service stop")
        backup_root(self, create=False)
        say(f"Preflight passed for {self.project}")

    def smoke(self, services=SERVICES):
        if not self.pg_ready():
            abort("PostgreSQL readiness failed")
        self.sql("SELECT 1; SELECT username FROM public.user_profile LIMIT 1; "
                 "SELECT revision FROM public.world_config LIMIT 1; SELECT sampled_at FROM public.worker_sample LIMIT 1;")
        check = {"web", "api", "rimworld"} if "rimworld" in services else set(services) & {"web", "api"}
        unready = set(services) | check
        deadline = time.monotonic() + 25
        while unready:
            for service in unready.copy():
                container = self.containers(service)
                if container and container["State"].get("Health", {}).get("Status") == "healthy":
                    unready.remove(service)
            if unready:
                if time.monotonic() >= deadline:
                    abort(f"Service health failed: {', '.join(sorted(unready))}")
                time.sleep(2)
        if "web" in check:
            web_checks = (ROOT / "scripts/smoke-web.cjs").read_bytes()
            self.compose("exec", "-T", "web", "node", "-", body=web_checks)
        if "rimworld" in services:
            source = (ROOT / "scripts/smoke-game.py").read_bytes()
            self.compose("exec", "-T", "api", "python", "-", body=source)
        say("Smoke passed. External firewall/NAT and a real RimWorld client join were not tested.")

    def append_event(self, status, **details):
        event = {"time": timestamp().isoformat(), "id": DEPLOY_ID, "status": status, **details}
        with (self.folder / "deployments.jsonl").open("a", encoding="utf-8") as output:
            print(json.dumps(event), file=output, flush=True)
        say(f"Deployment {DEPLOY_ID}: {status}")


def backup_root(stack, create=True):
    loc = Path(stack.settings.get("RWT_BACKUP_DIR", str(stack.folder / "backups")))
    loc = (ROOT / loc).absolute()
    if loc.resolve() != loc or loc == stack.folder or loc == stack.game or stack.game in loc.parents or loc in stack.folder.parents:
        abort("Backup directory must be separate from active game data and cannot use symlinks")
    git_ignored = (ROOT / ".rwt-deploy", ROOT / "rwt-backups")
    if loc == ROOT or (ROOT in loc.parents and not any(loc == path or path in loc.parents for path in git_ignored)):
        abort("Store backups outside the checkout or under its ignored deployment/backup directory")
    if create:
        loc.mkdir(parents=True, exist_ok=True, mode=0o700)
    if loc.exists():
        if not loc.is_dir() or not os.access(loc, os.W_OK):
            abort("Backup directory must be writable")
        if os.name != "nt" and loc.stat().st_mode & 0o077:
            abort("Backup directory must be private (chmod 700)")
    else:
        parent = next(path for path in loc.parents if path.is_dir())
        if not os.access(parent, os.W_OK):
            abort("Backup directory cannot be created by this user")
    return loc


def retention(stack, root, latest):
    def positive(key, default):
        value = stack.settings.get(key, str(default))
        if not re.fullmatch(r"[0-9]{1,7}", value) or int(value) < 1:
            abort(f"Invalid {key} value")
        return int(value)

    count = positive("RWT_BACKUP_MAX_COUNT", 14)
    minimum = positive("RWT_BACKUP_MIN_KEEP", 3)
    age = positive("RWT_BACKUP_MAX_DAYS", 30)
    if minimum > count:
        abort("RWT_BACKUP_MIN_KEEP exceeds RWT_BACKUP_MAX_COUNT")
    if latest is None:
        return
    # Retain at least the minimum of each backup type. Never discard the last
    # full backup just because newer database-only snapshots exist.
    known = {"db": [], "full": []}
    for path in sorted(root.iterdir(), reverse=True):
        if not backups.BACKUP_ID.fullmatch(path.name) or path.is_symlink():
            continue
        try:
            metadata = json_file(path / "manifest.json", {})
            if metadata.get("id") == path.name and metadata.get("verification") == "passed":
                known[metadata["scope"]].append((path, dt.datetime.fromisoformat(metadata["created_at"])))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    for items in known.values():
        verified = 0
        for index, (path, date) in enumerate(items):
            if verified < minimum:
                try:
                    if path.name != latest:
                        backups.verify(root, path.name)
                    verified += 1
                except (OSError, ValueError, KeyError, TypeError):
                    say(f"Warning: previous backup {path.name} did not verify; preserving older copies")
                continue
            if path.name != latest and (index >= count or timestamp() - date > dt.timedelta(days=age)):
                if all(not item.is_symlink() and item.is_file() and item.name in backups.contents("full") | {"manifest.json"}
                       for item in path.iterdir()):
                    say(f"Expiring verified backup {path.name} under the configured retention policy")
                    for item in path.iterdir():
                        item.unlink()
                    path.rmdir()


def capture_backup(stack, scope, keep_game_stopped=False):
    root = backup_root(stack)
    retention(stack, root, None)
    if not stack.pg_ready():
        abort("PostgreSQL is not ready for backup")
    schema = stack.schema("status")
    applied = [int(line.split()[1]) for line in schema if line.startswith("applied ")]
    identity = timestamp().strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    game = stack.containers("rimworld") if scope == "full" else None
    api = stack.containers("api") if game else None
    if scope == "full" and not game:
        abort("Cannot take a full backup before the game has been installed")
    db_bytes = int(stack.sql("SELECT pg_database_size(current_database());"))
    needed = db_bytes
    if game:
        game_bytes = stack.command("run", "--rm", "--network", "none", "--volumes-from", game["Id"] + ":ro",
                                   "--entrypoint", "du", game["Image"], "-sk", "/Data", "/bridge",
                                   capture=True).stdout.decode().splitlines()
        needed += sum(int(line.split()[0]) * 1024 for line in game_bytes)
    if shutil.disk_usage(root).free < needed + (128 << 20):
        abort("Insufficient free disk for backup")
    say(f"Creating {scope} backup {identity}")
    stopped = []
    sealed = False
    with tempfile.TemporaryDirectory(prefix=".incomplete-", dir=root) as stage_name:
        stage = Path(stage_name)
        try:
            for service, container in (("api", api), ("rimworld", game)):
                if container and container["State"]["Running"]:
                    stopped.append(service)
                    stack.compose("stop", service)
            if game:
                stopped_game = stack.containers("rimworld")
                if stopped_game["State"]["Running"] or stopped_game["State"]["ExitCode"] == 137:
                    abort("Game did not stop cleanly; a consistent backup cannot be asserted")
                stack.command("run", "--rm", "--network", "none", "--volumes-from", game["Id"] + ":ro",
                              "--entrypoint", "sh", game["Image"], "-c", "test ! -e /bridge/request.json")
                for archive, directory in (("game.tar", "/Data"), ("bridge.tar", "/bridge")):
                    with (stage / archive).open("wb") as target:
                        stack.command("run", "--rm", "--network", "none", "--volumes-from", game["Id"] + ":ro",
                                      "--entrypoint", "tar", game["Image"], "-C", directory, "--exclude=./staged-config.json",
                                      "-cf", "-", ".", file=target, timeout=3600)
                    backups.unpack(stage / archive)
            with (stage / "database.dump").open("wb") as target:
                stack.compose("exec", "-T", "postgres", "sh", "-ec",
                              'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
                              file=target, timeout=3600)
            if (stage / "database.dump").stat().st_size == 0:
                abort("PostgreSQL returned an empty database dump")
            with (stage / "database.dump").open("rb") as dump:
                result = sp.run((*stack.docker, "compose", "--env-file", str(stack.envfile), "-p", stack.project,
                                 "exec", "-T", "postgres", "pg_restore", "--list"),
                                cwd=ROOT, env=stack.env, stdin=dump, stdout=sp.DEVNULL, timeout=120)
                if result.returncode:
                    abort("pg_restore could not read the new backup")
            for name in backups.ENV_FILES:
                shutil.copyfile(stack.folder / name, stage / name)
            store(stage / "release.json", stack.state())
            backups.seal(stage, identity, scope, game_version=GAME_VERSION, schema=max(applied, default=0),
                         postgres_major=int(stack.sql("SHOW server_version_num;")) // 10000,
                         release={key: data["version"] for key, data in stack.state()["active"].items()})
            stage.rename(root / identity)
            sealed = True
        finally:
            for service in reversed(stopped):
                if service != "rimworld" or not (sealed and keep_game_stopped):
                    stack.compose("start", service, timeout=180)
    retention(stack, root, identity)
    say(f"Backup verified: {identity} ({root})")
    return identity

def scopes(stack, requested):
    selected = [service for service in SERVICES if requested in ("all", service)
                or requested == "app" and service in ("api", "web")]
    if not stack.tools and "beekeeper" in selected:
        if requested == "beekeeper":
            abort("Enable Beekeeper in compose.env before deploying it")
        selected.remove("beekeeper")
    return selected


def pin(stack, service, image):
    if not IMAGE_ID.fullmatch(image):
        abort("Invalid local image ID")
    ref = f"rwt-local/{stack.project}-{service}:{image[7:]}"
    if not stack.image_id(ref, optional=True):
        stack.command("image", "tag", image, ref, quiet=True)
    return ref


def refs_from(records):
    return {key: item["ref"] for key, item in records.items()}


def apply_release(stack, request, local=False, target=None):
    global DEPLOY_ID
    chosen = scopes(stack, request.scope)
    if local:
        data = {"commit": "local", "schema": [len(db.migrations())] * 2, "images": {}}
    else:
        data = target or read_manifest(request.version)
    desired = {key: data["images"][key] for key in chosen if key in data["images"]}
    state = stack.state()
    stack.preflight(chosen, require_pg=request.scope != "all", refs=desired)
    database = stack.pg_ready()
    pending = []
    if database:
        if int(stack.sql("SHOW server_version_num;")) // 10000 != 16:
            abort("Existing PostgreSQL server major version is incompatible")
        pending = [line for line in stack.schema("status") if not line.startswith("applied ")]
    elif request.scope != "all":
        abort("PostgreSQL is not ready; run the full installation first")
    elif stack.containers("postgres") or stack.command(
        "volume", "inspect", stack.project + "_postgres_data", capture=True, quiet=True, allowed=True,
    ).returncode == 0:
        abort("Existing database is not healthy; start PostgreSQL and verify it before deploying")
    migrate = request.scope in ("all", "app", "api")
    if request.scope == "api" and not state["active"].get("web"):
        abort("Adopt the dashboard/API together with --scope app before using API-only updates")
    if request.scope == "web":
        api = stack.containers("api")
        if not api or not api["State"]["Running"] or stack.compose(
            "exec", "-T", "api", "python", "-c",
            "import json,sys; from urllib.request import urlopen; "
            "sys.exit(json.load(urlopen('http://127.0.0.1:8000/healthz', timeout=3)).get('contract') != 2)",
            quiet=True, capture=True, allowed=True,
        ).returncode:
            abort("Web requires a ready API contract 2. Upgrade Web and API together with --scope app first.")
    if not migrate and pending:
        abort("Database adoption or pending migrations must be completed before an isolated deployment")
    if migrate and not data["schema"][0] <= len(db.migrations()) <= data["schema"][1]:
        abort("Release schema is incompatible with this checkout; use the matching operations code")
    if database and migrate and pending and "web" not in chosen:
        active_web = state["active"].get("web")
        next_schema = len(db.migrations())
        if active_web and not active_web["schema"][0] <= next_schema <= active_web["schema"][1]:
            abort("The pending migration is incompatible with active web; deploy a compatible web and API together")
    if request.dry_run:
        hashes = service_hashes(stack, desired)
        changes = [key for key in chosen if local or needs_change(stack, key, desired[key], hashes[key], state)]
        say(f"Plan for {data['commit']}; services to change (or not cached): {', '.join(changes) or 'none'}")
        say(f"Migrations: {', '.join(pending) if pending else ('none' if database else 'initial schema')}")
        say("Backup plan: " + ("game/bridge/DB if replacing an existing game" if "rimworld" in changes else
                              "DB only if applying migrations or upgrading API" if "api" in changes or pending else "none"))
        say("Smoke plan: selected service health, database, and required internal HTTP/TCP checks")
        return
    DEPLOY_ID = uuid.uuid4().hex[:12]
    stack.append_event("started", release=data["commit"], scope=request.scope)
    changed = []
    completed = []
    backup_id = None
    original = {}
    resume_game = False
    try:
        if not local:
            for key, ref in desired.items():
                if not stack.image_id(ref, optional=True):
                    say(f"Pulling {key} by digest")
                    stack.command("pull", "--platform", "linux/amd64", ref, timeout=1200)
        else:
            say(f"Building {', '.join(chosen)}")
            stack.compose("build", *chosen, timeout=3600)
            for key in chosen:
                desired[key] = pin(stack, key, stack.image_id(f"{stack.project}-{key}"))
        hashes = service_hashes(stack, desired)
        changed = [key for key in chosen if needs_change(stack, key, desired[key], hashes[key], state)]
        if not changed and not pending and database:
            stack.schema("check", data["schema"])
            stack.smoke(chosen)
            if any(state["active"].get(key, {}).get("version") != data["commit"] for key in chosen):
                for key in chosen:
                    state["active"][key] = record(stack, key, desired[key], data, hashes[key])
                store(stack.path, state)
            stack.append_event("no-op", release=data["commit"])
            return
        game = stack.containers("rimworld")
        if game and "rimworld" in changed and not request.maintenance:
            abort("Replacing the game requires --maintenance. Deploy web/api separately to leave it running.")
        for key in changed:
            existing = stack.containers(key)
            tracked = state["active"].get(key)
            if existing and tracked and tracked["id"] == existing["Image"]:
                original[key] = dict(tracked)
        if game and "rimworld" in changed:
            resume_game = game["State"]["Running"]
            backup_id = capture_backup(stack, "full", keep_game_stopped=True)
            stack.append_event("backup-passed", backup=backup_id)
        elif database and (pending or ("api" in changed and stack.containers("api"))):
            backup_id = capture_backup(stack, "db")
            stack.append_event("backup-passed", backup=backup_id)
        if not database:
            stack.compose("up", "-d", "--no-recreate", "--wait", "--wait-timeout", "150", "postgres", timeout=180)
        if migrate:
            for line in stack.schema("apply"):
                say(f"Migration {line}")
            stack.append_event("migration-passed")
        stack.schema("check", data["schema"])
        for key in changed:
            completed.append(key)  # A failed Compose command may already have replaced the old container.
            say(f"Activating {key}")
            activate(stack, key, desired[key])
        stack.smoke(chosen)
        for key in chosen:
            prior = original.get(key)
            if prior and prior["id"] != stack.image_id(desired[key]):
                state["previous"][key] = prior
            state["active"][key] = record(stack, key, desired[key], data, hashes[key])
        store(stack.path, state)
        stack.append_event("succeeded", release=data["commit"], services=changed, backup=backup_id, health="passed")
    except (Exception, KeyboardInterrupt) as error:
        stack.append_event("failed", release=data["commit"], services=completed, backup=backup_id)
        try:
            restorable = [key for key in completed if key in original]
            if restorable:
                for key in restorable:
                    prepare_rollback(stack, original[key])
                for key in restorable:
                    activate(stack, key, original[key]["ref"])
                stack.smoke(restorable)
                for key in restorable:
                    cfg_hash = service_hashes(stack, {key: original[key]["ref"]})[key]
                    state["active"][key] = record(stack, key, original[key]["ref"],
                        {"commit": original[key]["version"], "schema": original[key]["schema"]}, cfg_hash)
                store(stack.path, state)
                stack.append_event("application-rollback-passed", services=restorable)
            if len(restorable) != len(completed):
                say("No verified prior release for some changed services; inspect service logs and the backup before recovery.")
        except (Exception, KeyboardInterrupt):
            stack.append_event("application-rollback-failed")
            say("Check release status and logs. The database was not rolled back.")
        if resume_game and "rimworld" not in completed:
            stack.compose("start", "rimworld", allowed=True)
        raise error


def service_hashes(stack, refs):
    model = json.loads(stack.compose("config", "--format", "json", refs=refs, capture=True, quiet=True).stdout)
    return {key: hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
            for key, config in model["services"].items()}


def needs_change(stack, service, ref, config_hash, state):
    item = stack.containers(service)
    target = stack.image_id(ref, optional=True)
    prior = state["active"].get(service, {})
    return (not item or not target or item["Image"] != target or
            item["Id"] != prior.get("container") or prior.get("config_hash") != config_hash or
            item["State"].get("Health", {}).get("Status") != "healthy")


def activate(stack, service, ref):
    stack.compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "--wait",
                  "--wait-timeout", "150", service, refs={service: ref}, timeout=180)
    running = stack.containers(service)
    if not running or running["Image"] != stack.image_id(ref):
        abort(f"Unexpected image activated for {service}")


def record(stack, service, ref, data, config_hash):
    return {"ref": ref, "id": stack.image_id(ref), "version": data["commit"], "config_hash": config_hash,
            "container": stack.containers(service)["Id"],
            "schema": data["schema"], "deployed_at": timestamp().isoformat()}


def prepare_rollback(stack, item):
    stack.schema("check", item["schema"])
    if not REF.fullmatch(item["ref"]) or not IMAGE_ID.fullmatch(item["id"]):
        abort("Invalid previous image record")
    if not stack.image_id(item["ref"], optional=True):
        if not item["ref"].startswith(REGISTRY + "-"):
            abort("Previous local image is missing; recover an exported image or choose a published release")
        stack.command("pull", "--platform", "linux/amd64", item["ref"], timeout=1200)
    if stack.image_id(item["ref"]) != item["id"]:
        abort("Previous image content does not match the recorded digest")


def rollback(stack, request):
    global DEPLOY_ID
    state = stack.state()
    selected = [key for key in scopes(stack, request.scope) if key in state["previous"]]
    if not selected:
        abort("No verified previous release is recorded for the requested scope")
    if "rimworld" in selected and not request.maintenance:
        abort("Restoring a previous game wrapper requires --maintenance")
    stack.preflight(selected, require_pg=True)
    DEPLOY_ID = uuid.uuid4().hex[:12]
    stack.append_event("rollback-started", services=selected)
    attempted = []
    was_running = False
    try:
        for key in selected:
            prepare_rollback(stack, state["previous"][key])
        if "rimworld" in selected:
            was_running = stack.containers("rimworld")["State"]["Running"]
            identity = capture_backup(stack, "full", keep_game_stopped=True)
            stack.append_event("backup-passed", backup=identity)
        for key in selected:
            attempted.append(key)
            activate(stack, key, state["previous"][key]["ref"])
        stack.smoke(selected)
        for key in selected:
            state["active"][key], state["previous"][key] = state["previous"][key], state["active"][key]
            state["active"][key]["deployed_at"] = timestamp().isoformat()
            state["active"][key]["container"] = stack.containers(key)["Id"]
            state["active"][key]["config_hash"] = service_hashes(stack, {key: state["active"][key]["ref"]})[key]
        store(stack.path, state)
        stack.append_event("rollback-succeeded", services=selected)
    except (Exception, KeyboardInterrupt):
        if was_running and "rimworld" not in attempted:
            stack.compose("start", "rimworld", allowed=True)
        stack.append_event("rollback-failed")
        say("Inspect release status and healthy services; no database restore was performed.")
        raise


RESTORE_ROLES = r"""
\getenv web_password RIMWORLD_WEB_DB_PASSWORD
\getenv api_password RIMWORLD_API_DB_PASSWORD
SELECT format('CREATE ROLE rimworld_web LOGIN PASSWORD %L', :'web_password') \gexec
SELECT format('CREATE ROLE rimworld_api LOGIN PASSWORD %L', :'api_password') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO rimworld_web, rimworld_api', current_database()) \gexec
"""


def restore(stack, request):
    source, info = backups.verify(backup_root(stack, create=False), request.backup)
    if info["game_version"] != GAME_VERSION or info["schema"] > len(db.migrations()):
        abort("Backup game or schema version is newer/different; use matching recovery code")
    if request.scope in ("full", "game") and info["scope"] != "full":
        abort("This backup does not include game files")
    if request.start and request.scope != "full":
        abort("--start requires a full backup")
    if request.confirm != request.backup:
        abort("Use --confirm BACKUP_ID to authorize restoring into a new isolated project")
    if not PROJECT.fullmatch(request.new_project) or request.new_project == stack.project:
        abort("Specify a new Compose project name distinct from the active deployment")
    for kind in (("ps", "-aq"), ("volume", "ls", "-q"), ("network", "ls", "-q")):
        if stack.command(*kind, "--filter", f"label=com.docker.compose.project={request.new_project}",
                         capture=True).stdout.strip():
            abort("Recovery project already has Docker resources; choose a different name")
    destination = stack.folder / "recovery" / request.new_project
    if destination.parent.is_symlink() or destination.exists() or destination.is_symlink():
        abort("Recovery directory exists or uses a symlink")
    if shutil.disk_usage(stack.folder).free < sum(f["bytes"] for f in info["files"].values()) * 2:
        abort("Insufficient free disk for safe recovery")
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    marker = destination / "restore-incomplete"
    marker.touch()
    (destination / "game").mkdir(mode=0o755)
    (destination / "game").chmod(0o755)
    if request.scope in ("full", "game"):
        backups.unpack(source / "game.tar", destination / "game")
        (destination / "bridge").mkdir(mode=0o755)
        backups.unpack(source / "bridge.tar", destination / "bridge")
    if request.scope == "game":
        marker.unlink()
        say(f"Game data restored to {destination}; existing project untouched")
        return
    recovered = plain_env(source / "compose.env")
    for key in ("RWT_BACKUP_DIR", "RIMWORLD_PUBLIC_HOST"):
        recovered.pop(key, None)
    defaults = dict(COMPOSE_PROJECT_NAME=request.new_project, RWT_WEB_ENV_FILE=(destination / "web.env").as_posix(),
                    RWT_POSTGRES_ENV_FILE=(destination / "postgres.env").as_posix(),
                    RWT_GAME_DATA=(destination / "game").as_posix(), RIMWORLD_HOST_BIND="127.0.0.1",
                    RIMWORLD_WEB_BIND="127.0.0.1", RWT_BEEKEEPER_ENABLED="0",
                    RIMWORLD_HOST_PORT=str(port(request.game_port)), RIMWORLD_WEB_PORT=str(port(request.web_port)))
    recovered.update(defaults)
    for name in ("postgres.env", "web.env"):
        shutil.copyfile(source / name, destination / name)
        (destination / name).chmod(0o600)
    config = destination / "compose.env"
    config.write_text("".join(f"{key}={value}\n" for key, value in recovered.items()), encoding="utf-8")
    config.chmod(0o600)
    test = Stack(destination)
    test.preflight(scopes(test, "all"))
    test.compose("up", "-d", "--no-recreate", "--wait", "--wait-timeout", "150", "postgres",
                 no_init=True, timeout=180)
    if int(test.sql("SHOW server_version_num;")) // 10000 != info["postgres_major"]:
        abort("PostgreSQL major version differs; recover with the original major version")
    test.sql(RESTORE_ROLES)
    with (source / "database.dump").open("rb") as dump:
        test.compose("exec", "-T", "postgres", "sh", "-ec",
                     'exec pg_restore --single-transaction --exit-on-error -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
                     stdin=dump, timeout=3600)
    for line in test.schema("apply"):
        say(f"Recovered migration {line}")
    # Sessions are not portable across a disaster restore, even though the
    # deployment's signing key and all account passwords are preserved.
    test.sql("TRUNCATE public.dashboard_sessions, public.dashboard_login_budget;")
    test.sql("SELECT count(*) FROM public.user_profile; SELECT count(*) FROM public.player_data;")
    store(destination / "restored-from.json", {"backup": request.backup, "scope": request.scope, "source": info["release"]})
    if request.scope == "full":
        volume = test.project + "_game_bridge"
        test.command("volume", "create", "--label", f"com.docker.compose.project={test.project}",
                     "--label", "com.docker.compose.volume=game_bridge", volume, quiet=True)
        with (source / "bridge.tar").open("rb") as archive:
            test.command("run", "--rm", "-i", "--network", "none", "-v", f"{volume}:/recovered",
                         "--entrypoint", "sh", test.containers("postgres")["Image"], "-ec",
                         'tar -xf - -C /recovered; chown 10001:10001 /recovered; chmod 0770 /recovered',
                         stdin=archive, timeout=1800)
    if request.start:
        options = argparse.Namespace(scope="all", dry_run=False, maintenance=False)
        apply_release(test, options, local=True)
    marker.unlink()
    say(f"Restored {request.scope} into {destination} with a new PostgreSQL volume; existing project untouched")


def external(host, number):
    if not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host):
        abort("External check requires a DNS name or IP")
    try:
        with socket.create_connection((host, port(number)), timeout=8):
            say("External TCP connection accepted; this does not verify the RimWorld login protocol")
    except ConnectionRefusedError:
        abort("TCP connection refused: check the listener, port mapping and firewall rejection policy")
    except TimeoutError:
        abort("TCP timed out: check the host/provider firewall, routing and NAT; the exact cause cannot be inferred")
    except OSError:
        abort("Connection failed: check DNS, routing and the configured host address")


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--state-dir", type=Path, default=ROOT / ".rwt-deploy")
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("bootstrap", "deploy", "rollback", "preflight", "smoke"):
        sub = commands.add_parser(name)
        sub.add_argument("--scope", choices=SCOPES, default="all")
        if name in ("bootstrap", "deploy", "rollback"):
            sub.add_argument("--maintenance", action="store_true")
        if name in ("bootstrap", "deploy"):
            sub.add_argument("--dry-run", action="store_true")
        if name == "deploy":
            sub.add_argument("--version", required=True)
        if name == "preflight":
            sub.add_argument("--version", help="also verify registry access for a published release")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--status", action="store_true")
    backup = commands.add_parser("backup")
    backup.add_argument("--scope", choices=("db", "full"), default="full")
    backup.add_argument("--maintenance", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("backup", nargs="?")
    recover = commands.add_parser("restore")
    recover.add_argument("backup")
    recover.add_argument("--new-project", required=True)
    recover.add_argument("--confirm")
    recover.add_argument("--scope", choices=("db", "game", "full"), default="full")
    recover.add_argument("--game-port", default=35555)
    recover.add_argument("--web-port", default=11005)
    recover.add_argument("--start", action="store_true")
    commands.add_parser("status")
    test_external = commands.add_parser("external")
    test_external.add_argument("host")
    test_external.add_argument("--port", default=25555)
    return cli


def main():
    os.umask(0o077)
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt
    for signum in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if signum is not None:
            signal.signal(signum, interrupted)
    args = parser().parse_args()
    name = args.command
    if name == "external":
        external(args.host, args.port)
        return
    stack = Stack(args.state_dir)
    read_only = name in ("status", "verify", "preflight", "smoke") or getattr(args, "dry_run", False) or (
        name == "migrate" and args.status
    )
    with (contextlib.nullcontext() if read_only else lock(stack.folder)):
        if name in ("bootstrap", "deploy"):
            apply_release(stack, args, local=name == "bootstrap")
        elif name == "rollback":
            rollback(stack, args)
        elif name == "preflight":
            selected = scopes(stack, args.scope)
            release = read_manifest(args.version) if args.version else None
            refs = {key: release["images"][key] for key in selected} if release else None
            stack.preflight(selected, refs=refs)
            if release:
                if not release["schema"][0] <= len(db.migrations()) <= release["schema"][1]:
                    abort("Release schema is incompatible with this checkout")
                for key, ref in refs.items():
                    result = stack.command("manifest", "inspect", ref, capture=True, quiet=True, allowed=True, timeout=30)
                    if result.returncode:
                        abort(f"Registry could not resolve {key}; verify the released digest and GHCR read access")
                    say(f"{key}: registry digest is reachable")
        elif name == "smoke":
            stack.smoke(scopes(stack, args.scope))
        elif name == "migrate":
            plan = stack.schema("status")
            if args.status:
                result = plan
            elif any(not line.startswith("applied ") for line in plan):
                capture_backup(stack, "db")
                result = stack.schema("apply")
            else:
                result = ["No pending migrations"]
            for line in result:
                say(line)
        elif name == "backup":
            if args.scope == "full" and not args.maintenance:
                abort("Full backups stop game and API briefly; use --maintenance")
            capture_backup(stack, args.scope)
        elif name == "verify":
            root = backup_root(stack, create=False)
            if args.backup:
                _, metadata = backups.verify(root, args.backup)
                print(json.dumps(metadata, indent=2))
            elif root.is_dir():
                print("\n".join(sorted(path.name for path in root.iterdir()
                                       if backups.BACKUP_ID.fullmatch(path.name) and not path.is_symlink())))
        elif name == "restore":
            restore(stack, args)
        elif name == "status":
            state = stack.state()
            print(json.dumps(state, indent=2))
            stack.compose("ps")
            root = backup_root(stack, create=False)
            latest = sorted(path.name for path in root.iterdir() if backups.BACKUP_ID.fullmatch(path.name)) if root.exists() else []
            say(f"Latest backup: {latest[-1] if latest else 'none'}")
            if latest:
                saved = dt.datetime.strptime(latest[-1][:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
                say(f"Last backup age: {max(0, int((timestamp() - saved).total_seconds() / 3600))} hours")
            say(f"Free disk: {shutil.disk_usage(stack.folder).free // 1024**2} MiB")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("Interrupted. Check release status and container health before retrying.")
        sys.exit(130)
    except sp.TimeoutExpired:
        say("Operation timed out; check container state and the deployment journal.")
        sys.exit(1)
    except (OSError, KeyError, TypeError, ValueError, tarfile.TarError) as exc:
        # Some exceptions can contain parsed input values (including secrets).
        say(str(exc) if type(exc) is ValueError else f"Operation failed ({type(exc).__name__}); verify files and permissions.")
        sys.exit(1)
