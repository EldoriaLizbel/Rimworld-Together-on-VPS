"""Read colony details from a supported server-side RimWorld save."""
import io
import re
from functools import lru_cache
from xml.etree.ElementTree import ParseError

import lz4.block
import msgpack
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

MAX_PACKED = 48 * 1024 * 1024
MAX_XML = 96 * 1024 * 1024
FACTION = ("savegame", "game", "world", "factionManager", "allFactions", "li")
WORLD_OBJECT = ("savegame", "game", "world", "worldObjects", "worldObjects", "li")
MAP_INFO = ("savegame", "game", "maps", "li", "mapInfo")
MAP_THING = ("savegame", "game", "maps", "li", "things", "thing")
RECORDS = {FACTION, WORLD_OBJECT, MAP_INFO, MAP_THING}
TILE = re.compile(r"(-?\d+)(?:,-?\d+)?")


def unpack_save(packed):
    def unpack(data):
        return msgpack.unpackb(data, max_array_len=4, max_map_len=0, max_bin_len=MAX_XML, max_ext_len=MAX_PACKED)

    payload = unpack(packed)
    if isinstance(payload, msgpack.ExtType) and payload.code == 99:
        # MessagePack-CSharp Lz4Block starts with a serialized uncompressed size.
        buffer = msgpack.Unpacker(max_buffer_size=MAX_PACKED, max_array_len=0, max_map_len=0)
        buffer.feed(payload.data)
        length = next(buffer)
        if type(length) is not int or not 0 < length <= MAX_XML:
            raise ValueError("Unsupported save size")
        decoded = lz4.block.decompress(payload.data[buffer.tell():], uncompressed_size=length)
        if len(decoded) != length:
            raise ValueError("Invalid save size")
        payload = unpack(decoded)
    if not isinstance(payload, bytes):
        raise ValueError("Unsupported save encoding")
    return payload


def parse_colonies(payload, tiles):
    stack = []
    tags = []
    record = None
    player = None
    settlements = {}
    map_parent = None
    counts = {}
    for event, element in ElementTree.iterparse(io.BytesIO(payload), events=("start", "end")):
        if event == "start":
            stack.append(element)
            tags.append(element.tag)
            if len(tags) > 256:
                raise ValueError("Unsupported nesting depth in save")
            if record is None and tuple(tags) in RECORDS:
                record = tuple(tags)
            continue
        if record and len(tags) == len(record):
            if record == FACTION and element.findtext("def") in ("PlayerColony", "PlayerTribe"):
                if element.findtext("loadID"):
                    player = f"Faction_{element.findtext('loadID')}"
            elif record == WORLD_OBJECT and player and element.findtext("faction") == player:
                match = TILE.fullmatch(element.findtext("tile") or "")
                identity = element.findtext("ID")
                if element.get("Class") == "Settlement" and identity and match and int(match[1]) in tiles:
                    settlements[f"WorldObject_{identity}"] = (int(match[1]), element.findtext("nameInt") or None)
            elif record == MAP_INFO:
                map_parent = element.findtext("parent")
                if map_parent in settlements:
                    counts[map_parent] = 0
            elif record == MAP_THING and map_parent in counts:
                is_colonist = (
                    element.get("Class") == "Pawn" and element.findtext("faction") == player
                    and element.find("story") is not None
                    and element.findtext("guest/joinStatus") not in ("Prisoner", "Slave")
                    and element.findtext("guest/slaveFaction") in (None, "null")
                )
                if is_colonist:
                    counts[map_parent] += 1
            record = None
        if record is None:
            if len(stack) > 1:
                stack[-2].remove(element)
            element.clear()
        stack.pop()
        tags.pop()
    names = [name for _, name in sorted(settlements.values(), key=lambda item: item[0]) if name]
    complete = {tile for parent, (tile, _) in settlements.items() if parent in counts} == set(tiles)
    return (names[0] if names else None, sum(counts.values()) if complete and counts else None)


@lru_cache(maxsize=256)
def summary(path, modified_ns, size, tiles):
    if not tiles or not 0 < size <= MAX_PACKED:
        return None, None
    try:
        with path.open("rb") as source:
            packed = source.read(MAX_PACKED + 1)
        if len(packed) != size or path.stat().st_mtime_ns != modified_ns:
            return None, None
        return parse_colonies(unpack_save(packed), tiles)
    except (OSError, ValueError, TypeError, StopIteration, ParseError, DefusedXmlException, lz4.block.LZ4BlockError):
        return None, None
