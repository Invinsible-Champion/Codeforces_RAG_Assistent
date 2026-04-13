"""
SQLAlchemy ORM models and database engine/session setup.
"""

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Float,
    ARRAY,
)
from sqlalchemy.orm import declarative_base, sessionmaker

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


def init_db():
    """Create all tables (idempotent)."""
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    init_db()
    print("✅  Database tables created.")
