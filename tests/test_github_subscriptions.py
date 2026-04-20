from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

import bot.db.base as database_module
from bot.cogs.github import (
    GitHubCog,
    _build_issue_triage_embed,
    _default_issue_template,
    _issue_body,
    _review_bucket,
    _reviewer_load_lines,
    _team_load_lines,
    _should_send_review_digest,
    _summarize_reviews,
)
from bot.db import Database
from bot.github_embeds import normalize_rest_commit_for_push


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

    async def test_dispatch_event_fetches_channel_when_not_cached(self) -> None:
        channel = AsyncMock(spec=discord.TextChannel)
        bot = MagicMock()
        bot.tree = MagicMock()
        bot.tree.add_command = MagicMock()
        bot.get_channel.return_value = None
        bot.fetch_channel = AsyncMock(return_value=channel)

        cog = GitHubCog(bot=bot, db=MagicMock(), config=SimpleNamespace(github_token=None))

        event = {
            "type": "IssuesEvent",
            "payload": {
                "action": "opened",
                "issue": {
                    "number": 7,
                    "title": "Broken notifications",
                    "html_url": "https://github.com/o/r/issues/7",
                    "body": "Monitor stopped posting.",
                },
                "sender": {"login": "octocat", "avatar_url": "https://example.com/avatar.png"},
            },
        }

        await cog._dispatch_event("owner/repo", event, subscribers=[{"channel_id": 123, "events": "issues"}])

        bot.fetch_channel.assert_awaited_once_with(123)
        channel.send.assert_awaited_once()


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


class GitHubReviewHelperTests(unittest.TestCase):
    def test_summarize_reviews_uses_latest_state_per_user(self) -> None:
        reviews = [
            {
                "user": {"login": "alice"},
                "state": "COMMENTED",
                "submitted_at": "2026-04-09T09:00:00Z",
            },
            {
                "user": {"login": "alice"},
                "state": "APPROVED",
                "submitted_at": "2026-04-09T10:00:00Z",
            },
            {
                "user": {"login": "bob"},
                "state": "CHANGES_REQUESTED",
                "submitted_at": "2026-04-09T11:00:00Z",
            },
        ]

        approvals, changes_requested = _summarize_reviews(reviews)

        self.assertEqual(approvals, 1)
        self.assertTrue(changes_requested)

    def test_review_bucket_prioritizes_changes_requested(self) -> None:
        pr_data = {
            "updated_at": "2026-04-09T10:00:00Z",
            "requested_reviewers": [{"login": "charlie"}],
        }
        reviews = [
            {
                "user": {"login": "bob"},
                "state": "CHANGES_REQUESTED",
                "submitted_at": "2026-04-09T11:00:00Z",
            }
        ]

        bucket = _review_bucket(
            pr_data,
            reviews,
            stale_cutoff=datetime.now(timezone.utc) - timedelta(hours=24),
        )

        self.assertEqual(bucket, "changes_requested")

    def test_issue_body_includes_source_message_link_and_excerpt(self) -> None:
        message = SimpleNamespace(
            id=123,
            content="Button click in dashboard does nothing after login.",
            channel=SimpleNamespace(id=456),
            guild=SimpleNamespace(id=789),
            author=SimpleNamespace(display_name="Jacob"),
        )

        body = _issue_body("Dashboard button is broken", "Open dashboard and click save.", message)

        self.assertIn("## Summary", body)
        self.assertIn("## Discord Context", body)
        self.assertIn("https://discord.com/channels/789/456/123", body)
        self.assertIn("Button click in dashboard does nothing after login.", body)

    def test_triage_embed_reports_unassigned_unlabeled_and_stale_counts(self) -> None:
        recent = datetime.now(timezone.utc)
        old = recent - timedelta(days=10)
        issues = [
            {
                "number": 1,
                "title": "No assignee",
                "html_url": "https://example.com/1",
                "updated_at": old.isoformat(),
                "user": {"login": "alice"},
                "assignees": [],
                "labels": [],
            },
            {
                "number": 2,
                "title": "Assigned and labeled",
                "html_url": "https://example.com/2",
                "updated_at": recent.isoformat(),
                "user": {"login": "bob"},
                "assignees": [{"login": "bob"}],
                "labels": [{"name": "bug"}],
            },
        ]

        embed = _build_issue_triage_embed("owner/repo", issues, stale_days=7)

        self.assertIn("Open issues: `2`", embed.description)
        self.assertIn("Unassigned: `1`", embed.description)
        self.assertIn("Unlabeled: `1`", embed.description)
        self.assertIn("Stale: `1`", embed.description)

    def test_should_send_review_digest_requires_scheduled_hour_and_unsent_day(self) -> None:
        now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)

        self.assertFalse(_should_send_review_digest(now, hour_utc=13, last_sent_on=None))
        self.assertTrue(_should_send_review_digest(now, hour_utc=12, last_sent_on=None))
        self.assertFalse(_should_send_review_digest(now, hour_utc=12, last_sent_on="2026-04-09"))

    def test_default_issue_template_contains_expected_sections(self) -> None:
        template = _default_issue_template("bug")

        self.assertIn("Problem summary", template)
        self.assertIn("Expected behavior", template)
        self.assertIn("Actual behavior", template)

    def test_reviewer_load_lines_summarize_pending_requests(self) -> None:
        stale_cutoff = datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc)
        queue = [
            (
                {
                    "number": 10,
                    "title": "Add review queue",
                    "updated_at": "2026-04-08T10:00:00Z",
                    "requested_reviewers": [{"login": "alice"}],
                },
                [],
            ),
            (
                {
                    "number": 11,
                    "title": "Refine digest formatting",
                    "updated_at": "2026-04-09T10:00:00Z",
                    "requested_reviewers": [{"login": "alice"}, {"login": "bob"}],
                },
                [],
            ),
        ]

        lines = _reviewer_load_lines(queue, stale_cutoff)

        self.assertEqual(len(lines), 2)
        self.assertIn("`alice`  •  2 pending", lines[0])
        self.assertIn("`bob`  •  1 pending", lines[1])

    def test_team_load_lines_summarize_requested_teams(self) -> None:
        stale_cutoff = datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc)
        queue = [
            (
                {
                    "number": 12,
                    "title": "Add deployment docs",
                    "updated_at": "2026-04-08T10:00:00Z",
                    "requested_reviewers": [],
                    "requested_teams": [{"slug": "docs"}],
                },
                [],
            ),
            (
                {
                    "number": 13,
                    "title": "Refactor CI",
                    "updated_at": "2026-04-09T10:00:00Z",
                    "requested_reviewers": [],
                    "requested_teams": [{"slug": "docs"}, {"slug": "platform"}],
                },
                [],
            ),
        ]

        lines = _team_load_lines(queue, stale_cutoff)

        self.assertEqual(len(lines), 2)
        self.assertIn("`docs`  •  2 pending", lines[0])
        self.assertIn("`platform`  •  1 pending", lines[1])


class GitHubPushEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_rest_commit_maps_compare_entry(self) -> None:
        raw = {
            "sha": "abc123def456",
            "html_url": "https://github.com/o/r/commit/abc123def456",
            "commit": {
                "message": "fix: thing\n\nbody",
                "author": {"name": "Pat", "email": "p@example.com", "date": "2026-01-01T00:00:00Z"},
                "committer": {"name": "Pat", "email": "p@example.com"},
            },
            "author": {"login": "patlee"},
        }
        out = normalize_rest_commit_for_push(raw)
        self.assertEqual(out["id"], raw["sha"])
        self.assertEqual(out["message"], raw["commit"]["message"])
        self.assertEqual(out["author"]["login"], "patlee")
        self.assertTrue(str(out["url"]).startswith("https://github.com"))

    async def test_enrich_push_payload_fetches_compare_when_events_payload_empty_commits(self) -> None:
        cog = GitHubCog(bot=MagicMock(), db=MagicMock(), config=SimpleNamespace(github_token="t"))
        compare_commit = {
            "sha": "111",
            "html_url": "https://github.com/o/r/commit/111",
            "commit": {"message": "one", "author": {"name": "A"}},
            "author": {"login": "a"},
        }
        cog.gh.get = AsyncMock(
            return_value=(
                200,
                {"commits": [compare_commit]},
                {},
            )
        )
        payload = {
            "before": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "after": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "head": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "commits": [],
            "ref": "refs/heads/main",
        }
        out = await cog._enrich_push_payload("o/r", payload)
        cog.gh.get.assert_awaited_once()
        self.assertEqual(len(out["commits"]), 1)
        self.assertEqual(out["commits"][0]["message"], "one")
        self.assertEqual(out["head_commit"]["sha"], "111")

    async def test_enrich_push_payload_skips_api_when_commits_present(self) -> None:
        cog = GitHubCog(bot=MagicMock(), db=MagicMock(), config=SimpleNamespace(github_token=None))
        cog.gh.get = AsyncMock()
        payload = {"commits": [{"id": "x", "message": "m"}], "before": "a", "after": "b"}
        out = await cog._enrich_push_payload("o/r", payload)
        cog.gh.get.assert_not_awaited()
        self.assertEqual(out["commits"][0]["message"], "m")


class GitHubTemplateAssigneeTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_issue_template_assignees_parses_csv(self) -> None:
        db = MagicMock()
        db.get_guild_config = AsyncMock(return_value="octocat, maintainer, octocat")

        cog = GitHubCog(bot=MagicMock(), db=db, config=SimpleNamespace(github_token=None))
        assignees = await cog._get_issue_template_assignees(1, "bug")

        self.assertEqual(assignees, ["maintainer", "octocat"])

    async def test_get_issue_template_milestone_parses_numeric_value(self) -> None:
        db = MagicMock()
        db.get_guild_config = AsyncMock(return_value="12")

        cog = GitHubCog(bot=MagicMock(), db=db, config=SimpleNamespace(github_token=None))
        milestone = await cog._get_issue_template_milestone(1, "bug")

        self.assertEqual(milestone, 12)

    async def test_get_issue_template_milestone_ignores_invalid_value(self) -> None:
        db = MagicMock()
        db.get_guild_config = AsyncMock(return_value="release-one")

        cog = GitHubCog(bot=MagicMock(), db=db, config=SimpleNamespace(github_token=None))
        milestone = await cog._get_issue_template_milestone(1, "bug")

        self.assertIsNone(milestone)


if __name__ == "__main__":
    unittest.main()