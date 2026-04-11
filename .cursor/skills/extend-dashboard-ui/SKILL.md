---
name: extend-dashboard-ui
description: >-
  Adds or changes FastAPI dashboard routes, Jinja templates, or static assets
  for Playerbot-support. Use when working under dashboard/ for guild settings,
  integrations, or assistant config pages.
---

# Extend dashboard

## Flow

1. Inspect `dashboard/app.py` for how routers are registered and which services (`Config`, `ModelDiscoveryService`, `DynamicConfigSchema`) are passed in.
2. Add or extend a module under `dashboard/routes/` using the **`init(templates, …)` → APIRouter** pattern used by sibling modules.
3. Reuse **`dashboard/helpers.py`** for session-backed requests, guild authorization, and DB helpers.

## UI

- Templates live in `dashboard/templates/`; static JS/CSS in `dashboard/static/`.
- Match existing layout and naming so navigation and partials stay coherent.

## Security

- Every guild-scoped handler must enforce **`require_guild_access`** (or equivalent) before reads/writes.
- Never expose raw `SESSION_SECRET` or bot tokens to templates or JSON responses.

## After changes

- Restart **`python main.py`** (dashboard thread does not auto-reload).
