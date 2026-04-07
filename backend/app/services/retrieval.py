"""
Hybrid retrieval engine: combines FAISS vector similarity with SQL filtering.
Supports natural language queries like "Give me 1200 greedy problems".
"""
import re
import logging
from typing import Optional
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Problem, ProblemChunk
from app.services.embeddings import get_embedding
from app.services.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# Known Codeforces tags for query parsing
CF_TAGS = {
    "implementation", "math", "greedy", "dp", "data structures", "brute force",
    "constructive algorithms", "graphs", "sortings", "binary search", "dfs and similar",
    "trees", "strings", "number theory", "geometry", "combinatorics", "two pointers",
    "dsu", "bitmasks", "probabilities", "shortest paths", "hashing", "divide and conquer",
    "games", "matrices", "flows", "string suffix structures", "expression parsing",
    "graph matchings", "ternary search", "meet-in-the-middle", "fft", "2-sat",
    "chinese remainder theorem", "schedules", "interactive", "special",
}


def parse_query_filters(query: str) -> dict:
    """
    Parse natural language query to extract structured filters.

    Examples:
    - "Give me 1200 greedy problems" → rating=1200, tags=["greedy"]
    - "dp problems between 1500 and 1800" → tags=["dp"], rating_min=1500, rating_max=1800
    - "easy math problems" → tags=["math"], rating_max=1200
    - "hard graph problems" → tags=["graphs"], rating_min=2000
    """
    filters = {}
    query_lower = query.lower()

    # Extract tags
    found_tags = []
    for tag in CF_TAGS:
        # Check for tag presence (word boundary matching)
        if re.search(r'\b' + re.escape(tag) + r'\b', query_lower):
            found_tags.append(tag)
    # Also check common abbreviations
    if re.search(r'\bdp\b', query_lower):
        if "dp" not in found_tags:
            found_tags.append("dp")
    if re.search(r'\bdfs\b', query_lower):
        if "dfs and similar" not in found_tags:
            found_tags.append("dfs and similar")
    if re.search(r'\bbfs\b', query_lower):
        if "graphs" not in found_tags:
            found_tags.append("graphs")

    if found_tags:
        filters["tags"] = found_tags

    # Extract exact rating
    rating_match = re.search(r'\b(\d{3,4})\b', query_lower)
    # Check for "between X and Y" pattern first
    range_match = re.search(r'between\s+(\d{3,4})\s+and\s+(\d{3,4})', query_lower)
    if range_match:
        filters["rating_min"] = int(range_match.group(1))
        filters["rating_max"] = int(range_match.group(2))
    elif rating_match:
        rating = int(rating_match.group(1))
        if 800 <= rating <= 3500:
            filters["rating"] = rating

    # Extract difficulty keywords
    if any(word in query_lower for word in ["easy", "beginner", "simple", "basic"]):
        if "rating_max" not in filters and "rating" not in filters:
            filters["rating_max"] = 1200
    elif any(word in query_lower for word in ["medium", "intermediate", "moderate"]):
        if "rating_min" not in filters and "rating" not in filters:
            filters["rating_min"] = 1300
            filters["rating_max"] = 1800
    elif any(word in query_lower for word in ["hard", "difficult", "advanced", "tough"]):
        if "rating_min" not in filters and "rating" not in filters:
            filters["rating_min"] = 2000

    # Extract limit
    limit_match = re.search(r'(\d+)\s+(?:problems?|questions?|tasks?)', query_lower)
    if limit_match:
        requested = int(limit_match.group(1))
        if 1 <= requested <= 50:
            filters["limit"] = requested

    return filters


async def hybrid_search(
    query: str,
    db: AsyncSession,
    filters: Optional[dict] = None,
    top_k: int = 10,
) -> list[dict]:
    """
    Hybrid retrieval combining vector similarity with SQL filtering.

    1. Parse query for structured filters (rating, tags, etc.)
    2. Embed the query for semantic search
    3. FAISS similarity search → candidate chunk IDs
    4. SQL filter on associated problems
    5. Return ranked results with problem metadata
    """
    # Parse filters from natural language
    parsed_filters = parse_query_filters(query)
    if filters:
        parsed_filters.update(filters)

    vector_store = get_vector_store()

    # Get query embedding
    query_embedding = await get_embedding(query)

    # FAISS search — get more than top_k to allow for filtering
    fetch_k = top_k * 5
    faiss_results = vector_store.search(query_embedding, top_k=fetch_k)

    if not faiss_results:
        # Fall back to SQL-only search
        return await sql_only_search(db, parsed_filters, top_k)

    # Get chunk IDs from FAISS results
    chunk_ids = [chunk_id for chunk_id, _ in faiss_results]
    score_map = {chunk_id: score for chunk_id, score in faiss_results}

    # Query DB for chunks and their problems
    stmt = (
        select(ProblemChunk, Problem)
        .join(Problem, ProblemChunk.problem_id == Problem.id)
        .where(ProblemChunk.id.in_(chunk_ids))
    )

    # Apply SQL filters
    conditions = []
    if parsed_filters.get("rating"):
        conditions.append(Problem.rating == parsed_filters["rating"])
    if parsed_filters.get("rating_min"):
        conditions.append(Problem.rating >= parsed_filters["rating_min"])
    if parsed_filters.get("rating_max"):
        conditions.append(Problem.rating <= parsed_filters["rating_max"])

    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await db.execute(stmt)
    rows = result.all()

    # Filter by tags in Python (JSON column)
    if parsed_filters.get("tags"):
        filtered_rows = []
        for chunk, problem in rows:
            problem_tags = [t.lower() for t in (problem.tags or [])]
            if any(tag.lower() in problem_tags for tag in parsed_filters["tags"]):
                filtered_rows.append((chunk, problem))
        rows = filtered_rows

    # Build results with scores and deduplicate by problem
    seen_problems = {}
    results = []

    for chunk, problem in rows:
        chunk_id_str = str(chunk.id)
        score = score_map.get(chunk_id_str, 0.0)
        problem_id_str = str(problem.id)

        if problem_id_str not in seen_problems or score > seen_problems[problem_id_str]["score"]:
            seen_problems[problem_id_str] = {
                "problem_id": problem_id_str,
                "contest_id": problem.contest_id,
                "problem_index": problem.problem_index,
                "name": problem.name,
                "rating": problem.rating,
                "tags": problem.tags,
                "url": problem.url,
                "solved_count": problem.solved_count,
                "chunk_text": chunk.chunk_text,
                "chunk_type": chunk.chunk_type,
                "score": score,
            }

    results = sorted(seen_problems.values(), key=lambda x: x["score"], reverse=True)

    # Apply limit
    limit = parsed_filters.get("limit", top_k)
    return results[:limit]


async def sql_only_search(
    db: AsyncSession,
    filters: dict,
    top_k: int = 10,
) -> list[dict]:
    """Fallback: SQL-only search when FAISS has no results."""
    stmt = select(Problem).where(Problem.is_embedded == True)

    if filters.get("rating"):
        stmt = stmt.where(Problem.rating == filters["rating"])
    if filters.get("rating_min"):
        stmt = stmt.where(Problem.rating >= filters["rating_min"])
    if filters.get("rating_max"):
        stmt = stmt.where(Problem.rating <= filters["rating_max"])

    stmt = stmt.order_by(Problem.solved_count.desc()).limit(top_k * 2)

    result = await db.execute(stmt)
    problems = result.scalars().all()

    # Filter by tags
    if filters.get("tags"):
        problems = [
            p for p in problems
            if any(t.lower() in [pt.lower() for pt in (p.tags or [])] for t in filters["tags"])
        ]

    limit = filters.get("limit", top_k)
    return [
        {
            "problem_id": str(p.id),
            "contest_id": p.contest_id,
            "problem_index": p.problem_index,
            "name": p.name,
            "rating": p.rating,
            "tags": p.tags,
            "url": p.url,
            "solved_count": p.solved_count,
            "chunk_text": p.statement_text[:500] if p.statement_text else "",
            "chunk_type": "full",
            "score": 0.5,
        }
        for p in problems[:limit]
    ]


async def similarity_search(
    problem_id: str,
    db: AsyncSession,
    top_k: int = 5,
) -> list[dict]:
    """Find problems most similar to a given problem using its embedding."""
    # Get the problem's chunks
    stmt = select(ProblemChunk).where(
        ProblemChunk.problem_id == problem_id,
        ProblemChunk.chunk_type.in_(["full", "summary", "statement"]),
    ).limit(1)

    result = await db.execute(stmt)
    chunk = result.scalar_one_or_none()

    if not chunk:
        return []

    # Use the chunk text to find similar problems
    embedding = await get_embedding(chunk.chunk_text)
    vector_store = get_vector_store()

    # Search for more to allow excluding the source problem
    faiss_results = vector_store.search(embedding, top_k=top_k * 3)

    chunk_ids = [cid for cid, _ in faiss_results]
    score_map = {cid: score for cid, score in faiss_results}

    stmt = (
        select(ProblemChunk, Problem)
        .join(Problem, ProblemChunk.problem_id == Problem.id)
        .where(ProblemChunk.id.in_(chunk_ids))
        .where(Problem.id != problem_id)  # Exclude the source problem
    )
    result = await db.execute(stmt)
    rows = result.all()

    seen = {}
    for chunk, problem in rows:
        pid = str(problem.id)
        score = score_map.get(str(chunk.id), 0)
        if pid not in seen or score > seen[pid]["score"]:
            seen[pid] = {
                "problem_id": pid,
                "contest_id": problem.contest_id,
                "problem_index": problem.problem_index,
                "name": problem.name,
                "rating": problem.rating,
                "tags": problem.tags,
                "url": problem.url,
                "score": score,
            }

    results = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    return results[:top_k]


async def difficulty_progression(
    db: AsyncSession,
    tags: list[str],
    current_rating: int = 800,
    step: int = 200,
    problems_per_level: int = 3,
) -> list[dict]:
    """
    Return a difficulty progression path for given tags.
    Groups problems by rating levels from current_rating upward.
    """
    progression = []
    max_rating = 2400

    for rating in range(current_rating, max_rating + 1, step):
        stmt = (
            select(Problem)
            .where(
                Problem.is_embedded == True,
                Problem.rating >= rating,
                Problem.rating < rating + step,
            )
            .order_by(Problem.solved_count.desc())
            .limit(problems_per_level * 3)
        )
        result = await db.execute(stmt)
        problems = result.scalars().all()

        # Filter by tags
        if tags:
            problems = [
                p for p in problems
                if any(t.lower() in [pt.lower() for pt in (p.tags or [])] for t in tags)
            ]

        level_problems = [
            {
                "contest_id": p.contest_id,
                "problem_index": p.problem_index,
                "name": p.name,
                "rating": p.rating,
                "tags": p.tags,
                "url": p.url,
                "solved_count": p.solved_count,
            }
            for p in problems[:problems_per_level]
        ]

        if level_problems:
            progression.append({
                "rating_range": f"{rating}-{rating + step - 1}",
                "problems": level_problems,
            })

    return progression
