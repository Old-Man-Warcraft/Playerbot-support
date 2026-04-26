"""Shared helpers for social and stream alert targets."""

from __future__ import annotations

from urllib.parse import urlparse


SOCIAL_ALERT_PLATFORM_LABELS: dict[str, str] = {
    "rss": "RSS",
    "twitch": "Twitch",
    "youtube": "YouTube",
}


def format_social_alert_platform(platform: str) -> str:
    return SOCIAL_ALERT_PLATFORM_LABELS.get(platform.lower(), platform.title())


def normalize_twitch_account(account: str) -> str:
    raw = account.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        path = urlparse(raw).path.strip("/")
        raw = path.split("/", 1)[0] if path else raw
    return raw.lstrip("@").strip().lower()


def normalize_youtube_account(account: str) -> str:
    raw = account.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        path = urlparse(raw).path.strip("/")
        parts = [part for part in path.split("/") if part]
        if parts:
            if parts[0] == "channel" and len(parts) > 1:
                return parts[1]
            if parts[0] in {"c", "user"} and len(parts) > 1:
                return parts[1]
            if parts[0].startswith("@"):
                return parts[0]
    return raw


def default_social_alert_template(platform: str) -> str:
    normalized = platform.strip().lower()
    if normalized == "twitch":
        return "🔴 **{creator}** is live on Twitch: **{title}**\n{link}"
    if normalized == "youtube":
        return "🔴 **{creator}** is live on YouTube: **{title}**\n{link}"
    return "📰 **{title}**\n{link}"