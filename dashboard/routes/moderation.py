"""Moderation routes: /moderation, /warnings, /tickets, /automod."""

from __future__ import annotations

import logging
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bot.ticket_panel import resolve_ticket_panel_copy, ticket_panel_message_components

from dashboard.helpers import (
    DISCORD_API_BASE,
    auth_redirect,
    ctx,
    db_execute,
    db_fetchall,
    db_fetchone,
    get_authorized_guilds,
    get_guild_config_map,
    require_guild_access,
)

logger = logging.getLogger(__name__)

_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

_TICKET_SETUP_KEYS = (
    "ticket_category",
    "ticket_staff_roles",
    "ticket_panel_title",
    "ticket_panel_description",
    "ticket_panel_footer",
)


def _ticket_panel_embed_api_dict(cfg: dict[str, str]) -> dict:
    sub = {k: cfg.get(k) for k in ("ticket_panel_title", "ticket_panel_description", "ticket_panel_footer")}
    title, description, footer = resolve_ticket_panel_copy(sub)
    return {
        "title": title,
        "description": description,
        "color": 0x5865F2,
        "footer": {"text": footer},
    }

router = APIRouter()


def init(templates: Jinja2Templates) -> APIRouter:
    # ── Moderation cases ───────────────────────────────────────────────

    @router.get("/moderation", response_class=HTMLResponse)
    async def moderation_page(request: Request, guild_id: int | None = None, user_id: int | None = None, page: int = 1):
        if r := auth_redirect(request):
            return r

        guilds = await get_authorized_guilds(request, guild_id)
        per_page = 25
        offset = (page - 1) * per_page
        cases = []
        total = 0

        if guild_id:
            if user_id:
                total_row = await db_fetchone("SELECT COUNT(*) as c FROM mod_cases WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
                total = total_row["c"] if total_row else 0
                cases = await db_fetchall(
                    "SELECT * FROM mod_cases WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (guild_id, user_id, per_page, offset),
                )
            else:
                total_row = await db_fetchone("SELECT COUNT(*) as c FROM mod_cases WHERE guild_id = ?", (guild_id,))
                total = total_row["c"] if total_row else 0
                cases = await db_fetchall(
                    "SELECT * FROM mod_cases WHERE guild_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (guild_id, per_page, offset),
                )

        total_pages = max(1, (total + per_page - 1) // per_page)

        return templates.TemplateResponse(request, "moderation.html", ctx({
            "guilds": guilds,
            "guild_id": guild_id,
            "user_id": user_id,
            "cases": cases,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "active_page": "moderation",
        }))

    @router.post("/moderation/delete")
    async def moderation_delete(request: Request, case_id: int = Form(...), guild_id: int = Form(...)):
        if r := auth_redirect(request):
            return r
        await require_guild_access(request, guild_id)
        await db_execute("DELETE FROM mod_cases WHERE id = ? AND guild_id = ?", (case_id, guild_id))
        return RedirectResponse(f"/moderation?guild_id={guild_id}", status_code=302)

    # ── Warnings ──────────────────────────────────────────────────────

    @router.get("/warnings", response_class=HTMLResponse)
    async def warnings_page(request: Request, guild_id: int | None = None, user_id: int | None = None):
        if r := auth_redirect(request):
            return r

        guilds = await get_authorized_guilds(request, guild_id)
        warnings = []
        if guild_id:
            if user_id:
                warnings = await db_fetchall(
                    "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? AND active = 1 ORDER BY id DESC",
                    (guild_id, user_id),
                )
            else:
                warnings = await db_fetchall(
                    "SELECT * FROM warnings WHERE guild_id = ? AND active = 1 ORDER BY id DESC",
                    (guild_id,),
                )

        return templates.TemplateResponse(request, "warnings.html", ctx({
            "guilds": guilds,
            "guild_id": guild_id,
            "user_id": user_id,
            "warnings": warnings,
            "active_page": "warnings",
        }))

    @router.post("/warnings/delete")
    async def warning_delete(request: Request, warning_id: int = Form(...), guild_id: int = Form(...)):
        if r := auth_redirect(request):
            return r
        await require_guild_access(request, guild_id)
        await db_execute("UPDATE warnings SET active = 0 WHERE id = ? AND guild_id = ?", (warning_id, guild_id))
        return RedirectResponse(f"/warnings?guild_id={guild_id}", status_code=302)

    # ── Tickets ───────────────────────────────────────────────────────

    @router.get("/tickets", response_class=HTMLResponse)
    async def tickets_page(
        request: Request,
        guild_id: int | None = None,
        status: str = "open",
        ticket_saved: int | None = None,
        panel_ok: int | None = None,
        panel_err: str | None = None,
    ):
        if r := auth_redirect(request):
            return r

        guilds = await get_authorized_guilds(request, guild_id)
        tickets = []
        ticket_config: dict[str, str] = {}
        if guild_id:
            if status == "all":
                tickets = await db_fetchall(
                    "SELECT * FROM tickets WHERE guild_id = ? ORDER BY id DESC",
                    (guild_id,),
                )
            else:
                tickets = await db_fetchall(
                    "SELECT * FROM tickets WHERE guild_id = ? AND status = ? ORDER BY id DESC",
                    (guild_id, status),
                )
            full_cfg = await get_guild_config_map(guild_id)
            ticket_config = {k: full_cfg.get(k, "") for k in _TICKET_SETUP_KEYS}

        return templates.TemplateResponse(request, "tickets.html", ctx({
            "guilds": guilds,
            "guild_id": guild_id,
            "status": status,
            "tickets": tickets,
            "ticket_config": ticket_config,
            "ticket_saved": bool(ticket_saved),
            "panel_ok": bool(panel_ok),
            "panel_err": panel_err,
            "bot_token_configured": bool(_BOT_TOKEN),
            "active_page": "tickets",
        }))

    @router.post("/tickets/setup")
    async def tickets_setup_save(
        request: Request,
        guild_id: int = Form(...),
        ticket_category: str = Form(""),
        ticket_staff_roles: str = Form(""),
        ticket_panel_title: str = Form(""),
        ticket_panel_description: str = Form(""),
        ticket_panel_footer: str = Form(""),
    ):
        if r := auth_redirect(request):
            return r
        await require_guild_access(request, guild_id)

        settings = {
            "ticket_category": ticket_category.strip(),
            "ticket_staff_roles": ticket_staff_roles.strip(),
            "ticket_panel_title": ticket_panel_title.strip(),
            "ticket_panel_description": ticket_panel_description.strip(),
            "ticket_panel_footer": ticket_panel_footer.strip(),
        }
        for key, value in settings.items():
            if value:
                await db_execute(
                    "INSERT INTO guild_config (guild_id, key, value) VALUES (?, ?, ?) "
                    "ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value",
                    (guild_id, key, value),
                )
            else:
                await db_execute("DELETE FROM guild_config WHERE guild_id = ? AND key = ?", (guild_id, key))

        return RedirectResponse(f"/tickets?guild_id={guild_id}&ticket_saved=1", status_code=302)

    @router.post("/tickets/post-panel")
    async def tickets_post_panel(request: Request, guild_id: int = Form(...), channel_id: str = Form("")):
        if r := auth_redirect(request):
            return r
        await require_guild_access(request, guild_id)

        def _redirect_err(msg: str) -> RedirectResponse:
            return RedirectResponse(
                f"/tickets?guild_id={guild_id}&panel_err={quote(msg, safe='')}",
                status_code=302,
            )

        if not _BOT_TOKEN:
            return _redirect_err("DISCORD_BOT_TOKEN is not set; the dashboard cannot post to Discord.")

        raw_ch = channel_id.strip()
        try:
            ch_int = int(raw_ch)
        except ValueError:
            return _redirect_err("Channel ID must be a numeric Discord channel ID.")

        headers = {"Authorization": f"Bot {_BOT_TOKEN}"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                ch_resp = await client.get(f"{DISCORD_API_BASE}/channels/{ch_int}", headers=headers)
                if ch_resp.status_code != 200:
                    return _redirect_err("Could not read that channel (check ID and bot access).")
                ch_data = ch_resp.json()
                if int(ch_data.get("guild_id") or 0) != guild_id:
                    return _redirect_err("That channel does not belong to the selected server.")
                ch_type = ch_data.get("type")
                if ch_type == 15:
                    return _redirect_err("Use a text or announcement channel, not a forum channel.")
                if ch_type not in (0, 5):
                    return _redirect_err("Channel must be a text or announcement channel.")

                full_cfg = await get_guild_config_map(guild_id)
                embed = _ticket_panel_embed_api_dict(full_cfg)
                payload = {
                    "embeds": [embed],
                    "components": ticket_panel_message_components(),
                }
                msg_resp = await client.post(
                    f"{DISCORD_API_BASE}/channels/{ch_int}/messages",
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                )
                if msg_resp.status_code not in (200, 201):
                    logger.error("Ticket panel post failed: %s %s", msg_resp.status_code, msg_resp.text)
                    return _redirect_err("Discord rejected the message (permissions or rate limit).")
        except Exception as exc:
            logger.exception("tickets_post_panel: %s", exc)
            return _redirect_err("Unexpected error while contacting Discord.")

        return RedirectResponse(f"/tickets?guild_id={guild_id}&panel_ok=1", status_code=302)

    @router.get("/tickets/{ticket_id}/transcript", response_class=HTMLResponse)
    async def ticket_transcript(request: Request, ticket_id: int):
        if r := auth_redirect(request):
            return r

        ticket = await db_fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket:
            raise HTTPException(404, "Ticket not found")
        await require_guild_access(request, int(ticket["guild_id"]))
        messages = await db_fetchall(
            "SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        )

        return templates.TemplateResponse(request, "ticket_transcript.html", ctx({
            "ticket": ticket,
            "messages": messages,
            "active_page": "tickets",
        }))

    # ── Auto-mod ──────────────────────────────────────────────────────

    @router.get("/automod", response_class=HTMLResponse)
    async def automod_page(request: Request, guild_id: int | None = None):
        if r := auth_redirect(request):
            return r

        guilds = await get_authorized_guilds(request, guild_id)
        filters = []
        if guild_id:
            filters = await db_fetchall(
                "SELECT * FROM automod_filters WHERE guild_id = ? ORDER BY filter_type, pattern",
                (guild_id,),
            )

        return templates.TemplateResponse(request, "automod.html", ctx({
            "guilds": guilds,
            "guild_id": guild_id,
            "filters": filters,
            "active_page": "automod",
        }))

    @router.post("/automod/add")
    async def automod_add(request: Request, guild_id: int = Form(...), filter_type: str = Form(...), pattern: str = Form(...)):
        if r := auth_redirect(request):
            return r
        await require_guild_access(request, guild_id)
        try:
            await db_execute(
                "INSERT OR IGNORE INTO automod_filters (guild_id, filter_type, pattern) VALUES (?, ?, ?)",
                (guild_id, filter_type, pattern),
            )
        except Exception:
            pass
        return RedirectResponse(f"/automod?guild_id={guild_id}", status_code=302)

    @router.post("/automod/delete")
    async def automod_delete(request: Request, filter_id: int = Form(...), guild_id: int = Form(...)):
        if r := auth_redirect(request):
            return r
        await require_guild_access(request, guild_id)
        await db_execute("DELETE FROM automod_filters WHERE id = ? AND guild_id = ?", (filter_id, guild_id))
        return RedirectResponse(f"/automod?guild_id={guild_id}", status_code=302)

    return router
