import os
import sqlite3
from app import create_app

def upgrade():
    app = create_app()
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    print(f"Resolving database migration for: {db_uri}")
    
    if not db_uri or not db_uri.startswith("sqlite:///"):
        print("Database is not SQLite or URI is missing. Skipping local SQLite upgrade.")
        return
        
    db_path = db_uri.replace("sqlite:///", "")
    print(f"Target database file: {os.path.abspath(db_path)}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. Update test_sessions table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='test_sessions'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(test_sessions)")
            columns = [col[1] for col in cursor.fetchall()]
            
            ts_adds = {
                "accumulated_duration": "INTEGER DEFAULT 0",
                "last_resume_time": "DATETIME"
            }
            for col_name, col_type in ts_adds.items():
                if col_name not in columns:
                    cursor.execute(f"ALTER TABLE test_sessions ADD COLUMN {col_name} {col_type}")
                    print(f" -> Added column: test_sessions.{col_name}")
            conn.commit()
            
        # 2. Update configurations table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='configurations'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(configurations)")
            cfg_columns = [col[1] for col in cursor.fetchall()]
            
            cfg_adds = {
                "sla_success_rate": "REAL DEFAULT 95.0",
                "sla_latency": "REAL DEFAULT 500.0",
                "sla_packet_loss": "REAL DEFAULT 2.0",
                "sla_jitter": "REAL DEFAULT 30.0",
                "cross_confirm_limit": "INTEGER DEFAULT 10",
                "camera_publishers": "TEXT DEFAULT '1,2,3,4,5'",
                "screen_share_publishers": "TEXT DEFAULT '2'",
                "mic_publishers": "TEXT DEFAULT '1,2,3,4,5'",
                "viewer_bots": "TEXT DEFAULT '6-1000'",
                "viewer_mode": "TEXT DEFAULT 'receive_only'",
                "auto_camera": "BOOLEAN DEFAULT 0",
                "auto_mic": "BOOLEAN DEFAULT 0",
                "auto_screen_share": "BOOLEAN DEFAULT 0"
            }
            for col_name, col_type in cfg_adds.items():
                if col_name not in cfg_columns:
                    cursor.execute(f"ALTER TABLE configurations ADD COLUMN {col_name} {col_type}")
                    print(f" -> Added column: configurations.{col_name}")
            conn.commit()
            
        conn.close()
        print("Database upgrade completed successfully!")
    except Exception as e:
        print(f"Database upgrade failed: {e}")

if __name__ == "__main__":
    upgrade()
