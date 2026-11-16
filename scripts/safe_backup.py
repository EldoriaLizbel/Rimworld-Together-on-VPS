"""Treat backup archives as untrusted input; restore only into new directories."""
import hashlib
import json
import os
import re
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import PurePosixPath

BACKUP_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")
ENV_FILES = ("compose.env", "web.env", "postgres.env")
LIMIT_FILES = 500_000


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _hash(source)


def _hash(source):
    value = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        value.update(chunk)
    return value.hexdigest()


def safe_members(archive):
    names = set()
    for item in archive:
        if len(names) >= LIMIT_FILES:
            raise ValueError("Archive contains too many entries")
        name = PurePosixPath(item.name)
        if (name.is_absolute() or ".." in name.parts or "\\" in item.name or ":" in item.name
                or (not item.isfile() and not item.isdir()) or name in names):
            raise ValueError("Archive contains an unsafe or duplicate path")
        if not name.parts and not item.isdir():
            raise ValueError("Invalid archive root")
        names.add(name)
        yield item, name


def unpack(path, target=None):
    total = 0
    budget = shutil.disk_usage(target).free if target else None
    with tarfile.open(path, "r:*") as archive:
        for item, name in safe_members(archive):
            total += item.size
            if budget is not None and total > budget:
                raise ValueError("Insufficient space for restored data")
            if target is None or not name.parts:
                continue
            dest = target.joinpath(*name.parts)
            if item.isdir():
                dest.mkdir(parents=True, exist_ok=True, mode=0o755)
                dest.chmod(0o755)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                dest.parent.chmod(0o755)
                with archive.extractfile(item) as src, dest.open("xb") as out:
                    shutil.copyfileobj(src, out)
                # The API runs with a different UID than the game. Protect password settings.
                dest.chmod(0o600 if dest.name == "PasswordConfig.json" else 0o644)
    return total


def contents(scope):
    return set(ENV_FILES) | {"database.dump", "release.json"} | (
        {"game.tar", "bridge.tar"} if scope == "full" else set()
    )


def regular(path):
    return not path.is_symlink() and path.is_file()


def verify(root, identifier):
    if not BACKUP_ID.fullmatch(identifier):
        raise ValueError("Invalid backup ID")
    path = root / identifier
    if path.is_symlink() or not path.is_dir() or not regular(path / "manifest.json"):
        raise ValueError("Backup not found or unsafe backup directory")
    metadata = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if (metadata["version"] != 1 or metadata["id"] != identifier or metadata["scope"] not in ("db", "full")
            or set(metadata["files"]) != contents(metadata["scope"]) or metadata["verification"] != "passed"):
        raise ValueError("Invalid backup manifest")
    for name, recorded in metadata["files"].items():
        member = path / name
        if not regular(member) or member.stat().st_size != recorded["bytes"] or digest(member) != recorded["sha256"]:
            raise ValueError(f"Backup integrity check failed: {name}")
        if name.endswith(".tar"):
            unpack(member)
    return path, metadata


def seal(stage, identifier, scope, **extra):
    metadata = {
        "version": 1, "id": identifier, "scope": scope, **extra,
        "created_at": datetime.now(timezone.utc).isoformat(), "verification": "passed",
        "files": {name: {"sha256": digest(stage / name), "bytes": (stage / name).stat().st_size}
                  for name in sorted(contents(scope))},
    }
    (stage / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    for path in stage.iterdir():
        path.chmod(0o600)
        with path.open("rb+") as handle:
            os.fsync(handle.fileno())
    return metadata
