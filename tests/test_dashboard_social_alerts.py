from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace

import dashboard.app as dashboard_app
import dashboard.helpers as dashboard_helpers


def _get_route_handler(path: str, method: str = "POST"):
    for route in dashboard_app.app.routes:
        if getattr(route, "path", None) == path and method.upper() in (getattr(route, "methods", set()) or set()):
            return route.endpoint
    return None


dashboard_app.social_alerts_page = _get_route_handler("/social-alerts", "GET")
dashboard_app.social_alerts_save = _get_route_handler("/social-alerts/save", "POST")
dashboard_app.social_alerts_toggle = _get_route_handler("/social-alerts/toggle", "POST")
dashboard_app.social_alerts_delete = _get_route_handler("/social-alerts/delete", "POST")
dashboard_app.db_execute = dashboard_helpers.db_execute
dashboard_app.db_fetchone = dashboard_helpers.db_fetchone
dashboard_app.db_fetchall = dashboard_helpers.db_fetchall


class DashboardSocialAlertsTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _session(guild_ids: list[int] | None = None, user_id: int = 1001) -> dict:
        return {
            "authenticated": True,
            "discord_user_id": user_id,
            "guild_access_ids": guild_ids or [],
        }

    @classmethod
    def _request(cls, guild_ids: list[int] | None = None, user_id: int = 1001):
        return SimpleNamespace(
            session=cls._session(guild_ids, user_id),
            query_params={},
            url=SimpleNamespace(path="/social-alerts"),
        )

    async def asyncSetUp(self) -> None:
        self._original_db_path = dashboard_helpers.DB_PATH
        self._tmpdir = tempfile.TemporaryDirectory()
        dashboard_helpers.DB_PATH = f"{self._tmpdir.name}/test.db"
        dashboard_app.DB_PATH = dashboard_helpers.DB_PATH

        await dashboard_app.db_execute(
            """
            CREATE TABLE IF NOT EXISTS social_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                platform TEXT NOT NULL DEFAULT 'rss',
                account_id TEXT NOT NULL,
                alert_type TEXT NOT NULL DEFAULT 'new',
                message_template TEXT NOT NULL DEFAULT '📰 **{title}**\n{link}',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(guild_id, platform, account_id, alert_type)
            )
            """
        )

    async def asyncTearDown(self) -> None:
        dashboard_helpers.DB_PATH = self._original_db_path
        dashboard_app.DB_PATH = self._original_db_path
        self._tmpdir.cleanup()

    async def test_save_route_normalizes_twitch_target_and_upserts(self) -> None:
        request = self._request([1])

        first = await dashboard_app.social_alerts_save(
            request,
            guild_id=1,
            channel_id=42,
            platform="twitch",
            account_id="https://www.twitch.tv/ExampleStreamer",
            message_template="",
        )
        second = await dashboard_app.social_alerts_save(
            request,
            guild_id=1,
            channel_id=99,
            platform="twitch",
            account_id="ExampleStreamer",
            message_template="@everyone {creator} is live",
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        rows = await dashboard_app.db_fetchall(
            "SELECT * FROM social_alerts WHERE guild_id = ?",
            (1,),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account_id"], "examplestreamer")
        self.assertEqual(rows[0]["channel_id"], 99)
        self.assertEqual(rows[0]["alert_type"], "stream")
        self.assertEqual(rows[0]["message_template"], "@everyone {creator} is live")

    async def test_toggle_and_delete_routes_manage_existing_alert(self) -> None:
        await dashboard_app.db_execute(
            "INSERT INTO social_alerts (guild_id, channel_id, platform, account_id, alert_type, message_template, enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, 11, "youtube", "@creator", "stream", "hello", 1),
        )
        request = self._request([1])

        toggle_response = await dashboard_app.social_alerts_toggle(request, guild_id=1, alert_id=1)
        row = await dashboard_app.db_fetchone("SELECT enabled FROM social_alerts WHERE id = 1", ())
        delete_response = await dashboard_app.social_alerts_delete(request, guild_id=1, alert_id=1)
        deleted = await dashboard_app.db_fetchone("SELECT * FROM social_alerts WHERE id = 1", ())

        self.assertEqual(toggle_response.status_code, 302)
        self.assertEqual(row["enabled"], 0)
        self.assertEqual(delete_response.status_code, 302)
        self.assertIsNone(deleted)

    async def test_page_lists_guild_from_social_alerts_table(self) -> None:
        await dashboard_app.db_execute(
            "INSERT INTO social_alerts (guild_id, channel_id, platform, account_id, alert_type, message_template, enabled) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (7, 11, "rss", "https://example.com/feed.xml", "new", "hello", 1),
        )
        request = self._request([7])

        response = await dashboard_app.social_alerts_page(request, guild_id=7)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stats"]["total"], 1)
        self.assertEqual(response.context["guilds"][0]["guild_id"], 7)