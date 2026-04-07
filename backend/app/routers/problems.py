"""
Problem explorer API endpoints.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Problem, ProblemChunk
from app.schemas import ProblemSummary, ProblemDetail, ProblemListResponse
from app.services.retrieval import similarity_search, difficulty_progression

router = APIRouter(prefix="/api/problems", tags=["problems"])


@router.get("")
async def list_problems(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    rating_min: Optional[int] = Query(None, ge=800, le=3500),
    rating_max: Optional[int] = Query(None, ge=800, le=3500),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    search: Optional[str] = Query(None, description="Search by name"),
    sort_by: str = Query("rating", enum=["rating", "solved_count", "contest_id", "name"]),
    sort_order: str = Query("asc", enum=["asc", "desc"]),
    db: AsyncSession = Depends(get_db),
):
    """List problems with filtering, search, and pagination."""
    stmt = select(Problem).where(Problem.is_embedded == True)

    # Filters
    if rating_min:
        stmt = stmt.where(Problem.rating >= rating_min)
    if rating_max:
        stmt = stmt.where(Problem.rating <= rating_max)
    if search:
        stmt = stmt.where(Problem.name.ilike(f"%{search}%"))

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()

    # Sort
    sort_col = getattr(Problem, sort_by, Problem.rating)
    if sort_order == "desc":
        stmt = stmt.order_by(sort_col.desc())
    else:
        stmt = stmt.order_by(sort_col.asc())

    # Paginate
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    problems = result.scalars().all()

    # Filter by tags in Python (JSON column)
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",")]
        problems = [
            p for p in problems
            if any(t in [pt.lower() for pt in (p.tags or [])] for t in tag_list)
        ]

    return ProblemListResponse(
        problems=[
            ProblemSummary(
                id=str(p.id),
                contest_id=p.contest_id,
                problem_index=p.problem_index,
                name=p.name,
                rating=p.rating,
                tags=p.tags or [],
                solved_count=p.solved_count,
                url=p.url,
            )
            for p in problems
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get database statistics."""
    from app.services.vector_store import get_vector_store

    # Problem counts
    total_result = await db.execute(select(func.count(Problem.id)))
    total_problems = total_result.scalar()

    embedded_result = await db.execute(
        select(func.count(Problem.id)).where(Problem.is_embedded == True)
    )
    embedded_problems = embedded_result.scalar()

    # Chunk count
    chunk_result = await db.execute(select(func.count(ProblemChunk.id)))
    total_chunks = chunk_result.scalar()

    # Vector count
    vector_store = get_vector_store()

    # Rating distribution
    rating_result = await db.execute(
        select(Problem.rating, func.count(Problem.id))
        .where(Problem.is_embedded == True, Problem.rating.isnot(None))
        .group_by(Problem.rating)
        .order_by(Problem.rating)
    )
    rating_dist = {str(r): c for r, c in rating_result}

    # Tag distribution (approximate — count problems per tag)
    all_problems_result = await db.execute(
        select(Problem.tags).where(Problem.is_embedded == True)
    )
    tag_counts = {}
    for (tags_list,) in all_problems_result:
        if tags_list:
            for tag in tags_list:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return {
        "total_problems": total_problems,
        "embedded_problems": embedded_problems,
        "total_chunks": total_chunks,
        "total_vectors": vector_store.total_vectors,
        "rating_distribution": rating_dist,
        "tags_distribution": dict(sorted(tag_counts.items(), key=lambda x: -x[1])),
    }


@router.get("/progression")
async def get_progression(
    tags: str = Query(..., description="Comma-separated tags"),
    current_rating: int = Query(800, ge=800, le=3500),
    step: int = Query(200, ge=100, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get difficulty progression for given tags."""
    tag_list = [t.strip() for t in tags.split(",")]
    result = await difficulty_progression(
        db=db,
        tags=tag_list,
        current_rating=current_rating,
        step=step,
    )
    return {"levels": result}


@router.get("/{problem_id}")
async def get_problem(problem_id: str, db: AsyncSession = Depends(get_db)):
    """Get full problem details."""
    result = await db.execute(
        select(Problem).where(Problem.id == problem_id)
    )
    problem = result.scalar_one_or_none()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")

    return ProblemDetail(
        id=str(problem.id),
        contest_id=problem.contest_id,
        problem_index=problem.problem_index,
        name=problem.name,
        rating=problem.rating,
        tags=problem.tags or [],
        time_limit=problem.time_limit,
        memory_limit=problem.memory_limit,
        solved_count=problem.solved_count,
        statement_text=problem.statement_text,
        input_spec=problem.input_spec,
        output_spec=problem.output_spec,
        sample_tests=problem.sample_tests,
        note=problem.note,
        url=problem.url,
    )


@router.get("/{problem_id}/similar")
async def get_similar(
    problem_id: str,
    top_k: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Find similar problems."""
    results = await similarity_search(problem_id, db, top_k=top_k)
    return {"problems": results}
