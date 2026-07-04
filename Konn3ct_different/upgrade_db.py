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
        
        # 1. Create tables if they do not exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(80) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) DEFAULT 'Viewer' NOT NULL,
            api_key VARCHAR(120) UNIQUE,
            created_at DATETIME
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS configurations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) UNIQUE NOT NULL,
            description TEXT,
            room VARCHAR(100) DEFAULT 'testinggg',
            bots INTEGER DEFAULT 50,
            stagger REAL DEFAULT 1.0,
            batch INTEGER DEFAULT 3,
            concurrency INTEGER DEFAULT 100,
            leave INTEGER DEFAULT 0,
            start_id INTEGER DEFAULT 1,
            webrtc_enabled BOOLEAN DEFAULT 0,
            media_quality VARCHAR(20) DEFAULT 'medium',
            max_subscriptions INTEGER DEFAULT 2,
            decode_downlink BOOLEAN DEFAULT 0,
            test_scenarios VARCHAR(255) DEFAULT 'camera_toggle,mic_toggle,hand_raise,chat',
            action_interval REAL DEFAULT 30.0,
            chat_interval REAL DEFAULT 60.0,
            confirm_timeout REAL DEFAULT 5.0,
            max_retries INTEGER DEFAULT 5,
            no_chat BOOLEAN DEFAULT 0,
            no_camera BOOLEAN DEFAULT 0,
            no_mic BOOLEAN DEFAULT 0,
            no_handraise BOOLEAN DEFAULT 0,
            no_screen_share BOOLEAN DEFAULT 0,
            no_cross_confirm BOOLEAN DEFAULT 0,
            frontend VARCHAR(255) DEFAULT 'https://edge.konn3ct.net',
            signal VARCHAR(255) DEFAULT 'konn3ctedge.konn3ct.net',
            jwt_secret VARCHAR(255),
            host_bot_id INTEGER DEFAULT 1,
            presenter_bot_id INTEGER DEFAULT 2,
            network_conditions TEXT DEFAULT 'ethernet:20,wi-fi:50,4g:20,3g:10',
            network_degradation BOOLEAN DEFAULT 0,
            degradation_interval INTEGER DEFAULT 300,
            browser_distribution TEXT DEFAULT 'chrome:30,safari:20,firefox:15,edge:10,brave:5,chrome_mobile:10,safari_mobile:5,opera:3,samsung:2',
            device_distribution TEXT DEFAULT 'desktop:70,mobile:20,tablet:10',
            os_distribution TEXT DEFAULT 'windows:40,macos:30,linux:10,ios:12,android:8',
            sla_success_rate REAL DEFAULT 95.0,
            sla_latency REAL DEFAULT 500.0,
            sla_packet_loss REAL DEFAULT 2.0,
            sla_jitter REAL DEFAULT 30.0,
            cross_confirm_limit INTEGER DEFAULT 10,
            camera_publishers TEXT DEFAULT '1,2,3,4,5',
            screen_share_publishers TEXT DEFAULT '2',
            mic_publishers TEXT DEFAULT '1,2,3,4,5',
            viewer_bots TEXT DEFAULT '6-10000',
            viewer_mode TEXT DEFAULT 'receive_only',
            auto_camera BOOLEAN DEFAULT 0,
            auto_mic BOOLEAN DEFAULT 0,
            auto_screen_share BOOLEAN DEFAULT 0,
            disable_ram_scenario_opt BOOLEAN DEFAULT 0,
            refresh_bots INTEGER DEFAULT 0,
            disable_abnormal_behavior BOOLEAN DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id INTEGER REFERENCES configurations(id) ON DELETE SET NULL,
            name VARCHAR(100) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending' NOT NULL,
            pid INTEGER,
            started_at DATETIME,
            ended_at DATETIME,
            accumulated_duration INTEGER DEFAULT 0,
            last_resume_time DATETIME,
            report_log_path VARCHAR(255),
            report_docx_path VARCHAR(255),
            report_pdf_path VARCHAR(255),
            report_csv_path VARCHAR(255),
            error_message TEXT,
            total_expected_workers INTEGER DEFAULT 1,
            uploaded_workers_count INTEGER DEFAULT 0
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address VARCHAR(100) UNIQUE NOT NULL,
            status VARCHAR(20) DEFAULT 'idle' NOT NULL,
            last_seen DATETIME
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER REFERENCES test_sessions(id) ON DELETE CASCADE,
            timestamp DATETIME,
            connected_bots INTEGER DEFAULT 0,
            connecting_bots INTEGER DEFAULT 0,
            failed_bots INTEGER DEFAULT 0,
            reconnecting_bots INTEGER DEFAULT 0,
            cpu_usage REAL DEFAULT 0.0,
            ram_usage REAL DEFAULT 0.0,
            avg_latency REAL DEFAULT 0.0,
            packet_loss REAL DEFAULT 0.0,
            jitter REAL DEFAULT 0.0,
            bitrate INTEGER DEFAULT 0
        )
        """)
        conn.commit()
        
        # 2. Add any missing columns dynamically (in case table exists but missing columns)
        def add_missing_columns(table_name, expected_columns):
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            for col_name, col_def in expected_columns.items():
                if col_name not in columns:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}")
                    print(f" -> Added column: {table_name}.{col_name}")
            conn.commit()

        # Check users
        users_cols = {
            "api_key": "VARCHAR(120)",
            "role": "VARCHAR(20) DEFAULT 'Viewer' NOT NULL",
            "created_at": "DATETIME"
        }
        add_missing_columns("users", users_cols)

        # Check configurations
        config_cols = {
            "sla_success_rate": "REAL DEFAULT 95.0",
            "sla_latency": "REAL DEFAULT 500.0",
            "sla_packet_loss": "REAL DEFAULT 2.0",
            "sla_jitter": "REAL DEFAULT 30.0",
            "cross_confirm_limit": "INTEGER DEFAULT 10",
            "camera_publishers": "TEXT DEFAULT '1,2,3,4,5'",
            "screen_share_publishers": "TEXT DEFAULT '2'",
            "mic_publishers": "TEXT DEFAULT '1,2,3,4,5'",
            "viewer_bots": "TEXT DEFAULT '6-10000'",
            "viewer_mode": "TEXT DEFAULT 'receive_only'",
            "auto_camera": "BOOLEAN DEFAULT 0",
            "auto_mic": "BOOLEAN DEFAULT 0",
            "auto_screen_share": "BOOLEAN DEFAULT 0",
            "disable_ram_scenario_opt": "BOOLEAN DEFAULT 0",
            "refresh_bots": "INTEGER DEFAULT 0",
            "disable_abnormal_behavior": "BOOLEAN DEFAULT 0",
            "start_id": "INTEGER DEFAULT 1"
        }
        add_missing_columns("configurations", config_cols)
        
        # Check test_sessions
        sessions_cols = {
            "accumulated_duration": "INTEGER DEFAULT 0",
            "last_resume_time": "DATETIME",
            "report_log_path": "VARCHAR(255)",
            "report_docx_path": "VARCHAR(255)",
            "report_pdf_path": "VARCHAR(255)",
            "report_csv_path": "VARCHAR(255)",
            "error_message": "TEXT",
            "total_expected_workers": "INTEGER DEFAULT 1",
            "uploaded_workers_count": "INTEGER DEFAULT 0"
        }
        add_missing_columns("test_sessions", sessions_cols)
        
        # Check worker_nodes
        worker_cols = {
            "ip_address": "VARCHAR(100) UNIQUE NOT NULL",
            "status": "VARCHAR(20) DEFAULT 'idle' NOT NULL",
            "last_seen": "DATETIME"
        }
        add_missing_columns("worker_nodes", worker_cols)
        
        # Check session_metrics
        metrics_cols = {
            "connected_bots": "INTEGER DEFAULT 0",
            "connecting_bots": "INTEGER DEFAULT 0",
            "failed_bots": "INTEGER DEFAULT 0",
            "reconnecting_bots": "INTEGER DEFAULT 0",
            "cpu_usage": "REAL DEFAULT 0.0",
            "ram_usage": "REAL DEFAULT 0.0",
            "avg_latency": "REAL DEFAULT 0.0",
            "packet_loss": "REAL DEFAULT 0.0",
            "jitter": "REAL DEFAULT 0.0",
            "bitrate": "INTEGER DEFAULT 0"
        }
        add_missing_columns("session_metrics", metrics_cols)
        
        conn.close()
        print("Database schema matches models exactly. Upgrade completed successfully!")
    except Exception as e:
        print(f"Database upgrade failed: {e}")

if __name__ == "__main__":
    upgrade()
