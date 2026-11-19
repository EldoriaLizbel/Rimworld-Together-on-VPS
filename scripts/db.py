"""Build a single psql session: advisory lock, verified legacy baseline and atomic migrations."""
import hashlib
import re
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[1] / "postgresql_1/postgres-docker/sql"
LOCK = 51837720702255
TABLES = {
    1: {"user_profile": "username nickname password role created_at last_login"},
    4: {"world_config": "singleton revision settings world_initialized updated_at boot_id",
        "server_log": "id epoch boot_id stream byte_offset occurred_at category description",
        "player_data": "username colony_name colonist_count settlement_tiles last_login last_save updated_at"},
    5: {"player_online_sample": "sampled_at boot_id online_players player_count session_counts last_log_id"},
    6: {"worker_sample": "sampled_at ram_used_bytes ram_available_bytes game_boot_id game_uptime_seconds"},
    7: {"dashboard_sessions": "token_hash username expires_at", "dashboard_login_budget": "bucket attempts expires_at"},
    8: {"world_config": "world_reset_id"},
}
INDEXES = {4: ("server_log_timeline_idx",), 5: ("player_online_sample_boot_time_idx",),
           7: ("dashboard_sessions_expiry_idx",)}


def migrations(directory=DIRECTORY):
    result = []
    for path in sorted(directory.glob("*.sql")):
        if not re.fullmatch(r"\d{3}_[a-z0-9_]+\.sql", path.name):
            raise ValueError("Invalid migration filename")
        number = int(path.name[:3])
        source = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^BEGIN;$", source) or not re.search(r"\nCOMMIT;\s*$", source):
            raise ValueError(f"{path.name} must use one outer transaction")
        body = re.sub(r"(?m)^BEGIN;$", "", source, count=1)
        body = re.sub(r"\nCOMMIT;\s*$", "", body)
        result.append((number, hashlib.sha256(source.encode()).hexdigest(), body))
    if [row[0] for row in result] != list(range(1, len(result) + 1)) or len(result) < 7:
        raise ValueError("Migration files must start at 001 and have sequential versions")
    return result


def grants(role, tables):
    privileges = " AND ".join(
        f"has_table_privilege('{role}',to_regclass('public.{table}'),'{op}')"
        for table in tables for op in ("SELECT", "INSERT", "UPDATE", "DELETE")
    )
    return f"(CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}' AND rolcanlogin) THEN ({privileges}) ELSE false END)"


def postcondition(number):
    checks = []
    for table, columns in TABLES.get(number, {}).items():
        columns = columns.split()
        values = ",".join(f"'{name}'" for name in columns)
        checks.append(f"(SELECT count(*)={len(columns)} FROM pg_attribute "
                      f"WHERE attrelid=to_regclass('public.{table}') AND attnum>0 AND NOT attisdropped AND attname IN ({values}))")
        checks.append(f"EXISTS (SELECT 1 FROM pg_constraint WHERE contype='p' AND conrelid=to_regclass('public.{table}'))")
    for index in INDEXES.get(number, ()):
        checks.append(f"to_regclass('public.{index}') IS NOT NULL")
    if number == 2:
        # This check is called only once user_profile exists.
        checks.extend(["EXISTS (SELECT 1 FROM pg_extension WHERE extname='pgcrypto')",
                       "EXISTS (SELECT 1 FROM public.user_profile WHERE role='superuser' AND password IS NOT NULL)"])
    if number == 3:
        checks.append(grants("rimworld_web", ["user_profile"]))
    if number == 4:
        checks.extend([grants("rimworld_api", TABLES[4]),
                       "(CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rimworld_api') THEN "
                       "has_sequence_privilege('rimworld_api',to_regclass('public.server_log_id_seq'),'USAGE') ELSE false END)"])
    if number in (5, 6, 7):
        checks.append(grants("rimworld_web" if number == 7 else "rimworld_api", TABLES[number]))
    # A future migration requires an explicit observable postcondition.
    if not checks:
        raise ValueError(f"No postcondition for migration {number:03}")
    return "COALESCE((" + " AND ".join(checks) + "), false)"


def check_version(minimum, maximum):
    return f"""SELECT COALESCE(max(version),0) BETWEEN {int(minimum)} AND {int(maximum)} AS compatible
FROM public.schema_migrations \\gset
\\if :compatible
\\else
DO $$ BEGIN RAISE EXCEPTION 'Installed schema is incompatible with the selected application'; END $$;
\\endif
"""


def script(mode, accepted=None, directory=DIRECTORY):
    files = migrations(directory)
    high = files[-1][0]
    lines = [r"\set ON_ERROR_STOP on", "SET statement_timeout='90s';", "SET lock_timeout='15s';",
             "SET search_path=public,pg_catalog;", f"SELECT pg_advisory_lock({LOCK});",
             r"SELECT to_regclass('public.schema_migrations') IS NOT NULL AS tracking \gset"]
    expected = ", ".join(f"({version},'{checksum}')" for version, checksum, _ in files)
    lines += [r"\if :tracking",
              rf"""SELECT NOT EXISTS(
    SELECT 1 FROM public.schema_migrations applied
    LEFT JOIN (VALUES {expected}) AS expected(version,checksum) USING (version)
    WHERE expected.checksum IS NULL OR expected.checksum <> applied.checksum) AS supported \gset""",
              r"\if :supported", r"\else",
              "DO $$ BEGIN RAISE EXCEPTION 'Unknown migration or checksum mismatch'; END $$;",
              r"\endif", r"\endif"]
    if mode == "apply":
        lines += ["""CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version integer PRIMARY KEY, checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    baseline boolean NOT NULL, duration_ms integer NOT NULL
);""", r"\set tracking true"]
    for number, digest, body in files:
        lines += [r"\if :tracking",
                  rf"SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version={number}) AS applied,",
                  rf"NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version={number} AND checksum<>'{digest}') AS valid \gset",
                  r"\else", r"\set applied false", r"\set valid true", r"\endif",
                  r"\if :valid", r"\else",
                  f"DO $$ BEGIN RAISE EXCEPTION 'Migration {number:03} checksum mismatch'; END $$;",
                  r"\endif"]
        lines += [r"\if :applied"]
        if mode == "status":
            lines += [rf"\echo applied {number:03}"]
        lines += [r"\else"]
        if mode == "apply":
            lines += ["BEGIN;", r"SELECT clock_timestamp() AS started \gset"]
        if number == 2:
            lines += [r"SELECT to_regclass('public.user_profile') IS NOT NULL AS accounts \gset",
                      r"\if :accounts"]
        lines += ["SELECT " + postcondition(number) + r" AS postcondition \gset"]
        if number == 2:
            lines += [r"\else", r"\set postcondition false", r"\endif"]
        if mode == "apply":
            lines += [r"\if :postcondition", r"\set baselined true", r"\else", body,
                      r"\set baselined false", "SELECT " + postcondition(number) + r" AS postcondition \gset",
                      r"\if :postcondition", r"\else",
                      f"DO $$ BEGIN RAISE EXCEPTION 'Migration {number:03} postcondition failed'; END $$;",
                      r"\endif", r"\endif",
                      f"INSERT INTO schema_migrations VALUES ({number},'{digest}',clock_timestamp(),"
                      ":'baselined', (extract(epoch FROM (clock_timestamp()-:'started'::timestamptz))*1000)::int);",
                      "COMMIT;", rf"\echo verified {number:03} baseline=:baselined"]
        elif mode == "status":
            lines += [r"\if :postcondition", rf"\echo baseline {number:03}", r"\else",
                      rf"\echo pending {number:03}", r"\endif"]
        lines += [r"\endif"]
    lines += [r"\if :tracking",
              rf"SELECT NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version NOT BETWEEN 1 AND {high}) AS supported \gset",
              r"\if :supported", r"\else",
              "DO $$ BEGIN RAISE EXCEPTION 'Database schema is newer than this checkout'; END $$;",
              r"\endif", r"\endif"]
    if accepted:
        lines += [r"\if :tracking", check_version(*accepted), r"\else",
                  "DO $$ BEGIN RAISE EXCEPTION 'Database has no managed schema'; END $$;", r"\endif"]
    lines += [f"SELECT pg_advisory_unlock({LOCK});"]
    return "\n".join(lines) + "\n"
