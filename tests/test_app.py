import io
import os
import tarfile

import lz4.block
import msgpack
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

import db
import ops
import rwt_files
import safe_backup
from save_summary import unpack_save
import supervisor

os.environ.setdefault("RIMWORLD_API_TOKEN", "temporary-internal-test-token")
import main  # noqa: E402


@pytest.mark.parametrize("invalid", ["", "0", "65536", "1e5", "+80", "123456"])
def test_port_validation(invalid):
    with pytest.raises(ValueError):
        ops.port(invalid)


def test_manifest_rejects_wrong_service_digests_and_unsupported_game():
    version = "0" * 40
    data = {"format": 1, "commit": version, "platform": "linux/amd64", "game": ops.GAME_VERSION,
            "schema": [7, 7], "images": {k: f"{ops.REGISTRY}-{k}@sha256:" + "a" * 64 for k in ops.SERVICES}}
    assert ops.manifest(data, version) == data
    data["images"]["web"] = data["images"]["api"]
    with pytest.raises(ValueError, match="immutable"):
        ops.manifest(data, version)


def test_backup_archive_rejects_traversal_and_symlinks(tmp_path):
    for name, kind in (("../outside", tarfile.REGTYPE), ("nested/hop", tarfile.SYMTYPE), ("/root", tarfile.REGTYPE)):
        path = tmp_path / "fixture.tar"
        with tarfile.open(path, "w") as archive:
            item = tarfile.TarInfo(name)
            item.type = kind
            if kind == tarfile.SYMTYPE:
                item.linkname = "outside"
            archive.addfile(item, io.BytesIO())
        with pytest.raises(ValueError, match="unsafe"):
            safe_backup.unpack(path)


def test_backup_checksum_verification(tmp_path):
    backup_id = "20261116T000000Z-01234567"
    path = tmp_path / backup_id
    path.mkdir()
    for file in safe_backup.contents("db"):
        (path / file).write_bytes(b"test data")
    safe_backup.seal(path, backup_id, "db", postgres_major=16, schema=7)
    assert safe_backup.verify(tmp_path, backup_id)[1]["schema"] == 7
    (path / "database.dump").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        safe_backup.verify(tmp_path, backup_id)


def test_settings_are_atomic_and_only_allowlisted(tmp_path):
    target = tmp_path / "Configs" / "ServerConfig.json"
    target.parent.mkdir()
    rwt_files.write_json(target, {"Name": "before", "MaxPlayers": 10})
    change = {"file": "Configs/ServerConfig.json", "key": "Name", "previous": "before", "value": "after"}
    new = rwt_files.prepare_updates(tmp_path, [change])
    assert new[target]["Name"] == "after"
    assert rwt_files.read_json(target)["Name"] == "before"
    with pytest.raises(ValueError, match="read-only"):
        rwt_files.prepare_updates(tmp_path, [{**change, "file": "../../outside"}])
    with pytest.raises(ValueError, match="changed since"):
        rwt_files.prepare_updates(tmp_path, [{**change, "previous": "other"}])
    target.unlink()
    outside = tmp_path / "outside"
    outside.write_text('{"Name":"hidden"}', encoding="utf-8")
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="Linked"):
        rwt_files.read_json(target)


def test_supervisor_initialization_without_game_binary(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    boot = tmp_path / "boot.json"
    monkeypatch.setattr(supervisor, "GAME", game)
    monkeypatch.setattr(supervisor, "BOOT", boot)
    monkeypatch.setattr(supervisor, "REQUEST", tmp_path / "request.json")
    state = supervisor.initialize()
    assert state["status"] == "starting"
    assert not state["world_initialized"]
    assert rwt_files.read_json(boot)["id"] == state["id"]
    assert not rwt_files.read_json(game / "Configs/ServerConfig.json")["EnableServerTelemetry"]


def test_api_denies_missing_token_and_enforces_in_game_confirmation():
    client = TestClient(main.app)
    assert client.get("/config").status_code == 401
    main.app.dependency_overrides[main.user] = lambda: "user"
    try:
        assert client.get("/config").status_code == 403
        assert client.post("/factory-reset", json={"confirm": "factory-reset"}).status_code == 403
        main.app.dependency_overrides[main.user] = lambda: "superuser"
        assert client.post("/factory-reset", json={}).status_code == 422
        assert client.post("/player-reset", json={"username": "bad\nline", "confirm": "player-reset"}).status_code == 422
        assert client.patch("/config", json={"revision": "wrong", "changes": []}).status_code == 422
    finally:
        main.app.dependency_overrides.clear()


def test_db_timeout_reports_generic_503(monkeypatch):
    class Unavailable:
        def connection(self):
            raise PoolTimeout("private DSN")

    monkeypatch.setattr(main.app.state, "pool", Unavailable(), raising=False)
    response = TestClient(main.app).get("/healthz")
    assert response.status_code == 503
    assert "private" not in response.text


def test_migration_script_has_lock_and_legacy_seed_is_non_destructive():
    result = db.script("apply")
    assert result.index("pg_advisory_lock") < result.index("INSERT INTO schema_migrations")
    assert "DELETE FROM public.user_profile" not in result
    assert "checksum mismatch" in result
    assert "baseline=:baselined" in result


def test_host_operation_lock_rejects_competing_operation(tmp_path):
    with ops.lock(tmp_path):
        with pytest.raises(ValueError, match="holds the lock"), ops.lock(tmp_path):
            pytest.fail("Concurrent acquisition unexpectedly succeeded")
    with ops.lock(tmp_path):
        pass


def test_save_decoder_supports_native_lz4_envelope():
    xml = b"<savegame><game /></savegame>"
    packed = msgpack.packb(xml)
    compressed = msgpack.packb(len(packed)) + lz4.block.compress(packed, store_size=False)
    assert unpack_save(msgpack.packb(msgpack.ExtType(99, compressed))) == xml
