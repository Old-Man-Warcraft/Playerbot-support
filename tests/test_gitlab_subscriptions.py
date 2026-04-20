from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.cogs.gitlab import GitLabCog


class GitLabDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_event_fetches_channel_when_not_cached(self) -> None:
        channel = AsyncMock(spec=discord.TextChannel)
        bot = MagicMock()
        bot.get_channel.return_value = None
        bot.fetch_channel = AsyncMock(return_value=channel)

        cog = GitLabCog(
            bot=bot,
            db=MagicMock(),
            config=SimpleNamespace(gitlab_token=None, gitlab_url="https://gitlab.com"),
        )

        event = {
            "action_name": "opened",
            "target_type": "issue",
            "target_iid": 9,
            "target_title": "Broken notifications",
            "author": {"username": "octocat", "avatar_url": "https://example.com/avatar.png"},
        }

        await cog._dispatch_event(
            "group/project",
            event,
            subscribers=[{"channel_id": 456, "events": "issues"}],
        )

        bot.fetch_channel.assert_awaited_once_with(456)
        channel.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()