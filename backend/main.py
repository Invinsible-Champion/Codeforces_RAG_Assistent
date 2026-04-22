from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, List
import math

from ml_engine import analyze_user_profile
from chat_engine import fetch_practice_problem
from models import SessionLocal, User, ProblemHistory, init_db
from auth import hash_password, verify_password, create_session, get_current_user, clear_session
from sqlalchemy import func as sa_func

app = FastAPI(title="CF Coach API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure DB tables exist on startup
init_db()


# ── Request models ───────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    cf_handle: str
    password: str

class LoginRequest(BaseModel):
    cf_handle: str
    password: str

class ProfileRequest(BaseModel):
    handle: Optional[str] = None

class ToggleCompleteRequest(BaseModel):
    is_completed: bool


# ── Auth endpoints ───────────────────────────────────────────────────

@app.post("/api/register")
def register(req: RegisterRequest, response: Response):
    cf_handle = req.cf_handle.strip()
    password = req.password.strip()

    if not cf_handle or not password:
        raise HTTPException(status_code=400, detail="Handle and password are required.")
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.cf_handle == cf_handle).first()
        if existing:
            raise HTTPException(status_code=409, detail="This Codeforces handle is already registered.")

        user = User(cf_handle=cf_handle, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)

        create_session(response, user.id, user.cf_handle)
        return {"message": "Registration successful!", "cf_handle": user.cf_handle}
    finally:
        db.close()


@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    cf_handle = req.cf_handle.strip()
    password = req.password.strip()

    if not cf_handle or not password:
        raise HTTPException(status_code=400, detail="Handle and password are required.")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.cf_handle == cf_handle).first()
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid handle or password.")

        create_session(response, user.id, user.cf_handle)
        return {"message": "Login successful!", "cf_handle": user.cf_handle}
    finally:
        db.close()


@app.post("/api/logout")
def logout(response: Response):
    clear_session(response)
    return {"message": "Logged out."}


@app.get("/api/me")
def me(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return {"cf_handle": user["handle"]}


# ── Core endpoints (now session-aware) ───────────────────────────────

def _resolve_handle(req: ProfileRequest, request: Request) -> str:
    """Return the handle from request body or fall back to session."""
    if req.handle and req.handle.strip():
        return req.handle.strip()
    user = get_current_user(request)
    if user:
        return user["handle"]
    raise HTTPException(status_code=401, detail="Please log in or provide a handle.")


def _get_user_id(request: Request) -> int:
    """Return the user ID from session or raise."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user["uid"]


@app.post("/api/analyze")
def analyze_profile(req: ProfileRequest, request: Request):
    handle = _resolve_handle(req, request)
    result = analyze_user_profile(handle)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/get_problem")
def get_problem(req: ProfileRequest, request: Request):
    handle = _resolve_handle(req, request)
    user_id = _get_user_id(request)

    result = analyze_user_profile(handle)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    response = fetch_practice_problem(result)
    if "error" in response:
        raise HTTPException(status_code=500, detail=response["error"])

    problem_details = response.get("problem_details")

    # Auto-save to history
    if problem_details:
        db = SessionLocal()
        try:
            tags_str = problem_details.get("tags", "")
            if isinstance(tags_str, list):
                tags_str = ", ".join(tags_str)

            entry = ProblemHistory(
                user_id=user_id,
                problem_id=problem_details.get("problem_id", ""),
                problem_name=problem_details.get("name", "Unknown"),
                contest_id=int(problem_details.get("contest_id", 0)),
                problem_index=problem_details.get("index", "A"),
                rating=problem_details.get("rating"),
                tags=tags_str,
                coach_message=response.get("message", ""),
                is_completed=False,
            )
            db.add(entry)
            db.commit()
        except Exception as e:
            print(f"[!] Failed to save history: {e}")
            db.rollback()
        finally:
            db.close()

    return {
        "message": response["message"],
        "profile": result,
        "problem_details": problem_details,
    }


# ── History endpoints ────────────────────────────────────────────────

@app.get("/api/history")
def get_history(request: Request):
    user_id = _get_user_id(request)
    db = SessionLocal()
    try:
        items = (
            db.query(ProblemHistory)
            .filter(ProblemHistory.user_id == user_id)
            .order_by(ProblemHistory.created_at.desc())
            .all()
        )
        return [
            {
                "id": item.id,
                "problem_id": item.problem_id,
                "problem_name": item.problem_name,
                "contest_id": item.contest_id,
                "problem_index": item.problem_index,
                "rating": item.rating,
                "tags": item.tags,
                "coach_message": item.coach_message,
                "is_completed": item.is_completed,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ]
    finally:
        db.close()


@app.patch("/api/history/{item_id}")
def toggle_history(item_id: int, req: ToggleCompleteRequest, request: Request):
    user_id = _get_user_id(request)
    db = SessionLocal()
    try:
        item = (
            db.query(ProblemHistory)
            .filter(ProblemHistory.id == item_id, ProblemHistory.user_id == user_id)
            .first()
        )
        if not item:
            raise HTTPException(status_code=404, detail="History item not found.")
        item.is_completed = req.is_completed
        db.commit()
        return {"id": item.id, "is_completed": item.is_completed}
    finally:
        db.close()


@app.delete("/api/history/{item_id}")
def delete_history(item_id: int, request: Request):
    user_id = _get_user_id(request)
    db = SessionLocal()
    try:
        item = (
            db.query(ProblemHistory)
            .filter(ProblemHistory.id == item_id, ProblemHistory.user_id == user_id)
            .first()
        )
        if not item:
            raise HTTPException(status_code=404, detail="History item not found.")
        db.delete(item)
        db.commit()
        return {"message": "Deleted."}
    finally:
        db.close()


# ── Leaderboard endpoint ────────────────────────────────────────────

@app.get("/api/leaderboard")
def get_leaderboard(request: Request, search: Optional[str] = None):
    """
    Ranking formula: avg_rating_of_completed_problems * log2(n + 1)
    where n = number of completed AI-recommended problems.
    """
    db = SessionLocal()
    try:
        # Get aggregated stats for ALL users who have completed at least 1 problem
        rows = (
            db.query(
                User.id,
                User.cf_handle,
                sa_func.avg(ProblemHistory.rating).label("avg_rating"),
                sa_func.count(ProblemHistory.id).label("total_solves"),
            )
            .join(ProblemHistory, ProblemHistory.user_id == User.id)
            .filter(
                ProblemHistory.is_completed == True,
                ProblemHistory.rating.isnot(None),
            )
            .group_by(User.id, User.cf_handle)
            .all()
        )

        # Compute scores in Python (log2 not available in all SQL dialects easily)
        leaderboard = []
        for row in rows:
            avg_r = float(row.avg_rating or 0)
            n = int(row.total_solves or 0)
            score = avg_r * math.log2(n + 1) if n > 0 else 0
            leaderboard.append({
                "user_id": row.id,
                "cf_handle": row.cf_handle,
                "avg_rating": round(avg_r, 1),
                "total_solves": n,
                "score": round(score, 1),
            })

        # Sort by score descending
        leaderboard.sort(key=lambda x: x["score"], reverse=True)

        # Assign ranks
        for i, entry in enumerate(leaderboard):
            entry["rank"] = i + 1

        # Also include users with 0 completed problems (append at bottom)
        ranked_ids = {e["user_id"] for e in leaderboard}
        all_users = db.query(User.id, User.cf_handle).all()
        for u in all_users:
            if u.id not in ranked_ids:
                leaderboard.append({
                    "user_id": u.id,
                    "cf_handle": u.cf_handle,
                    "avg_rating": 0,
                    "total_solves": 0,
                    "score": 0,
                    "rank": len(leaderboard) + 1,
                })

        # Search filter (applied after ranking so ranks stay global)
        if search and search.strip():
            q = search.strip().lower()
            leaderboard = [e for e in leaderboard if q in e["cf_handle"].lower()]

        # Get current user's rank
        current_user = get_current_user(request)
        my_rank = None
        if current_user:
            for entry in leaderboard:
                if entry["cf_handle"] == current_user["handle"]:
                    my_rank = entry["rank"]
                    break

        return {
            "leaderboard": leaderboard,
            "total_users": len(all_users),
            "my_rank": my_rank,
            "my_handle": current_user["handle"] if current_user else None,
        }
    finally:
        db.close()


# ── Static files (must be last) ─────────────────────────────────────

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
