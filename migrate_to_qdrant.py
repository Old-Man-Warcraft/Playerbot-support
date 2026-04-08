#!/usr/bin/env python3
"""One-time migration: embed existing knowledge base rows and push them into Qdrant.

Run once after deploying the Qdrant integration:
    python migrate_to_qdrant.py

For each row in the embeddings table that has no qdrant_id yet, this script
calls the LLM embeddings API to generate a vector, upserts it into Qdrant,
and writes the qdrant_id back to SQLite.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import aiosqlite
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/bot.db")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
EMB_MODEL = "qwen3-embedding-8b"  # fallback; per-row model used when available


async def migrate() -> None:
    from bot.qdrant_service import QdrantService

    qdrant = QdrantService()
    client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    migrated = 0
    skipped = 0
    errors = 0

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Ensure qdrant_id column exists (may not yet if migration hasn't run)
        try:
            await db.execute("ALTER TABLE embeddings ADD COLUMN qdrant_id TEXT")
            await db.commit()
        except Exception:
            pass

        rows = await (await db.execute(
            "SELECT id, guild_id, name, text, model, source_url, qdrant_id FROM embeddings"
        )).fetchall()

        print(f"Found {len(rows)} rows to check.")

        for row in rows:
            if row["qdrant_id"]:
                skipped += 1
                continue

            # Generate embedding via LLM API
            row_model = row["model"] or EMB_MODEL
            try:
                resp = await client.embeddings.create(model=row_model, input=row["text"])
                vec = resp.data[0].embedding
            except Exception as exc:
                print(f"  [error] id={row['id']} name={row['name']!r}: {exc}")
                errors += 1
                continue

            point_id = str(uuid.uuid4())
            await qdrant.upsert_embedding(
                guild_id=row["guild_id"],
                point_id=point_id,
                vector=vec,
                name=row["name"],
                text=row["text"],
                model=row["model"] or EMB_MODEL,
                source_url=row["source_url"] or "",
            )
            await db.execute(
                "UPDATE embeddings SET qdrant_id = ? WHERE id = ?",
                (point_id, row["id"]),
            )
            migrated += 1
            if migrated % 10 == 0:
                await db.commit()
                print(f"  … {migrated} migrated so far")

        await db.commit()

    print(f"\nDone. Migrated: {migrated}  Skipped (already had qdrant_id): {skipped}  Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(migrate())
