"""Ticket panel copy and Discord message components — shared by bot cog and dashboard."""

from __future__ import annotations

DEFAULT_TITLE = "🎫 Support Tickets"
DEFAULT_DESCRIPTION = (
    "Need help?  Click the button below to open a private support ticket.\n\n"
    "A staff member will be with you shortly."
)
DEFAULT_FOOTER = "One open ticket per user at a time."


def resolve_ticket_panel_copy(cfg: dict[str, str | None]) -> tuple[str, str, str]:
    """Return (title, description, footer) with Discord size limits applied."""
    title = (cfg.get("ticket_panel_title") or "").strip() or DEFAULT_TITLE
    desc = (cfg.get("ticket_panel_description") or "").strip() or DEFAULT_DESCRIPTION
    foot = (cfg.get("ticket_panel_footer") or "").strip() or DEFAULT_FOOTER
    return title[:256], desc[:4096], foot[:2048]


def ticket_panel_message_components() -> list[dict]:
    """Action row + button matching ``TicketPanelView`` in ``bot.cogs.tickets``."""
    return [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 1,
                    "label": "🎫 Open Ticket",
                    "custom_id": "ticket_panel:open",
                }
            ],
        }
    ]
