"""
Pydantic schemas for API request/response models.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Chat ──────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="User's question or request")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for context continuity")
    mode: str = Field("chat", description="Response mode: chat, explain, hint, recommend")
    filters: Optional[dict] = Field(None, description="Optional structured filters (rating, tags, etc.)")
    stream: bool = Field(True, description="Whether to stream the response via SSE")


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    retrieved_problems: list[dict] = []
    parsed_filters: dict = {}


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    metadata: Optional[dict] = None
    created_at: datetime


class ConversationDetail(BaseModel):
    id: str
    title: str
    messages: list[MessageResponse]
    created_at: datetime


# ── Problems ──────────────────────────────────────────

class ProblemSummary(BaseModel):
    id: str
    contest_id: int
    problem_index: str
    name: str
    rating: Optional[int] = None
    tags: list[str] = []
    solved_count: Optional[int] = None
    url: Optional[str] = None


class ProblemDetail(BaseModel):
    id: str
    contest_id: int
    problem_index: str
    name: str
    rating: Optional[int] = None
    tags: list[str] = []
    time_limit: Optional[str] = None
    memory_limit: Optional[str] = None
    solved_count: Optional[int] = None
    statement_text: Optional[str] = None
    input_spec: Optional[str] = None
    output_spec: Optional[str] = None
    sample_tests: Optional[list[dict]] = None
    note: Optional[str] = None
    url: Optional[str] = None


class ProblemListResponse(BaseModel):
    problems: list[ProblemSummary]
    total: int
    page: int
    page_size: int


class SimilarProblemResponse(BaseModel):
    problems: list[dict]


class ProgressionResponse(BaseModel):
    levels: list[dict]


# ── Ingestion ─────────────────────────────────────────

class IngestRequest(BaseModel):
    tags: Optional[list[str]] = None
    rating_min: Optional[int] = Field(None, ge=800, le=3500)
    rating_max: Optional[int] = Field(None, ge=800, le=3500)
    limit: int = Field(100, ge=1, le=1000)


class IngestStatusResponse(BaseModel):
    running: bool
    total: int
    processed: int
    errors: int
    message: str


# ── Stats ─────────────────────────────────────────────

class StatsResponse(BaseModel):
    total_problems: int
    embedded_problems: int
    total_chunks: int
    total_vectors: int
    tags_distribution: dict
    rating_distribution: dict
