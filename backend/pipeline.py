"""
Full data pipeline for CF Coach
=================================
Step 1 — Fetch problems + statistics from the Codeforces API
Step 2 — Upsert every problem into PostgreSQL
Step 3 — Generate a rich description text for each problem
Step 4 — Embed the descriptions and store them in ChromaDB

Usage:
    python pipeline.py              # run full pipeline
    python pipeline.py --step 1     # run only step 1  (fetch + store)
    python pipeline.py --step 2     # run only step 2  (generate texts)
    python pipeline.py --step 3     # run only step 3  (embed into chroma)
"""

import argparse
import json
import time
import sys

import requests
from sqlalchemy import text

from config import (
    CF_API_URL,
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION_NAME,
    EMBEDDING_MODEL,
)
from models import init_db, SessionLocal, Problem


# ─────────────────────────────────────────────────────────────────────
# STEP 1 — Fetch from Codeforces API & store in PostgreSQL
# ─────────────────────────────────────────────────────────────────────
def fetch_and_store():
    """Hit the CF API, merge problems + stats, and upsert into PostgreSQL."""

    print("=" * 60)
    print("STEP 1 · Fetching data from Codeforces API …")
    print("=" * 60)

    resp = requests.get(CF_API_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "OK":
        print(f"❌  API returned status: {data.get('status')}")
        sys.exit(1)

    problems = data["result"]["problems"]
    stats = data["result"]["problemStatistics"]

    print(f"   ▸ Problems returned : {len(problems)}")
    print(f"   ▸ Statistics returned: {len(stats)}")

    # Build a lookup  { "1555A": solved_count }
    stats_map: dict[str, int] = {}
    for s in stats:
        pid = f"{s['contestId']}{s['index']}"
        stats_map[pid] = s.get("solvedCount", 0)

    # Merge
    merged: list[dict] = []
    for p in problems:
        cid = p.get("contestId")
        idx = p.get("index")
        if cid is None or idx is None:
            continue
        pid = f"{cid}{idx}"
        merged.append(
            {
                "problem_id": pid,
                "contest_id": cid,
                "index": idx,
                "name": p.get("name", ""),
                "rating": p.get("rating"),
                "tags": p.get("tags", []),
                "solved_count": stats_map.get(pid),
            }
        )

    print(f"   ▸ Merged records     : {len(merged)}")

    # ── Upsert into PostgreSQL ────────────────────────────────────────
    print("\n   ▸ Upserting into PostgreSQL …")
    init_db()

    session = SessionLocal()
    inserted, updated = 0, 0
    try:
        for rec in merged:
            existing = session.get(Problem, rec["problem_id"])
            if existing:
                existing.contest_id = rec["contest_id"]
                existing.index = rec["index"]
                existing.name = rec["name"]
                existing.rating = rec["rating"]
                existing.tags = rec["tags"]
                existing.solved_count = rec["solved_count"]
                updated += 1
            else:
                session.add(Problem(**rec))
                inserted += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(f"   ✅ Inserted {inserted}, Updated {updated} problems.\n")


# ─────────────────────────────────────────────────────────────────────
# STEP 2 — Generate description texts
# ─────────────────────────────────────────────────────────────────────

def _popularity_label(solved: int | None) -> str:
    if solved is None:
        return "an uncommon"
    if solved >= 30_000:
        return "a highly popular and well-known"
    if solved >= 10_000:
        return "a popular"
    if solved >= 3_000:
        return "a moderately popular"
    return "a niche"


def _difficulty_label(rating: int | None) -> str:
    if rating is None:
        return "an unrated"
    if rating <= 900:
        return "a beginner-friendly"
    if rating <= 1200:
        return "an easy"
    if rating <= 1600:
        return "a medium-difficulty"
    if rating <= 2000:
        return "a hard"
    if rating <= 2400:
        return "a very challenging"
    return "an expert-level"


def generate_texts():
    """Build a natural-language description for every problem and store it."""

    print("=" * 60)
    print("STEP 2 · Generating description texts …")
    print("=" * 60)

    session = SessionLocal()
    try:
        problems: list[Problem] = session.query(Problem).all()
        count = 0
        for p in problems:
            tags_str = ", ".join(p.tags) if p.tags else "general problem-solving"
            diff = _difficulty_label(p.rating)
            pop = _popularity_label(p.solved_count)
            rating_str = f" with an official difficulty rating of {p.rating}" if p.rating else ""
            solved_str = (
                f"With over {p.solved_count} successful submissions, this is {pop} problem"
                if p.solved_count
                else f"This is {pop} problem"
            )

            text = (
                f"The problem '{p.name}' (ID: {p.problem_id}) is {diff} competitive "
                f"programming challenge{rating_str}. "
                f"It focuses heavily on the following algorithmic concepts: {tags_str}. "
                f"{solved_str}, making it an excellent choice for practicing {tags_str} logic."
            )
            p.description_text = text
            count += 1

        session.commit()
        print(f"   ✅ Generated texts for {count} problems.\n")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─────────────────────────────────────────────────────────────────────
# STEP 3 — Embed descriptions and store in ChromaDB
# ─────────────────────────────────────────────────────────────────────
def embed_and_store():
    """Read description texts from PostgreSQL, embed them, push to ChromaDB."""

    print("=" * 60)
    print("STEP 3 · Embedding descriptions into ChromaDB …")
    print("=" * 60)

    import chromadb
    from chromadb.utils import embedding_functions

    # Use sentence-transformers embedding function (runs locally)
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    session = SessionLocal()
    try:
        problems: list[Problem] = (
            session.query(Problem)
            .filter(Problem.description_text.isnot(None))
            .all()
        )
        print(f"   ▸ Problems with text: {len(problems)}")

        # ChromaDB upsert in batches of 500
        BATCH = 500
        total_batches = (len(problems) + BATCH - 1) // BATCH

        for batch_idx in range(total_batches):
            start = batch_idx * BATCH
            end = start + BATCH
            batch = problems[start:end]

            ids = [p.problem_id for p in batch]
            docs = [p.description_text for p in batch]
            metas = [
                {
                    "contest_id": p.contest_id,
                    "index": p.index,
                    "name": p.name,
                    "rating": p.rating or 0,
                    "tags": ",".join(p.tags) if p.tags else "",
                    "solved_count": p.solved_count or 0,
                }
                for p in batch
            ]

            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            print(
                f"   ▸ Batch {batch_idx + 1}/{total_batches} "
                f"({len(batch)} problems) upserted."
            )

        total = collection.count()
        print(f"   ✅ ChromaDB collection '{CHROMA_COLLECTION_NAME}' now has {total} documents.\n")

    finally:
        session.close()


# ─────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="CF Coach data pipeline")
    parser.add_argument(
        "--step",
        type=int,
        choices=[1, 2, 3],
        help="Run a single step (1=fetch+store, 2=gen texts, 3=embed). "
             "Omit to run the full pipeline.",
    )
    args = parser.parse_args()

    t0 = time.time()

    if args.step is None or args.step == 1:
        fetch_and_store()
    if args.step is None or args.step == 2:
        generate_texts()
    if args.step is None or args.step == 3:
        embed_and_store()

    elapsed = time.time() - t0
    print(f"🏁 Pipeline finished in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
