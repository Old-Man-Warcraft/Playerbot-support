---
name: add-slash-feature
description: >-
  Adds or changes Discord slash commands, modals, buttons, or cog wiring in
  Playerbot-support. Use when extending bot/cogs, syncing commands, or touching
  ModLogging, Permissions, or persistent views.
---

# Add slash / cog feature

## Before coding

1. Read an existing cog with similar UX (`bot/cogs/tickets.py`, `bot/cogs/moderation.py`).
2. Confirm whether the feature needs **guild config** keys — if yes, add DB access in `bot/db/` and read/write via existing `guild_config` patterns.

## Implementation checklist

- [ ] Command tree: use `app_commands` on the cog `Group` or `Cog` as elsewhere in the file.
- [ ] **Defer** if the handler does I/O beyond quick DB reads.
- [ ] **Permissions:** Rely on Discord defaults plus the global check; do not duplicate deny logic in every command unless the cog already does for special cases.
- [ ] **Mod / audit:** For staff actions, log through **ModLogging** and persist cases where moderation-style tracking applies.
- [ ] **Persistence:** For buttons/menus that must survive restart, follow the same `custom_id` / `add_view` pattern as sibling features.
- [ ] After structural changes, run **`python main.py`** once to sync commands (or document if dev uses a sync helper).

## Do not

- Change cog **load order** in `main.py` without explicit reason.
- Store secrets in code or `guild_config` values.
