"""Repository: reaction_roles table."""

from __future__ import annotations

import aiosqlite


class ReactionRolesRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def add_reaction_role(
        self,
        guild_id: int,
        message_id: int,
        channel_id: int,
        emoji: str,
        role_id: int,
        unique_role: bool = False,
    ) -> bool:
        try:
            await self._conn.execute(
                "INSERT INTO reaction_roles (guild_id, message_id, channel_id, emoji, role_id, unique_role) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, message_id, channel_id, emoji, role_id, int(unique_role)),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def get_reaction_role(self, guild_id: int, message_id: int, emoji: str):
        cur = await self._conn.execute(
            "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (guild_id, message_id, emoji),
        )
        return await cur.fetchone()

    async def get_reaction_roles(self, guild_id: int, message_id: int | None = None):
        if message_id is not None:
            cur = await self._conn.execute(
                "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ?",
                (guild_id, message_id),
            )
        else:
            cur = await self._conn.execute(
                "SELECT * FROM reaction_roles WHERE guild_id = ? ORDER BY message_id, id",
                (guild_id,),
            )
        return await cur.fetchall()

    async def remove_reaction_role(self, guild_id: int, message_id: int, emoji: str) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (guild_id, message_id, emoji),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def remove_all_reaction_roles(self, guild_id: int, message_id: int) -> int:
        cur = await self._conn.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )
        await self._conn.commit()
        return cur.rowcount
