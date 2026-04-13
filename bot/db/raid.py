"""Repository: raid_settings, raid_events, join_tracking tables."""

from __future__ import annotations

import json

import aiosqlite


class RaidRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def get_raid_settings(self, guild_id: int):
        cur = await self._conn.execute(
            "SELECT * FROM raid_settings WHERE guild_id = ?",
            (guild_id,),
        )
        return await cur.fetchone()

    async def update_raid_settings(
        self,
        guild_id: int,
        *,
        enabled: bool | None = None,
        join_threshold: int | None = None,
        join_window: int | None = None,
        account_age_min: int | None = None,
        lockdown_duration: int | None = None,
        alert_channel_id: int | None = None,
        auto_ban: bool | None = None,
    ) -> bool:
        existing = await self.get_raid_settings(guild_id)
        if existing is None:
            await self._conn.execute(
                """INSERT INTO raid_settings
                (guild_id, enabled, join_threshold, join_window, account_age_min,
                 lockdown_duration, alert_channel_id, auto_ban)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    guild_id,
                    int(enabled if enabled is not None else False),
                    join_threshold if join_threshold is not None else 5,
                    join_window if join_window is not None else 60,
                    account_age_min if account_age_min is not None else 0,
                    lockdown_duration if lockdown_duration is not None else 300,
                    alert_channel_id,
                    int(auto_ban if auto_ban is not None else False),
                ),
            )
        else:
            updates: list[str] = []
            values: list[object] = []
            if enabled is not None:
                updates.append("enabled = ?")
                values.append(int(enabled))
            if join_threshold is not None:
                updates.append("join_threshold = ?")
                values.append(join_threshold)
            if join_window is not None:
                updates.append("join_window = ?")
                values.append(join_window)
            if account_age_min is not None:
                updates.append("account_age_min = ?")
                values.append(account_age_min)
            if lockdown_duration is not None:
                updates.append("lockdown_duration = ?")
                values.append(lockdown_duration)
            if alert_channel_id is not None:
                updates.append("alert_channel_id = ?")
                values.append(alert_channel_id)
            if auto_ban is not None:
                updates.append("auto_ban = ?")
                values.append(int(auto_ban))
            updates.append("updated_at = datetime('now')")
            values.append(guild_id)
            await self._conn.execute(
                f"UPDATE raid_settings SET {', '.join(updates)} WHERE guild_id = ?",
                values,
            )
        await self._conn.commit()
        return True

    async def track_join(self, guild_id: int, user_id: int, account_created: str | None = None) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO join_tracking (guild_id, user_id, account_created) VALUES (?, ?, ?)",
            (guild_id, user_id, account_created),
        )
        await self._conn.commit()

    async def get_recent_joins(self, guild_id: int, seconds: int):
        cur = await self._conn.execute(
            "SELECT user_id, joined_at, account_created FROM join_tracking "
            "WHERE guild_id = ? AND joined_at > datetime('now', '-{} seconds') "
            "ORDER BY joined_at DESC".format(seconds),
            (guild_id,),
        )
        return await cur.fetchall()

    async def cleanup_old_joins(self, guild_id: int, hours: int = 24) -> int:
        cur = await self._conn.execute(
            "DELETE FROM join_tracking WHERE guild_id = ? AND joined_at < datetime('now', '-{} hours')".format(hours),
            (guild_id,),
        )
        await self._conn.commit()
        return cur.rowcount

    async def create_raid_event(
        self,
        guild_id: int,
        join_count: int,
        window_seconds: int,
        actions_taken: list[str],
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO raid_events (guild_id, join_count, window_seconds, actions_taken) "
            "VALUES (?, ?, ?, ?)",
            (guild_id, join_count, window_seconds, json.dumps(actions_taken)),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_raid_events(self, guild_id: int, limit: int = 10):
        cur = await self._conn.execute(
            "SELECT * FROM raid_events WHERE guild_id = ? ORDER BY triggered_at DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()

    async def resolve_raid_event(self, guild_id: int, event_id: int, resolved_by: int) -> None:
        await self._conn.execute(
            "UPDATE raid_events SET resolved_at = datetime('now'), resolved_by = ? "
            "WHERE guild_id = ? AND id = ?",
            (resolved_by, guild_id, event_id),
        )
        await self._conn.commit()
