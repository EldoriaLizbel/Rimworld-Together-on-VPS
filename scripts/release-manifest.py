"""Extract registry digests from successful docker push outputs."""
import json
import re
import sys
from pathlib import Path

import db
import ops

directory, registry, commit = sys.argv[1:]
folder = Path(directory)
images = {}
for service in ops.SERVICES:
    output = (folder / f"{service}.push").read_text(encoding="utf-8")
    match = re.search(rf"^sha-{commit}: digest: (sha256:[0-9a-f]{{64}}) size: \d+$", output, re.M)
    if not match:
        raise SystemExit(f"Registry did not confirm the digest for {service}")
    images[service] = f"{registry}-{service}@{match[1]}"
schema = len(db.migrations())
document = ops.manifest({
    "format": 1, "commit": commit, "schema": [schema, schema], "images": images,
    "game": ops.GAME_VERSION, "platform": "linux/amd64", "built_at": ops.timestamp().isoformat(),
}, commit)
(folder / "release.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
