"""
database.py
SQLAlchemy setup — SQLite for local, MySQL for production.
Switch via DATABASE_URL in .env.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

# SQLite by default (zero setup, works locally out of the box)
# For MySQL on production: mysql+pymysql://user:password@host:3306/stem_splitter
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./stem_splitter.db")

# SQLite needs different connect args
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=10,
        max_overflow=20,
        echo=False,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import Job, Track, Stem, Upload  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print(f"[DB] Tables created / verified ({DATABASE_URL})")
