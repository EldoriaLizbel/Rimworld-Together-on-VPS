"""Read-only, bounded views of explicitly permitted game tables."""
from typing import Annotated

from fastapi import HTTPException, Query, Request
from psycopg import sql

TABLES = {
    "world_config": ("World configuration", ("singleton", "revision", "settings", "world_initialized", "updated_at", "boot_id", "world_reset_id"), ("updated_at",)),
    "server_log": ("Server logs", ("id", "epoch", "boot_id", "stream", "byte_offset", "occurred_at", "category", "description"), ("occurred_at", "id")),
    "player_data": ("Player metadata", ("username", "colony_name", "colonist_count", "settlement_tiles", "last_login", "last_save", "updated_at"), ("username",)),
    "player_online_sample": ("Player history", ("sampled_at", "boot_id", "online_players", "player_count", "session_counts", "last_log_id"), ("sampled_at",)),
    "worker_sample": ("Resource history", ("sampled_at", "ram_used_bytes", "ram_available_bytes", "game_boot_id", "game_uptime_seconds"), ("sampled_at",)),
}


async def catalog():
    return {"tables": [{"name": name, "label": details[0], "columns": details[1]} for name, details in TABLES.items()]}


async def records(request: Request, table: str, page: Annotated[int, Query(ge=0, le=100000)] = 0):
    if table not in TABLES:
        raise HTTPException(404, "Unknown server data table")
    _, columns, order = TABLES[table]
    query = sql.SQL("SELECT {} FROM public.{} ORDER BY {} LIMIT 51 OFFSET %s").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table),
        sql.SQL(", ").join(sql.SQL("{} DESC").format(sql.Identifier(key)) for key in order),
    )
    async with request.app.state.pool.connection() as conn:
        async with conn.transaction():
            await conn.execute("SET TRANSACTION READ ONLY")
            result = await conn.execute(query, (page * 50,))
            rows = await result.fetchall()
    return {"table": table, "columns": columns, "rows": rows[:50], "page": page, "has_more": len(rows) > 50}
