---
name: assistant-rag-change
description: >-
  Modifies AI assistant behaviour, embeddings, Qdrant usage, crawling, or
  LLMService in Playerbot-support. Use when editing bot/cogs/support.py,
  bot/llm_service.py, bot/qdrant_service.py, or embedding-related dashboard
  routes.
---

# Assistant & RAG changes

## Read first

- `bot/llm_service.py` — chat, embeddings, images, compaction.
- `bot/qdrant_service.py` — collections `embeddings_{guild_id}`, `facts_{guild_id}`.
- `bot/cogs/support.py` — triggers, memory, tool calls, feedback.
- `README.md` (AI section) — user-facing behaviour to keep aligned.

## Rules of thumb

- **Metadata in SQLite, vectors in Qdrant** — keep `qdrant_id` on rows that need vector updates or deletes.
- Changing **embedding model** or dimensions may require re-embed or migration; call out breaking changes in PR text.
- **Thresholds** (relatedness, learning) are behaviour-sensitive; prefer config keys / constants colocated with current defaults.
- Dashboard knowledge tools must stay consistent with chunk metadata the bot writes.

## Verify

- Run targeted tests: `tests/test_llm_service.py`, `tests/test_message_learning.py`, `tests/test_dashboard_knowledge.py` when relevant.
- Smoke: `/query` or dashboard knowledge page if you changed search or storage.
