"""
Ingestion pipeline: Fetch problems from Codeforces API, scrape statements,
scrape editorials, chunk text, generate embeddings, and store everything.

Key improvement: Asynchronously Scrapes ONLY the editorial for each specific problem 
(not random blog text) using Semaphore-controlled gather batches to avoid IP bans.
"""
import asyncio
import logging
from typing import Optional
import httpx
import json
import os
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Problem, ProblemChunk
from app.services.text_processing import (
    extract_problem_sections,
    chunk_problem_text,
    html_to_clean_text,
    extract_editorial_section,
    find_editorial_blog_url,
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

def get_ingestion_status() -> dict:
    return _ingestion_status.copy()

CHECKPOINT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "scraped_editorials.json")

def _load_editorial_from_checkpoint(contest_id: int, index: str) -> tuple[Optional[str], Optional[str]]:
    """Loads extracted editorial pre-fetched by the Stealth Selenium Scraper."""
    pid = f"{contest_id}{index}"
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                data = json.load(f)
                if pid in data and "text" in data[pid]:
                    return data[pid].get("html"), data[pid].get("text")
        except Exception:
            pass
    return None, None

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


async def scrape_problem_statement(client: httpx.AsyncClient, contest_id: int, index: str) -> Optional[str]:
    """Scrape the full problem statement HTML from Codeforces."""
    url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"

    try:
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


async def fetch_tutorial_link(client: httpx.AsyncClient, contest_id: int, index: str) -> Optional[str]:
    """Fetch the problem page and extract the URL for the 'Tutorial' or 'Editorial' from the right-hand sidebar."""
    url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
    
    try:
        response = await client.get(url)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        for link in soup.find_all("a", href=True):
            link_text = link.get_text(strip=True).lower()
            href = link["href"]
            
            if any(keyword in link_text for keyword in ["editorial", "tutorial", "analysis", "разбор"]):
                if "/blog/entry/" in href:
                    if href.startswith("/"):
                        return f"https://codeforces.com{href}"
                    return href
                    
        return None
        
    except Exception as e:
        logger.warning(f"Error fetching tutorial link for {contest_id}{index}: {e}")
        return None


async def fetch_and_extract_editorial(client: httpx.AsyncClient, tutorial_url: str, problem_index: str, problem_name: str) -> tuple[Optional[str], Optional[str]]:
    """Fetch blog post HTML and isolate problem HTML/text."""
    if not tutorial_url:
        return None, None
        
    try:
        response = await client.get(tutorial_url)
        if response.status_code != 200:
            return None, None
        
        return extract_editorial_section(response.text, problem_index, problem_name)
        
    except Exception as e:
        logger.warning(f"Error fetching editorial from {tutorial_url}: {e}")
        return None, None


async def process_single_problem(semaphore: asyncio.Semaphore, db: AsyncSession, client: httpx.AsyncClient, prob_data: dict, vector_store):
    global _ingestion_status
    contest_id = prob_data["contestId"]
    index = prob_data["index"]
    problem_name = prob_data.get("name", "")
    
    async with semaphore:
        # Respect the scrape delay environment limit inside the concurrent workers
        await asyncio.sleep(settings.scrape_delay)
        
        try:
            # Check if this problem is already fully ingested
            existing = await db.execute(
                select(Problem).where(
                    Problem.contest_id == contest_id,
                    Problem.problem_index == index,
                )
            )
            existing_problem = existing.scalar_one_or_none()

            if existing_problem and existing_problem.is_embedded:
                _ingestion_status["processed"] += 1
                return

            _ingestion_status["message"] = f"Scraping {contest_id}{index}..."
            
            # Fetch statement
            statement_html = await scrape_problem_statement(client, contest_id, index)
            await asyncio.sleep(settings.scrape_delay / 2)
            
            # Use stealth scraper pre-computed checkpoint if available
            editorial_html, editorial_text = _load_editorial_from_checkpoint(contest_id, index)
            
            # If not in checkpoint, fallback to old HTTP fetching
            if editorial_text is None:
                tutorial_url = await fetch_tutorial_link(client, contest_id, index)
                await asyncio.sleep(settings.scrape_delay / 2)
                
                if tutorial_url:
                    editorial_html, editorial_text = await fetch_and_extract_editorial(client, tutorial_url, index, problem_name)
                else:
                    logger.debug(f"No tutorial link for {contest_id}{index}")

            # Parse sections out of the html
            sections = extract_problem_sections(statement_html) if statement_html else {}

            if existing_problem:
                problem = existing_problem
            else:
                problem = Problem(
                    contest_id=contest_id,
                    problem_index=index,
                    name=problem_name,
                    rating=prob_data.get("rating"),
                    tags=prob_data.get("tags", []),
                    solved_count=prob_data.get("solvedCount", 0),
                    url=f"https://codeforces.com/problemset/problem/{contest_id}/{index}",
                )

            problem.statement_html = statement_html
            problem.statement_text = html_to_clean_text(statement_html) if statement_html else ""
            problem.editorial_html = editorial_html
            problem.editorial_text = editorial_text
            problem.time_limit = sections.get("time_limit", "")
            problem.memory_limit = sections.get("memory_limit", "")
            problem.input_spec = sections.get("input_spec", "")
            problem.output_spec = sections.get("output_spec", "")
            problem.sample_tests = sections.get("examples", [])
            problem.note = sections.get("note", "")

            if not existing_problem:
                db.add(problem)
            await db.flush()

            # Create chunks embedding the new editorial text!
            problem_meta = {
                "contest_id": contest_id,
                "index": index,
                "name": problem_name,
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
                return

            chunk_texts = [c["chunk_text"] for c in chunks]
            embeddings = await get_embeddings_batch(chunk_texts)

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

            # Store the FAISS Embeddings
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
            logger.error(f"✗ Error ingesting {contest_id}{index}: {e}")
            await db.rollback()


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
    2. Filter by rating/tags
    3. Use asyncio.gather to concurrently parse logic via process_single_problem.
    """
    global _ingestion_status
    _ingestion_status = {
        "running": True,
        "total": 0,
        "processed": 0,
        "errors": 0,
        "message": "Fetching problem list from Codeforces API...",
    }

    try:
        logger.info("Fetching problem list from Codeforces API...")
        all_problems = await fetch_problem_list(tags=tags)

        if rating_min is not None:
            all_problems = [p for p in all_problems if p.get("rating") and p["rating"] >= rating_min]
        if rating_max is not None:
            all_problems = [p for p in all_problems if p.get("rating") and p["rating"] <= rating_max]

        all_problems = [p for p in all_problems if p.get("rating")]
        all_problems = all_problems[:limit]
        
        _ingestion_status["total"] = len(all_problems)
        _ingestion_status["message"] = f"Processing {len(all_problems)} problems..."
        logger.info(f"Will process {len(all_problems)} problems")

        vector_store = get_vector_store()
        
        # We establish the semaphore limit for IP protection against Codeforces
        semaphore = asyncio.Semaphore(5)
        
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            tasks = [
                process_single_problem(semaphore, db, client, prob_data, vector_store) 
                for prob_data in all_problems
            ]
            await asyncio.gather(*tasks)

        vector_store.save()
        _ingestion_status["message"] = f"Done! Processed {_ingestion_status['processed']}/{_ingestion_status['total']} problems."
        _ingestion_status["running"] = False

    except Exception as e:
        _ingestion_status["running"] = False
        _ingestion_status["message"] = f"Error: {e}"
        logger.error(f"Ingestion failed: {e}")
        raise
