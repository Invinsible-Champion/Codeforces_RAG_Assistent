"""
Ingestion pipeline: Fetch problems from Codeforces API, scrape statements,
scrape editorials, chunk text, generate embeddings, and store everything.

Key improvement: Scrapes ONLY the editorial for each specific problem (not random
blog text) by locating the editorial blog entry and extracting the relevant section.
"""
import asyncio
import logging
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Problem, ProblemChunk
from app.services.text_processing import (
    extract_problem_sections,
    chunk_problem_text,
    html_to_clean_text,
    find_editorial_blog_url,
    extract_editorial_from_blog,
)
from app.services.embeddings import get_embeddings_batch
from app.services.vector_store import get_vector_store

settings = get_settings()
logger = logging.getLogger(__name__)

# Ingestion status tracking
_ingestion_status = {
    "running": False,
    "total": 0,
    "processed": 0,
    "errors": 0,
    "message": "Idle",
}

# Cache for editorial blog URLs per contest (avoid re-scraping the same contest page)
_editorial_url_cache: dict[int, Optional[str]] = {}


def get_ingestion_status() -> dict:
    return _ingestion_status.copy()


async def fetch_problem_list(
    tags: Optional[list[str]] = None,
) -> list[dict]:
    """Fetch problem list from the Codeforces API."""
    url = "https://codeforces.com/api/problemset.problems"
    params = {}
    if tags:
        params["tags"] = ";".join(tags)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    if data.get("status") != "OK":
        raise ValueError(f"Codeforces API error: {data.get('comment', 'Unknown error')}")

    problems = data["result"]["problems"]
    statistics = data["result"]["problemStatistics"]

    # Build solved_count map
    solved_map = {}
    for stat in statistics:
        key = (stat["contestId"], stat["index"])
        solved_map[key] = stat.get("solvedCount", 0)

    # Merge statistics into problems
    for prob in problems:
        key = (prob["contestId"], prob["index"])
        prob["solvedCount"] = solved_map.get(key, 0)

    return problems


async def scrape_problem_statement(contest_id: int, index: str) -> Optional[str]:
    """Scrape the full problem statement HTML from Codeforces."""
    url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code != 200:
                logger.warning(f"Failed to scrape {contest_id}{index}: HTTP {response.status_code}")
                return None

        soup = BeautifulSoup(response.text, "html.parser")
        statement = soup.select_one(".problem-statement")
        if statement:
            return str(statement)
        logger.warning(f"No .problem-statement found for {contest_id}{index}")
        return None

    except Exception as e:
        logger.error(f"Error scraping {contest_id}{index}: {e}")
        return None


async def _get_editorial_blog_url(contest_id: int) -> Optional[str]:
    """
    Get the editorial blog URL for a contest.
    Checks the contest page sidebar for "Tutorial" / "Editorial" links.
    Results are cached per contest.
    """
    global _editorial_url_cache

    if contest_id in _editorial_url_cache:
        return _editorial_url_cache[contest_id]

    url = f"https://codeforces.com/contest/{contest_id}"

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code != 200:
                _editorial_url_cache[contest_id] = None
                return None

        editorial_url = find_editorial_blog_url(response.text)
        _editorial_url_cache[contest_id] = editorial_url

        if editorial_url:
            logger.info(f"Found editorial for contest {contest_id}: {editorial_url}")
        else:
            logger.debug(f"No editorial found for contest {contest_id}")

        return editorial_url

    except Exception as e:
        logger.warning(f"Error finding editorial for contest {contest_id}: {e}")
        _editorial_url_cache[contest_id] = None
        return None


# Cache for blog HTML (since multiple problems from the same contest share one blog)
_blog_html_cache: dict[str, str] = {}


async def _fetch_editorial_blog_html(blog_url: str) -> Optional[str]:
    """Fetch and cache the editorial blog HTML."""
    global _blog_html_cache

    if blog_url in _blog_html_cache:
        return _blog_html_cache[blog_url]

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(blog_url)
            if response.status_code != 200:
                _blog_html_cache[blog_url] = None
                return None

        _blog_html_cache[blog_url] = response.text
        return response.text

    except Exception as e:
        logger.warning(f"Error fetching editorial blog {blog_url}: {e}")
        _blog_html_cache[blog_url] = None
        return None


async def scrape_editorial(contest_id: int, problem_index: str) -> Optional[str]:
    """
    Scrape the editorial for a specific problem.
    
    Strategy:
    1. Find the editorial blog URL from the contest page
    2. Fetch the blog page
    3. Extract ONLY the editorial section for this specific problem
    4. Return clean editorial text (not random blog content)
    """
    # Step 1: Get editorial blog URL
    blog_url = await _get_editorial_blog_url(contest_id)
    if not blog_url:
        return None

    # Throttle between requests
    await asyncio.sleep(settings.scrape_delay / 2)

    # Step 2: Fetch blog HTML (cached for same contest)
    blog_html = await _fetch_editorial_blog_html(blog_url)
    if not blog_html:
        return None

    # Step 3: Extract only this problem's editorial
    editorial = extract_editorial_from_blog(blog_html, contest_id, problem_index)

    if editorial:
        logger.info(f"✓ Extracted editorial for {contest_id}{problem_index} ({len(editorial)} chars)")
    else:
        logger.debug(f"Could not extract editorial for {contest_id}{problem_index}")

    return editorial


async def ingest_problems(
    db: AsyncSession,
    tags: Optional[list[str]] = None,
    rating_min: Optional[int] = None,
    rating_max: Optional[int] = None,
    limit: int = 100,
):
    """
    Main ingestion orchestrator.

    1. Fetch problem list from CF API
    2. Filter by rating
    3. Skip already-ingested problems
    4. Scrape statements
    5. Scrape editorials (ONLY the relevant editorial text, not random blog content)
    6. Chunk and embed
    7. Store in DB + FAISS
    """
    global _ingestion_status, _editorial_url_cache, _blog_html_cache
    _ingestion_status = {
        "running": True,
        "total": 0,
        "processed": 0,
        "errors": 0,
        "message": "Fetching problem list from Codeforces API...",
    }

    # Clear caches for fresh run
    _editorial_url_cache = {}
    _blog_html_cache = {}

    try:
        # 1. Fetch
        logger.info("Fetching problem list from Codeforces API...")
        all_problems = await fetch_problem_list(tags=tags)

        # 2. Filter by rating
        if rating_min is not None:
            all_problems = [p for p in all_problems if p.get("rating") and p["rating"] >= rating_min]
        if rating_max is not None:
            all_problems = [p for p in all_problems if p.get("rating") and p["rating"] <= rating_max]

        # Only take problems that have a rating (unrated problems are less useful)
        all_problems = [p for p in all_problems if p.get("rating")]

        # Limit
        all_problems = all_problems[:limit]
        _ingestion_status["total"] = len(all_problems)
        _ingestion_status["message"] = f"Processing {len(all_problems)} problems..."

        logger.info(f"Will process {len(all_problems)} problems")

        vector_store = get_vector_store()

        for prob_data in all_problems:
            try:
                contest_id = prob_data["contestId"]
                index = prob_data["index"]

                # Check if already ingested
                existing = await db.execute(
                    select(Problem).where(
                        Problem.contest_id == contest_id,
                        Problem.problem_index == index,
                    )
                )
                existing_problem = existing.scalar_one_or_none()

                if existing_problem and existing_problem.is_embedded:
                    _ingestion_status["processed"] += 1
                    continue

                # 3. Scrape statement
                _ingestion_status["message"] = f"Scraping {contest_id}{index}..."
                statement_html = await scrape_problem_statement(contest_id, index)

                # Throttle to be respectful
                await asyncio.sleep(settings.scrape_delay)

                # 4. Scrape editorial (ONLY the editorial for THIS problem)
                _ingestion_status["message"] = f"Fetching editorial for {contest_id}{index}..."
                editorial_text = await scrape_editorial(contest_id, index)

                # Throttle again
                await asyncio.sleep(settings.scrape_delay / 2)

                # 5. Parse sections
                sections = extract_problem_sections(statement_html) if statement_html else {}

                # Create or update problem record
                if existing_problem:
                    problem = existing_problem
                else:
                    problem = Problem(
                        contest_id=contest_id,
                        problem_index=index,
                        name=prob_data.get("name", ""),
                        rating=prob_data.get("rating"),
                        tags=prob_data.get("tags", []),
                        solved_count=prob_data.get("solvedCount", 0),
                        url=f"https://codeforces.com/problemset/problem/{contest_id}/{index}",
                    )

                problem.statement_html = statement_html
                problem.statement_text = html_to_clean_text(statement_html) if statement_html else ""
                problem.time_limit = sections.get("time_limit", "")
                problem.memory_limit = sections.get("memory_limit", "")
                problem.input_spec = sections.get("input_spec", "")
                problem.output_spec = sections.get("output_spec", "")
                problem.sample_tests = sections.get("examples", [])
                problem.note = sections.get("note", "")

                if not existing_problem:
                    db.add(problem)

                await db.flush()

                # 6. Chunk (now includes editorial text!)
                problem_meta = {
                    "contest_id": contest_id,
                    "index": index,
                    "name": prob_data.get("name", ""),
                    "rating": prob_data.get("rating"),
                    "tags": prob_data.get("tags", []),
                }
                chunks = chunk_problem_text(
                    sections,
                    problem_meta,
                    editorial_text=editorial_text,
                )

                if not chunks:
                    _ingestion_status["processed"] += 1
                    continue

                # 7. Embed
                _ingestion_status["message"] = f"Embedding {contest_id}{index}..."
                chunk_texts = [c["chunk_text"] for c in chunks]
                embeddings = await get_embeddings_batch(chunk_texts)

                # 8. Store chunks in DB
                # Remove old chunks if re-ingesting
                if existing_problem:
                    old_chunks = await db.execute(
                        select(ProblemChunk).where(ProblemChunk.problem_id == problem.id)
                    )
                    for old in old_chunks.scalars():
                        await db.delete(old)
                    await db.flush()

                db_chunks = []
                chunk_ids = []
                for chunk_data, embedding in zip(chunks, embeddings):
                    chunk = ProblemChunk(
                        problem_id=problem.id,
                        chunk_index=chunk_data["chunk_index"],
                        chunk_text=chunk_data["chunk_text"],
                        chunk_type=chunk_data["chunk_type"],
                        token_count=chunk_data.get("token_count", 0),
                    )
                    db.add(chunk)
                    await db.flush()

                    db_chunks.append(chunk)
                    chunk_ids.append(str(chunk.id))

                # 9. Add to FAISS
                embedding_indices = vector_store.add_vectors(embeddings, chunk_ids)
                for chunk_obj, emb_idx in zip(db_chunks, embedding_indices):
                    chunk_obj.embedding_id = emb_idx

                problem.is_embedded = True
                await db.commit()

                editorial_status = "with editorial" if editorial_text else "no editorial"
                _ingestion_status["processed"] += 1
                logger.info(f"✓ Ingested {contest_id}{index} ({len(chunks)} chunks, {editorial_status})")

            except Exception as e:
                _ingestion_status["errors"] += 1
                logger.error(f"✗ Error ingesting {prob_data.get('contestId', '?')}{prob_data.get('index', '?')}: {e}")
                await db.rollback()
                continue

        # Save FAISS index
        vector_store.save()
        _ingestion_status["message"] = f"Done! Processed {_ingestion_status['processed']}/{_ingestion_status['total']} problems."
        _ingestion_status["running"] = False

    except Exception as e:
        _ingestion_status["running"] = False
        _ingestion_status["message"] = f"Error: {e}"
        logger.error(f"Ingestion failed: {e}")
        raise
