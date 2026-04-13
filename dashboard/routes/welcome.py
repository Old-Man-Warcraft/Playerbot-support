"""Welcome routes: /welcome and /welcome/save."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from dashboard.helpers import (
    auth_redirect,
    ctx,
    db_execute,
    get_authorized_guilds,
    get_guild_config_map,
    require_guild_access,
)

router = APIRouter()


def init(templates: Jinja2Templates) -> APIRouter:
    @router.get("/welcome", response_class=HTMLResponse)
    async def welcome_page(request: Request, guild_id: int | None = None):
        if r := auth_redirect(request):
            return r

        guilds = await get_authorized_guilds(request, guild_id)
        config_values: dict = {}

        if guild_id:
            config_values = await get_guild_config_map(guild_id)

        return templates.TemplateResponse(request, "welcome.html", ctx({
            "guilds": guilds,
            "guild_id": guild_id,
            "config_values": config_values,
            "active_page": "welcome",
        }))

    @router.post("/welcome/save")
    async def welcome_save(
        request: Request,
        guild_id: int = Form(...),
        welcome_channel: str = Form(""),
        welcome_message: str = Form(""),
        autorole: str = Form(""),
        verified_role: str = Form(""),
    ):
        if r := auth_redirect(request):
            return r
        await require_guild_access(request, guild_id)

        settings = {
            "welcome_channel": welcome_channel.strip(),
            "welcome_message": welcome_message.strip(),
            "autorole": autorole.strip(),
            "verified_role": verified_role.strip(),
        }

        for key, value in settings.items():
            if value:
                await db_execute(
                    "INSERT INTO guild_config (guild_id, key, value) VALUES (?, ?, ?) "
                    "ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value",
                    (guild_id, key, value),
                )
            else:
                await db_execute(
                    "DELETE FROM guild_config WHERE guild_id = ? AND key = ?",
                    (guild_id, key),
                )

        return RedirectResponse(f"/welcome?guild_id={guild_id}", status_code=302)

    return router
