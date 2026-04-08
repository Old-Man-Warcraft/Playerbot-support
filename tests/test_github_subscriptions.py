from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import bot.database as database_module
from bot.cogs.github import GitHubCog
from bot.database import Database


class GitHubPollerBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_repo_bootstraps_without_dispatching_history(self) -> None:
        db = MagicMock()
        db.get_github_poll_state = AsyncMock(return_value=None)
        db.set_github_poll_state = AsyncMock()

        cog = GitHubCog(bot=MagicMock(), db=db, config=SimpleNamespace(github_token=None))
        cog.gh.get = AsyncMock(
            return_value=(
                200,
                [{"id": "evt_3", "type": "PushEvent", "payload": {}}],
                {"ETag": 'W/"abc123"'},
            )
        )
        cog._dispatch_event = AsyncMock()

        await cog._poll_repo("octocat/Hello-World", subscribers=[{"channel_id": 123, "events": "push"}])

        db.set_github_poll_state.assert_awaited_once_with(
            "octocat/Hello-World",
            "events",
            "evt_3",
            'W/"abc123"',
        )
        cog._dispatch_event.assert_not_awaited()


class GitHubSubscriptionCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._original_db_path = database_module.DB_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        database_module.DB_PATH = f"{self._tmpdir.name}/test.db"
        self.db = Database()
        await self.db.setup()

    async def asyncTearDown(self) -> None:
        if self.db._db is not None:
            await self.db._db.close()
        database_module.DB_PATH = self._original_db_path
        self._tmpdir.cleanup()

    async def test_remove_last_subscription_clears_poll_state(self) -> None:
        await self.db.add_github_subscription(1, 10, "owner/repo", "push", 42)
        await self.db.set_github_poll_state("owner/repo", "events", "evt_1", 'W/"etag"')

        removed = await self.db.remove_github_subscription(1, 10, "owner/repo")

        self.assertTrue(removed)
        self.assertIsNone(await self.db.get_github_poll_state("owner/repo", "events"))

    async def test_remove_subscription_keeps_poll_state_when_repo_still_has_subscribers(self) -> None:
        await self.db.add_github_subscription(1, 10, "owner/repo", "push", 42)
        await self.db.add_github_subscription(2, 11, "owner/repo", "push", 43)
        await self.db.set_github_poll_state("owner/repo", "events", "evt_1", 'W/"etag"')

        removed = await self.db.remove_github_subscription(1, 10, "owner/repo")

        self.assertTrue(removed)
        self.assertIsNotNone(await self.db.get_github_poll_state("owner/repo", "events"))


if __name__ == "__main__":
    unittest.main()