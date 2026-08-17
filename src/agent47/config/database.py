import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/agent47",
)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"connect_timeout": 5} if DATABASE_URL.startswith("postgresql") else {}
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=True)


class Base(DeclarativeBase):
    """Shared declarative base for all SQLAlchemy models."""
    pass


def get_db():
    """FastAPI dependency that provides a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create all tables in the database (for dev/bootstrap)."""
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE builds ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'pending';"))
        conn.execute(text("ALTER TABLE builds ADD COLUMN IF NOT EXISTS files_changed JSONB;"))
        conn.execute(text("ALTER TABLE builds ADD COLUMN IF NOT EXISTS log_sections JSONB;"))
        conn.execute(text("ALTER TABLE builds ADD COLUMN IF NOT EXISTS fix_summary TEXT;"))
        conn.execute(text("ALTER TABLE builds ADD COLUMN IF NOT EXISTS identified_issues JSONB;"))
        conn.execute(text("ALTER TABLE builds ADD COLUMN IF NOT EXISTS total_additions INTEGER DEFAULT 0;"))
        conn.execute(text("ALTER TABLE builds ADD COLUMN IF NOT EXISTS total_deletions INTEGER DEFAULT 0;"))
        conn.execute(text("ALTER TABLE builds ADD COLUMN IF NOT EXISTS duration_ms INTEGER;"))
        conn.execute(text("ALTER TABLE apikeys ADD COLUMN IF NOT EXISTS model VARCHAR DEFAULT 'gemini-1.5-pro';"))
        conn.execute(text("ALTER TABLE apikeys ADD COLUMN IF NOT EXISTS temperature FLOAT DEFAULT 0.2;"))
        conn.execute(text("ALTER TABLE apikeys ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT FALSE;"))

