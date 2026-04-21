from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.cogs.gitlab import GitLabCog


class GitLabDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_project_bootstraps_without_dispatching_history(self) -> None:
        db = MagicMock()
        db.get_gitlab_poll_state = AsyncMock(return_value=None)
        db.set_gitlab_poll_state = AsyncMock()

        cog = GitLabCog(
            bot=MagicMock(),
            db=db,
            config=SimpleNamespace(gitlab_token=None, gitlab_url="https://gitlab.com"),
        )
        cog.gl.get = AsyncMock(return_value=(200, [{"id": "evt_3"}]))
        cog._dispatch_event = AsyncMock()

        result = await cog._poll_project("group/project", subscribers=[{"channel_id": 456, "events": "push"}])

        db.set_gitlab_poll_state.assert_awaited_once_with("group/project", "events", "evt_3")
        cog._dispatch_event.assert_not_awaited()
        self.assertEqual(result["status"], "bootstrapped")
        self.assertEqual(result["newest_id"], "evt_3")

    async def test_poll_project_reports_new_events_and_dispatch_counts(self) -> None:
        db = MagicMock()
        db.get_gitlab_poll_state = AsyncMock(return_value={"last_id": "evt_1"})
        db.set_gitlab_poll_state = AsyncMock()

        cog = GitLabCog(
            bot=MagicMock(),
            db=db,
            config=SimpleNamespace(gitlab_token=None, gitlab_url="https://gitlab.com"),
        )
        cog.gl.get = AsyncMock(
            return_value=(
                200,
                [{"id": "evt_3"}, {"id": "evt_2"}, {"id": "evt_1"}],
            )
        )
        cog._dispatch_event = AsyncMock(side_effect=[{"matched": 1, "sent": 0}, {"matched": 2, "sent": 2}])

        result = await cog._poll_project("group/project", subscribers=[{"channel_id": 456, "events": "issues"}])

        self.assertEqual(result["status"], "checked")
        self.assertEqual(result["new_events"], 2)
        self.assertEqual(result["matched_subscriptions"], 3)
        self.assertEqual(result["sent_messages"], 2)
        db.set_gitlab_poll_state.assert_awaited_once_with("group/project", "events", "evt_3")

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