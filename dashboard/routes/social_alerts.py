"""Dashboard routes for social and stream alerts."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bot.social_alert_utils import (
    SOCIAL_ALERT_PLATFORM_LABELS,
    default_social_alert_template,
    normalize_twitch_account,
    normalize_youtube_account,
)
from dashboard.helpers import auth_redirect, ctx, db_execute, db_fetchall, get_authorized_guilds, require_guild_access

router = APIRouter()


def _redirect_with_flash(guild_id: int, level: str, message: str, *, anchor: str = "") -> RedirectResponse:
    query = urlencode({"guild_id": guild_id, "flash": level, "message": message})
    location = f"/social-alerts?{query}"
    if anchor:
        location = f"{location}#{anchor}"
    return RedirectResponse(location, status_code=302)


def init(templates: Jinja2Templates, *, twitch_configured: bool, youtube_configured: bool) -> APIRouter:
    @router.get("/social-alerts", response_class=HTMLResponse)
    async def social_alerts_page(request: Request, guild_id: int | None = None):
        if redirect := auth_redirect(request):
            return redirect

        guilds = await get_authorized_guilds(request, guild_id)
        selected_guild = next((guild for guild in guilds if guild.get("guild_id") == guild_id), None)
        alerts: list[dict] = []
        stats = {"total": 0, "enabled": 0, "streams": 0, "rss": 0}
        flash: dict[str, str] | None = None

        query_params = getattr(request, "query_params", {})
        flash_level = (query_params.get("flash") or "").strip()
        flash_message = (query_params.get("message") or "").strip()
        if flash_level and flash_message:
            flash = {"level": flash_level, "message": flash_message}

        if guild_id is not None:
            alerts = await db_fetchall(
                "SELECT * FROM social_alerts WHERE guild_id = ? ORDER BY enabled DESC, platform, created_at DESC, id DESC",
                (guild_id,),
            )
            stats = {
                "total": len(alerts),
                "enabled": sum(1 for alert in alerts if alert["enabled"]),
                "streams": sum(1 for alert in alerts if alert["alert_type"] == "stream"),
                "rss": sum(1 for alert in alerts if alert["platform"] == "rss"),
            }

        return templates.TemplateResponse(
            request,
            "social_alerts.html",
            ctx(
                {
                    "guilds": guilds,
                    "guild_id": guild_id,
                    "selected_guild": selected_guild,
                    "alerts": alerts,
                    "stats": stats,
                    "flash": flash,
                    "platform_labels": SOCIAL_ALERT_PLATFORM_LABELS,
                    "twitch_configured": twitch_configured,
                    "youtube_configured": youtube_configured,
                    "stream_default_template": default_social_alert_template("twitch"),
                    "rss_default_template": default_social_alert_template("rss"),
                    "active_page": "social_alerts",
                }
            ),
        )

    @router.post("/social-alerts/save")
    async def social_alerts_save(
        request: Request,
        guild_id: int = Form(...),
        channel_id: int = Form(...),
        platform: str = Form(...),
        account_id: str = Form(...),
        message_template: str = Form(""),
    ):
        if redirect := auth_redirect(request):
            return redirect
        await require_guild_access(request, guild_id)

        normalized_platform = platform.strip().lower()
        raw_account = account_id.strip()
        template = message_template.strip()
        if channel_id <= 0:
            return _redirect_with_flash(guild_id, "error", "Channel ID must be a positive Discord channel ID.", anchor="add-alert")

        if normalized_platform == "rss":
            if not raw_account.startswith(("http://", "https://")):
                return _redirect_with_flash(guild_id, "error", "RSS alerts require an http:// or https:// feed URL.", anchor="add-alert")
            normalized_account = raw_account
            alert_type = "new"
        elif normalized_platform == "twitch":
            normalized_account = normalize_twitch_account(raw_account)
            alert_type = "stream"
        elif normalized_platform == "youtube":
            normalized_account = normalize_youtube_account(raw_account)
            alert_type = "stream"
        else:
            return _redirect_with_flash(guild_id, "error", "Unsupported alert platform.", anchor="add-alert")

        if not normalized_account:
            return _redirect_with_flash(guild_id, "error", "Please provide a valid feed URL, Twitch channel, or YouTube channel.", anchor="add-alert")

        await db_execute(
            """
            INSERT INTO social_alerts (guild_id, channel_id, platform, account_id, alert_type, message_template, enabled)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(guild_id, platform, account_id, alert_type)
            DO UPDATE SET
                channel_id = excluded.channel_id,
                message_template = excluded.message_template,
                enabled = 1
            """,
            (
                guild_id,
                channel_id,
                normalized_platform,
                normalized_account,
                alert_type,
                template or default_social_alert_template(normalized_platform),
            ),
        )
        return _redirect_with_flash(guild_id, "success", f"Saved {normalized_platform} alert for {normalized_account}.", anchor="active-alerts")

    @router.post("/social-alerts/toggle")
    async def social_alerts_toggle(request: Request, guild_id: int = Form(...), alert_id: int = Form(...)):
        if redirect := auth_redirect(request):
            return redirect
        await require_guild_access(request, guild_id)

        rows = await db_fetchall(
            "SELECT enabled FROM social_alerts WHERE guild_id = ? AND id = ?",
            (guild_id, alert_id),
        )
        if not rows:
            return _redirect_with_flash(guild_id, "error", f"Alert #{alert_id} was not found.", anchor="active-alerts")

        enabled = 0 if rows[0]["enabled"] else 1
        await db_execute(
            "UPDATE social_alerts SET enabled = ? WHERE guild_id = ? AND id = ?",
            (enabled, guild_id, alert_id),
        )
        state = "enabled" if enabled else "disabled"
        return _redirect_with_flash(guild_id, "success", f"Alert #{alert_id} {state}.", anchor="active-alerts")

    @router.post("/social-alerts/delete")
    async def social_alerts_delete(request: Request, guild_id: int = Form(...), alert_id: int = Form(...)):
        if redirect := auth_redirect(request):
            return redirect
        await require_guild_access(request, guild_id)

        await db_execute(
            "DELETE FROM social_alerts WHERE guild_id = ? AND id = ?",
            (guild_id, alert_id),
        )
        return _redirect_with_flash(guild_id, "success", f"Deleted alert #{alert_id}.", anchor="active-alerts")

    return router