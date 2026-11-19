"""Archive native game state while the game process is stopped."""
import os
import re
from pathlib import Path

from rwt_files import read_json, write_json

RESET_DIRECTORIES = ("Assets", "Configs", "Logs", "Backups")


def reset_world(game, reset_id):
    if not re.fullmatch(r"[0-9a-f]{32}", reset_id):
        raise ValueError("Invalid world reset identifier")
    game = Path(game)
    archive = game / ".factory-resets" / reset_id
    if archive.resolve() != archive.absolute():
        raise ValueError("Invalid world backup path")
    archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive.parent.chmod(0o700)
    manifest = archive / "reset.json"
    progress = read_json(manifest) or {}
    if progress.get("status") == "complete":
        return reset_id
    for name in RESET_DIRECTORIES:
        active, saved = game / name, archive / name
        if active.is_symlink() or saved.is_symlink():
            raise ValueError("World reset cannot move linked directories")
        if active.exists() and not active.is_dir():
            raise ValueError("Expected a native game directory")
        if active.exists() and saved.exists():
            raise ValueError("Conflicting world reset backup")
    # Save the intent before moving anything. Repeating the same operation
    # resumes interrupted moves without deleting a completed operation's new world.
    write_json(manifest, {"id": reset_id, "status": "in-progress"}, mode=0o600)
    moved = []
    try:
        for name in RESET_DIRECTORIES:
            active, saved = game / name, archive / name
            if active.exists():
                os.replace(active, saved)
                moved.append(name)
        write_json(manifest, {"id": reset_id, "status": "complete",
                              "included": [name for name in RESET_DIRECTORIES if (archive / name).exists()]},
                   mode=0o600)
    except OSError:
        for name in reversed(moved):
            os.replace(archive / name, game / name)
        raise
    return reset_id
