"""Repository: social_alerts, social_alert_history tables."""

from __future__ import annotations

import aiosqlite


class SocialAlertsRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def add_social_alert(
        self,
        guild_id: int,
        channel_id: int,
        platform: str,
        account_id: str,
        alert_type: str,
        message_template: str,
    ) -> bool:
        try:
            await self._conn.execute(
                """INSERT INTO social_alerts
                   (guild_id, channel_id, platform, account_id, alert_type, message_template)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (guild_id, channel_id, platform, account_id, alert_type, message_template),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def get_social_alerts(self, guild_id: int) -> list:
        cur = await self._conn.execute(
            "SELECT * FROM social_alerts WHERE guild_id = ? ORDER BY id",
            (guild_id,),
        )
        return await cur.fetchall()

    async def get_all_enabled_social_alerts(self) -> list:
        cur = await self._conn.execute(
            "SELECT * FROM social_alerts WHERE enabled = 1 ORDER BY guild_id, id",
        )
        return await cur.fetchall()

    async def remove_social_alert(self, guild_id: int, alert_id: int) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM social_alerts WHERE guild_id = ? AND id = ?",
            (guild_id, alert_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def toggle_social_alert(self, guild_id: int, alert_id: int) -> bool | None:
        cur = await self._conn.execute(
            "SELECT enabled FROM social_alerts WHERE guild_id = ? AND id = ?",
            (guild_id, alert_id),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        new_val = 0 if row["enabled"] else 1
        await self._conn.execute(
            "UPDATE social_alerts SET enabled = ? WHERE guild_id = ? AND id = ?",
            (new_val, guild_id, alert_id),
        )
        await self._conn.commit()
        return bool(new_val)

    async def check_alert_history(self, alert_id: int, content_id: str) -> bool:
        cur = await self._conn.execute(
            "SELECT 1 FROM social_alert_history WHERE alert_id = ? AND content_id = ?",
            (alert_id, content_id),
        )
        return await cur.fetchone() is not None

    async def record_alert_history(self, guild_id: int, alert_id: int, content_id: str) -> None:
        try:
            await self._conn.execute(
                "INSERT INTO social_alert_history (guild_id, alert_id, content_id) VALUES (?, ?, ?)",
                (guild_id, alert_id, content_id),
            )
            await self._conn.commit()
        except aiosqlite.IntegrityError:
            pass

    async def cleanup_alert_history(self, days: int = 30) -> None:
        await self._conn.execute(
            "DELETE FROM social_alert_history WHERE sent_at < datetime('now', '-{} days')".format(days),
        )
        await self._conn.commit()
