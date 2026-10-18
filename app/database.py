from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


def _normalize_database_url(url: str) -> str:
    # Render (and some other hosts) hand out "postgres://" which SQLAlchemy
    # 2.x no longer accepts as a dialect name.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    # Pin the driver explicitly rather than relying on SQLAlchemy's default
    # dialect resolution for a bare "postgresql://" URL, which has changed
    # across SQLAlchemy versions (psycopg2 vs. psycopg 3) and caused a
    # ModuleNotFoundError in production when an unpinned SQLAlchemy release
    # picked a driver we hadn't installed.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = _normalize_database_url(settings.database_url)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
