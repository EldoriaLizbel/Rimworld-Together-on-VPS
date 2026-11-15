"""Capture the configuration created by the pinned official binary in a clean directory."""
import subprocess
import tempfile
import time
from pathlib import Path

from rwt_files import EDITABLE, FACTORY_DEFAULTS, PASSWORD_FILE, read_json, write_json


def generate():
    with tempfile.TemporaryDirectory() as directory:
        game = Path(directory)
        log = game / "startup.log"
        with log.open("wb") as output:
            process = subprocess.Popen(["/App/Server/RTServer"], cwd=game, stdin=subprocess.PIPE,
                                       stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 25
                while "Listening for users at" not in log.read_text(errors="replace"):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError(f"Official defaults could not be generated:\n{log.read_text(errors='replace')}")
                    time.sleep(.1)
                defaults = {file: read_json(game / file) for file in (*EDITABLE, PASSWORD_FILE)}
                if not all(isinstance(document, dict) for document in defaults.values()):
                    raise RuntimeError("The official image did not generate all expected config files")
                write_json(FACTORY_DEFAULTS, defaults)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    generate()
