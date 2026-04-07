"""
SQLAlchemy ORM models for the Codeforces RAG system.
Compatible with both PostgreSQL and SQLite.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, ForeignKey,
    JSON, Boolean, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Problem(Base):
    """Codeforces problem metadata."""
    __tablename__ = "problems"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    contest_id = Column(Integer, nullable=False, index=True)
    problem_index = Column(String(10), nullable=False)  # A, B, C, ...
    name = Column(String(500), nullable=False)
    rating = Column(Integer, nullable=True, index=True)
    tags = Column(JSON, nullable=False, default=list)  # ["dp", "greedy", ...]
    time_limit = Column(String(50), nullable=True)
    memory_limit = Column(String(50), nullable=True)
    solved_count = Column(Integer, nullable=True)
    statement_html = Column(Text, nullable=True)
    statement_text = Column(Text, nullable=True)
    input_spec = Column(Text, nullable=True)
    output_spec = Column(Text, nullable=True)
    sample_tests = Column(JSON, nullable=True)  # [{input: ..., output: ...}]
    note = Column(Text, nullable=True)
    url = Column(String(500), nullable=True)
    is_embedded = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    chunks = relationship("ProblemChunk", back_populates="problem", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("contest_id", "problem_index", name="uq_contest_problem"),
    )

    @property
    def problem_id_str(self) -> str:
        return f"{self.contest_id}{self.problem_index}"

    def __repr__(self):
        return f"<Problem {self.contest_id}{self.problem_index}: {self.name}>"


class ProblemChunk(Base):
    """Semantic chunk of a problem statement for RAG retrieval."""
    __tablename__ = "problem_chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    problem_id = Column(String(36), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_type = Column(String(50), nullable=False)  # statement, input_spec, output_spec, note, example, full
    token_count = Column(Integer, nullable=True)
    embedding_id = Column(Integer, nullable=True, index=True)  # FAISS vector index
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    problem = relationship("Problem", back_populates="chunks")

    def __repr__(self):
        return f"<ProblemChunk {self.problem_id}[{self.chunk_index}] type={self.chunk_type}>"


class Conversation(Base):
    """Chat conversation session."""
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(500), default="New Chat")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan",
                            order_by="Message.created_at")

    def __repr__(self):
        return f"<Conversation {self.id}: {self.title}>"


class Message(Base):
    """Individual message within a conversation."""
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)  # retrieved chunks, scores, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self):
        return f"<Message {self.role}: {self.content[:50]}>"
