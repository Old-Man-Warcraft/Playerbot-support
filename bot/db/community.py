"""Repository: levels, giveaways, polls, reminders, starboard_messages, highlights, selfroles tables."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite


class CommunityRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    # ── Self-roles ────────────────────────────────────────────────────

    async def add_selfrole(self, guild_id: int, role_id: int) -> bool:
        try:
            await self._conn.execute(
                "INSERT INTO selfroles (guild_id, role_id) VALUES (?, ?)",
                (guild_id, role_id),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_selfrole(self, guild_id: int, role_id: int) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM selfroles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def get_selfroles(self, guild_id: int) -> list[int]:
        cur = await self._conn.execute(
            "SELECT role_id FROM selfroles WHERE guild_id = ?", (guild_id,)
        )
        rows = await cur.fetchall()
        return [r["role_id"] for r in rows]

    # ── Leveling / XP ─────────────────────────────────────────────────

    async def get_level_row(self, guild_id: int, user_id: int):
        cur = await self._conn.execute(
            "SELECT * FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone()

    async def ensure_level_row(self, guild_id: int, user_id: int) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO levels (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id),
        )
        await self._conn.commit()

    async def add_xp(self, guild_id: int, user_id: int, amount: int, last_xp_at: str) -> dict:
        await self.ensure_level_row(guild_id, user_id)
        await self._conn.execute(
            "UPDATE levels SET xp = xp + ?, last_xp_at = ? WHERE guild_id = ? AND user_id = ?",
            (amount, last_xp_at, guild_id, user_id),
        )
        await self._conn.commit()
        row = await self.get_level_row(guild_id, user_id)
        return dict(row)

    async def set_level(self, guild_id: int, user_id: int, level: int) -> None:
        await self._conn.execute(
            "UPDATE levels SET level = ? WHERE guild_id = ? AND user_id = ?",
            (level, guild_id, user_id),
        )
        await self._conn.commit()

    async def set_xp(self, guild_id: int, user_id: int, xp: int, level: int) -> None:
        await self.ensure_level_row(guild_id, user_id)
        await self._conn.execute(
            "UPDATE levels SET xp = ?, level = ? WHERE guild_id = ? AND user_id = ?",
            (xp, level, guild_id, user_id),
        )
        await self._conn.commit()

    async def get_level_leaderboard(self, guild_id: int, limit: int = 10):
        cur = await self._conn.execute(
            "SELECT user_id, xp, level FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()

    async def get_level_rank(self, guild_id: int, user_id: int) -> int:
        cur = await self._conn.execute(
            "SELECT COUNT(*) FROM levels WHERE guild_id = ? AND xp > "
            "(SELECT xp FROM levels WHERE guild_id = ? AND user_id = ?)",
            (guild_id, guild_id, user_id),
        )
        row = await cur.fetchone()
        return (row[0] + 1) if row else 1

    async def reset_levels(self, guild_id: int) -> int:
        cur = await self._conn.execute("DELETE FROM levels WHERE guild_id = ?", (guild_id,))
        await self._conn.commit()
        return cur.rowcount

    # ── Giveaways ─────────────────────────────────────────────────────

    async def create_giveaway(
        self,
        guild_id: int,
        channel_id: int,
        prize: str,
        end_time: str,
        winner_count: int,
        host_id: int,
    ) -> int:
        start_time = datetime.now(timezone.utc).isoformat()
        cur = await self._conn.execute(
            "INSERT INTO giveaways (guild_id, channel_id, prize, start_time, end_time, winner_count, host_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, prize, start_time, end_time, winner_count, host_id),
        )
        await self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def set_giveaway_message(self, giveaway_id: int, message_id: int) -> None:
        await self._conn.execute(
            "UPDATE giveaways SET message_id = ? WHERE id = ?",
            (message_id, giveaway_id),
        )
        await self._conn.commit()

    async def get_giveaway(self, giveaway_id: int):
        cur = await self._conn.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
        return await cur.fetchone()

    async def get_active_giveaways(self, guild_id: int | None = None):
        if guild_id:
            cur = await self._conn.execute(
                "SELECT * FROM giveaways WHERE status = 'active' AND guild_id = ?", (guild_id,)
            )
        else:
            cur = await self._conn.execute("SELECT * FROM giveaways WHERE status = 'active'")
        return await cur.fetchall()

    async def end_giveaway(self, giveaway_id: int) -> None:
        await self._conn.execute(
            "UPDATE giveaways SET status = 'ended' WHERE id = ?", (giveaway_id,)
        )
        await self._conn.commit()

    async def set_giveaway_winners(self, giveaway_id: int, user_ids: list[int] | None) -> None:
        """Persist winner Discord user IDs as JSON array; ``None`` clears the column."""
        payload = json.dumps(user_ids) if user_ids is not None else None
        await self._conn.execute(
            "UPDATE giveaways SET winner_user_ids = ? WHERE id = ?",
            (payload, giveaway_id),
        )
        await self._conn.commit()

    async def enter_giveaway(self, giveaway_id: int, user_id: int) -> bool:
        try:
            await self._conn.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
                (giveaway_id, user_id),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def leave_giveaway(self, giveaway_id: int, user_id: int) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def get_giveaway_entries(self, giveaway_id: int) -> list[int]:
        cur = await self._conn.execute(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        )
        rows = await cur.fetchall()
        return [r["user_id"] for r in rows]

    async def get_giveaway_entry_count(self, giveaway_id: int) -> int:
        cur = await self._conn.execute(
            "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else 0

    # ── Polls ──────────────────────────────────────────────────────────

    async def create_poll(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        creator_id: int,
        question: str,
        options: list[str],
        multiple_choice: bool = False,
        anonymous: bool = False,
        ends_at: str | None = None,
    ) -> bool:
        try:
            await self._conn.execute(
                "INSERT INTO polls (guild_id, channel_id, message_id, creator_id, question, options, multiple_choice, anonymous, ends_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    guild_id,
                    channel_id,
                    message_id,
                    creator_id,
                    question,
                    json.dumps(options),
                    int(multiple_choice),
                    int(anonymous),
                    ends_at,
                ),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def get_poll(self, guild_id: int, message_id: int):
        cur = await self._conn.execute(
            "SELECT * FROM polls WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )
        return await cur.fetchone()

    async def get_polls(self, guild_id: int, active_only: bool = False):
        if active_only:
            cur = await self._conn.execute(
                "SELECT * FROM polls WHERE guild_id = ? AND (ends_at IS NULL OR ends_at > datetime('now')) "
                "ORDER BY created_at DESC",
                (guild_id,),
            )
        else:
            cur = await self._conn.execute(
                "SELECT * FROM polls WHERE guild_id = ? ORDER BY created_at DESC",
                (guild_id,),
            )
        return await cur.fetchall()

    async def delete_poll(self, guild_id: int, message_id: int) -> bool:
        poll = await self.get_poll(guild_id, message_id)
        if not poll:
            return False
        await self._conn.execute("DELETE FROM poll_votes WHERE poll_id = ?", (poll["id"],))
        cur = await self._conn.execute(
            "DELETE FROM polls WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def add_poll_vote(self, poll_id: int, user_id: int, option_index: int) -> bool:
        try:
            await self._conn.execute(
                "INSERT INTO poll_votes (poll_id, user_id, option_index) VALUES (?, ?, ?)",
                (poll_id, user_id, option_index),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_poll_vote(self, poll_id: int, user_id: int, option_index: int) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM poll_votes WHERE poll_id = ? AND user_id = ? AND option_index = ?",
            (poll_id, user_id, option_index),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def get_user_poll_votes(self, poll_id: int, user_id: int) -> list[int]:
        cur = await self._conn.execute(
            "SELECT option_index FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id),
        )
        rows = await cur.fetchall()
        return [row["option_index"] for row in rows]

    async def get_poll_results(self, poll_id: int):
        cur = await self._conn.execute(
            "SELECT option_index, COUNT(*) as votes FROM poll_votes WHERE poll_id = ? "
            "GROUP BY option_index ORDER BY option_index",
            (poll_id,),
        )
        return await cur.fetchall()

    async def clear_user_poll_votes(self, poll_id: int, user_id: int) -> int:
        cur = await self._conn.execute(
            "DELETE FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id),
        )
        await self._conn.commit()
        return cur.rowcount

    # ── Reminders ─────────────────────────────────────────────────────

    async def create_reminder(
        self,
        user_id: int,
        message: str,
        end_time: str,
        guild_id: int | None = None,
        channel_id: int | None = None,
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO reminders (user_id, guild_id, channel_id, message, end_time) VALUES (?, ?, ?, ?, ?)",
            (user_id, guild_id, channel_id, message, end_time),
        )
        await self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def get_due_reminders(self, now: str):
        cur = await self._conn.execute(
            "SELECT * FROM reminders WHERE end_time <= ? ORDER BY end_time",
            (now,),
        )
        return await cur.fetchall()

    async def delete_reminder(self, reminder_id: int) -> None:
        await self._conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        await self._conn.commit()

    async def get_user_reminders(self, user_id: int) -> list:
        cur = await self._conn.execute(
            "SELECT * FROM reminders WHERE user_id = ? ORDER BY end_time",
            (user_id,),
        )
        return await cur.fetchall()

    # ── Starboard ─────────────────────────────────────────────────────

    async def get_starboard_message(self, message_id: int):
        cur = await self._conn.execute(
            "SELECT * FROM starboard_messages WHERE message_id = ?", (message_id,)
        )
        return await cur.fetchone()

    async def upsert_starboard_message(
        self,
        message_id: int,
        guild_id: int,
        channel_id: int,
        author_id: int,
        star_count: int,
        starboard_msg_id: int | None = None,
    ) -> None:
        await self._conn.execute(
            "INSERT INTO starboard_messages (message_id, guild_id, channel_id, author_id, star_count, starboard_msg_id) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(message_id) DO UPDATE SET "
            "star_count = excluded.star_count, starboard_msg_id = COALESCE(excluded.starboard_msg_id, starboard_msg_id)",
            (message_id, guild_id, channel_id, author_id, star_count, starboard_msg_id),
        )
        await self._conn.commit()

    async def set_starboard_msg_id(self, message_id: int, starboard_msg_id: int) -> None:
        await self._conn.execute(
            "UPDATE starboard_messages SET starboard_msg_id = ? WHERE message_id = ?",
            (starboard_msg_id, message_id),
        )
        await self._conn.commit()

    async def delete_starboard_message(self, message_id: int) -> None:
        await self._conn.execute(
            "DELETE FROM starboard_messages WHERE message_id = ?", (message_id,)
        )
        await self._conn.commit()

    # ── Highlights ────────────────────────────────────────────────────

    async def add_highlight(self, user_id: int, guild_id: int, keyword: str) -> bool:
        try:
            await self._conn.execute(
                "INSERT INTO highlights (user_id, guild_id, keyword) VALUES (?, ?, ?)",
                (user_id, guild_id, keyword.lower()),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_highlight(self, user_id: int, guild_id: int, keyword: str) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM highlights WHERE user_id = ? AND guild_id = ? AND keyword = ?",
            (user_id, guild_id, keyword.lower()),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def get_user_highlights(self, user_id: int, guild_id: int) -> list[str]:
        cur = await self._conn.execute(
            "SELECT keyword FROM highlights WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        rows = await cur.fetchall()
        return [r["keyword"] for r in rows]

    async def get_guild_highlights(self, guild_id: int):
        cur = await self._conn.execute(
            "SELECT user_id, keyword FROM highlights WHERE guild_id = ?", (guild_id,)
        )
        return await cur.fetchall()

    async def clear_user_highlights(self, user_id: int, guild_id: int) -> int:
        cur = await self._conn.execute(
            "DELETE FROM highlights WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        await self._conn.commit()
        return cur.rowcount
