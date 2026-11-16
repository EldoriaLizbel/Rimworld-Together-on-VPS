import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

BRIDGE = Path("/bridge")
BOOT = BRIDGE / "boot.json"
REQUEST = BRIDGE / "request.json"
STAGED = BRIDGE / "staged-config.json"
SPOOL = BRIDGE / "logs"
LOGINS = BRIDGE / "logins"
WORLD = "Assets/WorldValuesFile.json"
PASSWORD_FILE = "Configs/PasswordConfig.json"
FACTORY_DEFAULTS = Path("/opt/rwt/factory-defaults.json")
EVENT_FILE = re.compile(r"Assets/Events/[^/\\]+\.json")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[=>]")
LOG_PREFIX = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \| ")
LOGIN_LINE = re.compile(r"^\[Log in\] > (.+?) \| ")
IDENTIFIER = re.compile(r"[0-9a-f]{32}")
GAME_USERNAME = re.compile(r"[\w.@-]{1,64}")

BOOL = ("boolean", None)
COUNT = ("integer", 1000000, 0)
FACTOR = ("decimal", 100, 0)
FRACTION = ("decimal", 1, 0)
DAY_MS = 86400000
ACTIONS = ("Raid", "Trade", "Caravan", "Aid", "Event", "Market", "Guild", "Site", "Road", "River", "Pollution", "Scenario")
ROAD_TYPES = ("DirtPath", "DirtRoad", "StoneRoad", "AsphaltPath", "AsphaltHighway")
EVENT_FIELDS = {"Name": ("text", 100), "Cost": COUNT, "IsEnabled": BOOL}

# Explicit fields from the installed game release. Keep identifiers and save topology outside this editor.
EDITABLE = {
    "Configs/ServerConfig.json": {
        "Name": ("text", 40), "Description": ("text", 200), "MaxPlayers": ("integer", 1000),
        "DiscordURL": ("url", 500), "SteamWorkshopURL": ("url", 500),
        "Verbosity": ("verbosity", 2, 0), "DisplayChatInConsole": BOOL, "UseUPnP": BOOL,
        "EnableServerBrowser": ("boolean", None), "EnableServerTelemetry": ("boolean", None),
    },
    "Configs/ChatConfig.json": {
        "EnableMoTD": ("boolean", None), "MessageOfTheDay": ("text", 500),
        "LoginNotifications": ("boolean", None), "DisconnectNotifications": ("boolean", None),
    },
    "Configs/BackupConfig.json": {
        "AutomaticBackups": BOOL, "IntervalHours": ("integer", 168), "AutomaticDeletion": BOOL,
        "Amount": ("integer", 1000),
    },
    "Configs/DifficultyConfig.json": {
        "IsDifficultyEnforced": BOOL,
        **dict.fromkeys((
            "AllowBigThreats", "AllowViolentQuests", "AllowIntroThreats", "PredatorsHuntHumanlikes",
            "AllowExtremeWeatherIncidents", "PeacefulTemples", "AllowCaveHives", "UnwaveringPrisoners",
            "AllowTraps", "AllowTurrets", "AllowMortars", "ClassicMortars", "FixedWealthMode",
            "NoBabiesOrChildren", "BabiesAreHealthy", "ChildRaidersAllowed",
        ), BOOL),
        **dict.fromkeys((
            "ThreatScale", "CropYieldFactor", "MineYieldFactor", "ButcherYieldFactor", "ResearchSpeedFactor",
            "QuestRewardValueFactor", "RaidLootPointsFactor", "MaintenanceCostFactor",
            "EnemyDeathOnDownedChanceFactor", "FoodPoisonChanceFactor", "ManhunterChanceOnDamageFactor",
            "PlayerPawnInfectionChanceFactor", "DiseaseIntervalFactor", "EnemyReproductionRateFactor",
            "DeepDrillInfestationChanceFactor", "FriendlyFireChanceFactor", "AdaptationEffectFactor",
            "AdaptationGrowthRateFactorOverZero", "LowPopConversionBoost", "ChildAgingRate", "AdultAgingRate",
            "WastepackInfestationChanceFactor", "NomadicMineableResourcesFactor",
        ), FACTOR),
        "ScariaRotChance": FRACTION, "AllowInstantKillChance": FRACTION,
        "TradePriceFactorLoss": ("decimal", 1, -1), "ColonistMoodOffset": ("decimal", 100, -100),
    },
    "Configs/StorytellerConfig.json": {"IsEnforced": BOOL},
    "Configs/ScenarioConfig.json": {"IsEnforced": BOOL},
    "Configs/ModConfig.json": {"AllowAllMods": BOOL, "EnforceSettings": BOOL},
    **{
        f"Configs/Actions/{action}.json": {"IsEnabled": BOOL, "Cooldown": ("decimal", DAY_MS, 0)}
        for action in ACTIONS if action != "Scenario"
    },
    # The client reads only IsEnabled for custom scenarios.
    "Configs/Actions/Scenario.json": {"IsEnabled": BOOL},
}
EDITABLE["Configs/Actions/Market.json"].update(
    MinimumPrice=COUNT, PriceMultiplier=FACTOR, MaxEntriesPerPlayer=("integer", 1000),
)
EDITABLE["Configs/Actions/Site.json"].update(
    TimeInterval=("decimal", DAY_MS * 30, 1), BuildingCost=COUNT, RewardsCount=COUNT,
)
for road in ROAD_TYPES:
    EDITABLE["Configs/Actions/Road.json"].update({
        f"RoadValues.Allow{road}": BOOL, f"RoadValues.{road}Cost": COUNT,
        f"RoadValues.{road}Multiplier": FRACTION,
    })

ENFORCED_SELECTIONS = {"Configs/StorytellerConfig.json": "DefName", "Configs/ScenarioConfig.json": "Name"}


def now():
    return datetime.now(timezone.utc)


def open_game_file(path):
    if path.resolve() != path.absolute():
        raise ValueError("Linked game files are not permitted")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("Expected a regular game file")
    return os.fdopen(fd, "rb")


def read_json(path):
    try:
        with open_game_file(path) as source:
            limit = 16 * 1024 * 1024
            data = source.read(limit + 1)
            if len(data) > limit:
                raise ValueError("Game JSON exceeds the size limit")
            return json.loads(data.decode("utf-8-sig"))
    except FileNotFoundError:
        return None


def write_json(path, payload, mode=None):
    if path.resolve() != path.absolute():
        raise ValueError("Linked game files are not permitted")
    if mode is None:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".pending-", delete=False
    ) as output:
        temp = Path(output.name)
        try:
            os.chmod(temp, mode)
            json.dump(payload, output, indent=2, ensure_ascii=False, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def read_settings(game):
    paths = sorted(
        set((game / "Configs").glob("*.json"))
        | set((game / "Configs/Actions").glob("*.json"))
        | set((game / "Assets/Events").glob("*.json"))
        | {game / WORLD}
    )
    settings = {}
    for path in paths:
        if path.is_symlink() or path.name.lower() in ("passwordconfig.json", "ipbanconfig.json"):
            continue
        value = read_json(path)
        if value is not None:
            settings[path.relative_to(game).as_posix()] = value
    return settings


def revision(settings):
    data = json.dumps(settings, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def fields_for(file):
    return EVENT_FIELDS if EVENT_FILE.fullmatch(file) else EDITABLE.get(file, {})


def setting_target(document, key):
    *parents, field = key.split(".")
    for parent in parents:
        document = document.get(parent) if isinstance(document, dict) else None
    if not isinstance(document, dict) or field not in document:
        raise ValueError(f"{key} is unavailable")
    return document, field


def has_selection(document, selection):
    value = document.get(selection)
    return isinstance(value, str) and bool(value.strip())


def available_fields(settings):
    groups = {}
    for file in dict.fromkeys((*EDITABLE, *settings)):
        document = settings.get(file)
        if not isinstance(document, dict):
            continue
        if (selection := ENFORCED_SELECTIONS.get(file)) and not (document.get("IsEnforced") or has_selection(document, selection)):
            continue
        fields = {}
        for key, rule in fields_for(file).items():
            try:
                setting_target(document, key)
            except ValueError:
                continue
            fields[key] = rule
        if fields:
            groups[file] = fields
    return groups


def validate_change(file, key, value):
    rule = fields_for(file).get(key)
    if not rule:
        raise ValueError(f"{file} / {key} is read-only")
    kind, limit, *bounds = rule
    minimum = bounds[0] if bounds else 1
    if kind == "boolean":
        valid = type(value) is bool
        requirement = "a boolean"
    elif kind in ("text", "url"):
        valid = (isinstance(value, str) and len(value) <= limit
                 and all(character.isprintable() for character in value)
                 and (key != "Name" or bool(value.strip())))
        requirement = f"text up to {limit} characters"
        if valid and kind == "url" and value:
            url = urlsplit(value)
            valid = (url.scheme in ("http", "https") and bool(url.hostname)
                     and url.username is None and not any(character.isspace() for character in value))
            requirement = f"an HTTP or HTTPS URL up to {limit} characters"
    else:
        number_types = (int, float) if kind == "decimal" else (int,)
        valid = type(value) in number_types and minimum <= value <= limit
        requirement = f"a number from {minimum} to {limit}" if kind == "decimal" else f"an integer from {minimum} to {limit}"
    if not valid:
        raise ValueError(f"{key} requires {requirement}")


def prepare_updates(game, changes):
    documents = {}
    for change in changes:
        file, key, value = change["file"], change["key"], change["value"]
        validate_change(file, key, value)
        path = game / file
        if path.resolve() != path:
            raise ValueError(f"{file} cannot be edited through a symlink")
        if path not in documents:
            documents[path] = read_json(path)
        document, field = setting_target(documents[path], key)
        if document[field] not in (change["previous"], value):
            raise ValueError(f"{file} / {key} changed since the request was submitted")
        document[field] = value
    for file, selection in ENFORCED_SELECTIONS.items():
        document = documents.get(game / file)
        if document and document.get("IsEnforced") and not has_selection(document, selection):
            raise ValueError(f"Choose a {selection} in the in-game Admin Panel before enabling enforcement")
    return documents


def password_digest(password):
    if not isinstance(password, str) or len(password) > 64 or (password and not re.fullmatch(r"[!-~]+", password)):
        raise ValueError("Use up to 64 printable ASCII characters without spaces")
    return hashlib.sha256(password.encode("ascii")).hexdigest().upper() if password else ""


def prepare_password(game, digest):
    if digest != "" and not re.fullmatch(r"[A-F0-9]{64}", digest):
        raise ValueError("Invalid password digest")
    path = game / PASSWORD_FILE
    if path.resolve() != path:
        raise ValueError("Invalid password config path")
    document, key = setting_target(read_json(path), "Password")
    document[key] = digest
    return path, document


def apply_password(game, digest):
    path, document = prepare_password(game, digest)
    write_json(path, document, mode=0o600)


def write_settings_batch(documents):
    originals = {path: read_json(path) for path in documents}
    written = []
    try:
        for path, document in documents.items():
            write_json(path, document, mode=0o600 if path.name == Path(PASSWORD_FILE).name else None)
            written.append(path)
    except OSError:
        for path in reversed(written):
            write_json(path, originals[path])
        raise


def restore_factory_defaults(game):
    defaults = read_json(FACTORY_DEFAULTS)
    settings = read_settings(game)
    changes = []
    for file, fields in EDITABLE.items():
        if file not in settings:
            continue  # The official binary recreates missing configuration files.
        for key in fields:
            current, field = setting_target(settings[file], key)
            default, _ = setting_target(defaults[file], key)
            if current[field] != default[field]:
                changes.append({"file": file, "key": key, "value": default[field], "previous": current[field]})
    documents = prepare_updates(game, changes)
    password_path = game / PASSWORD_FILE
    if password_path.resolve() != password_path:
        raise ValueError("Invalid password config path")
    password = read_json(password_path)
    if password is not None:
        password["Password"] = defaults[PASSWORD_FILE]["Password"]
        documents[password_path] = password
    write_settings_batch(documents)
