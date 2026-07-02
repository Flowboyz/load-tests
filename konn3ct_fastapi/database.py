import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Resolve database path relative to project root
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(PROJECT_ROOT, "konn3ct.db")
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Connect args necessary for SQLite to allow multiple threads/requests
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Enable WAL mode and normal synchronous mode for SQLite connection efficiency
from sqlalchemy import event
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

Base = declarative_base()

def get_db():
    """FastAPI dependency to yield database session and ensure clean close."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
