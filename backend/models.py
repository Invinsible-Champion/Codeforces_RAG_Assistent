from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Boolean,
    ForeignKey,
    String,
    Text,
    Float,
    ARRAY,
    DateTime,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Problem(Base):
    """
    One row per Codeforces problem.
    The primary key is the composite problem_id  (e.g. '1555A').
    """

    __tablename__ = "problems"

    problem_id = Column(String(20), primary_key=True)   # e.g. "1555A"
    contest_id = Column(Integer, nullable=False)
    index = Column(String(5), nullable=False)            # e.g. "A", "B1"
    name = Column(String(256), nullable=False)
    rating = Column(Integer, nullable=True)              # can be unrated
    tags = Column(ARRAY(String), nullable=True)          # ['math', 'greedy', ...]
    solved_count = Column(Integer, nullable=True)        # from problemStatistics
    description_text = Column(Text, nullable=True)       # generated text for embedding


class User(Base):
    """
    Registered user — stores Codeforces handle and bcrypt-hashed password.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cf_handle = Column(String(128), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ProblemHistory(Base):
    """
    Tracks every problem generated for a user — acts as a to-do list.
    """

    __tablename__ = "problem_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    problem_id = Column(String(20), nullable=False)       # e.g. "1555A"
    problem_name = Column(String(256), nullable=False)
    contest_id = Column(Integer, nullable=False)
    problem_index = Column(String(5), nullable=False)     # e.g. "A", "B1"
    rating = Column(Integer, nullable=True)
    tags = Column(String(512), nullable=True)             # comma-separated tags
    coach_message = Column(Text, nullable=True)           # LLM presentation text
    is_completed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


def init_db():
    """Create all tables (idempotent)."""
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    init_db()
    print("✅  Database tables created.")

