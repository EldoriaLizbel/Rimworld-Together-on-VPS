"""Validate Compose models with fake credentials and no running containers."""
import json
import tempfile
from pathlib import Path

import integration

root = integration.ops.ROOT
with tempfile.TemporaryDirectory(prefix="rwt-compose-test-") as tmp:
    stub = integration.fixture(Path(tmp).resolve() / "fixture", "rwt-ci-config-only", [25555, 10005, 5800])
    dev = json.loads(stub.compose("config", "--format", "json", capture=True).stdout)
    refs = {service: f"{stub.envfile.parent.name}-test" for service in integration.ops.SERVICES}
    with stub.envfile.open("a", encoding="utf-8") as variables:
        for service in refs:
            name = f"{integration.ops.REGISTRY}-{service}@sha256:" + "a" * 64
            variables.write(f"RWT_{service.upper()}_IMAGE={name}\n")
    prod = json.loads(stub.command("compose", "--env-file", str(stub.envfile), "-f", str(root / "compose.yaml"),
                                   "-f", str(root / "compose.prod.yaml"), "--profile", "tools",
                                   "config", "--format", "json", capture=True).stdout)
    for model in (dev, prod):
        services = model["services"]
        assert set(services) == {"postgres", *integration.ops.SERVICES}
        for key in ("postgres", "api"):
            assert not services[key].get("ports")
        for key in ("web", "beekeeper"):
            assert services[key]["ports"][0]["host_ip"] == "127.0.0.1"
        assert services["rimworld"]["ports"][0]["target"] == 25555
        assert services["rimworld"]["ports"][0]["protocol"] == "tcp"
        assert all(svc.get("healthcheck", {}).get("test") for svc in services.values())
        assert all("docker.sock" not in json.dumps(service.get("volumes", [])) for service in services.values())
        assert model["volumes"]["postgres_data"]["name"] == "rwt-ci-config-only_postgres_data"
    assert all("build" not in prod["services"][service] for service in integration.ops.SERVICES)
    assert prod["services"]["beekeeper"]["profiles"] == ["tools"]
    print("Development and digest-only Production Compose validated.")
