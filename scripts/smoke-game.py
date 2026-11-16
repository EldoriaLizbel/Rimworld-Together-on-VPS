import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg

for attempt in range(30):
    state = json.loads(Path("/bridge/boot.json").read_text())
    valid = state["status"] == "ready" and state["port"] == 25555
    valid = valid and (datetime.now(timezone.utc) - datetime.fromisoformat(state["heartbeat_at"])).total_seconds() < 10
    if valid:
        with psycopg.connect(connect_timeout=4) as db:
            valid = db.execute("SELECT EXISTS (SELECT 1 FROM world_config WHERE boot_id=%s)", (state["id"],)).fetchone()[0]
    if valid:
        with socket.create_connection(("rimworld", 25555), timeout=4):
            print("Game: current supervisor heartbeat, internal TCP listener and synchronized database snapshot")
        break
    time.sleep(2)
else:
    raise SystemExit("Game readiness/snapshot did not converge")
