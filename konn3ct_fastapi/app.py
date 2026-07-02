import os
import sys
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from database import Base, engine, SessionLocal
from services.bot_runner import adopt_running_sessions
from routers import dashboard, api, websocket, reports

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager handling application startup and shutdown tasks."""
    print("==================================================")
    print("Next-Gen FastAPI Konn3ct Server starting up...")
    print("==================================================")
    
    # 1. Create database tables if they do not exist
    Base.metadata.create_all(bind=engine)
    
    # Run dynamic SQLite migrations for new metrics columns using raw sqlite3 connection
    import sqlite3
    db_path = os.path.join(PROJECT_ROOT, "konn3ct.db")
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        new_cols = [
            ("ack_latency", "REAL DEFAULT 0.0"),
            ("peak_latency", "REAL DEFAULT 0.0"),
            ("join_rate", "REAL DEFAULT 0.0"),
            ("avg_join_time", "REAL DEFAULT 0.0"),
            ("mps", "REAL DEFAULT 0.0"),
            ("eps", "REAL DEFAULT 0.0"),
            ("net_throughput_kbps", "REAL DEFAULT 0.0"),
            ("active_bots", "INTEGER DEFAULT 0")
        ]
        for col_name, col_type in new_cols:
            try:
                cur.execute(f"ALTER TABLE session_metrics ADD COLUMN {col_name} {col_type}")
                conn.commit()
                print(f"Migration: Added column '{col_name}' to 'session_metrics' table.")
            except sqlite3.OperationalError as e:
                # If column already exists, sqlite3 throws an OperationalError
                if "duplicate column name" in str(e) or "already exists" in str(e):
                    pass
                else:
                    print(f"Migration warning for column {col_name}: {e}")
                    
        # configurations table migrations (SLA & Browser Launch columns)
        cfg_cols = [
            ("sla_thresholds", "TEXT"),
            ("browser_launch_options", "TEXT"),
            ("viewer_bots", "TEXT DEFAULT '6-10000'")
        ]
        for col_name, col_type in cfg_cols:
            try:
                cur.execute(f"ALTER TABLE configurations ADD COLUMN {col_name} {col_type}")
                conn.commit()
                print(f"Migration: Added column '{col_name}' to 'configurations' table.")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e) or "already exists" in str(e):
                    pass
                else:
                    print(f"Migration warning for configurations column {col_name}: {e}")
                    
        conn.close()
    except Exception as mig_err:
        print(f"Migration failed: {mig_err}")
        
    # 2. Inspect database and re-adopt running processes
    db = SessionLocal()
    try:
        await adopt_running_sessions(db)
    except Exception as db_err:
        print(f"Orphaned session re-adoption failed: {db_err}")
    finally:
        db.close()
        
    yield
    
    print("FastAPI Konn3ct Server shutting down gracefully.")

app = FastAPI(
    title="Konn3ct Load Testing Framework",
    description="Modernized FastAPI-based Load Testing Dashboard and Orchestration Engine",
    version="2.0.0",
    lifespan=lifespan
)

# Setup CORS for development and integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files folder
app.mount("/static", StaticFiles(directory=os.path.join(PROJECT_ROOT, "static")), name="static")

# Register routers
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(websocket.router)
# Include the api router under /api or mount as is (since some routes are under /api and others are top-level)
app.include_router(api.router)

if __name__ == "__main__":
    print("URL: http://localhost:9000/")
    uvicorn.run("app:app", host="0.0.0.0", port=9000, reload=True)
