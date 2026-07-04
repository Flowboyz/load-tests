import os
from flask import Flask, render_template, redirect, url_for, request, make_response
from flask_socketio import SocketIO, join_room, leave_room
from app.models import db, User, Configuration, TestSession
from app.auth import auth_bp
from app.routes import api_bp

socketio = SocketIO(cors_allowed_origins="*")

def create_app(db_uri=None):
    app = Flask(__name__)
    
    # Configuration paths
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not db_uri:
        db_path = os.path.join(project_root, 'konn3ct.db')
        db_uri = f'sqlite:///{db_path}'
        
    secret_key = os.environ.get("DASHBOARD_SECRET_KEY", "konn3ct-super-secret-key-12345-secure-64bytes-key-layout-standard")
    if len(secret_key) < 32:
        secret_key = secret_key.ljust(32, "x")
    app.config['SECRET_KEY'] = secret_key
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Run self-healing SQLite migrations
    import sqlite3
    if db_uri.startswith("sqlite:///"):
        db_path = db_uri.replace("sqlite:///", "")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 1. Update test_sessions table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='test_sessions'")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(test_sessions)")
                columns = [col[1] for col in cursor.fetchall()]
                if "accumulated_duration" not in columns:
                    cursor.execute("ALTER TABLE test_sessions ADD COLUMN accumulated_duration INTEGER DEFAULT 0")
                    print("Self-healing: added accumulated_duration column to test_sessions table")
                if "last_resume_time" not in columns:
                    cursor.execute("ALTER TABLE test_sessions ADD COLUMN last_resume_time DATETIME")
                    print("Self-healing: added last_resume_time column to test_sessions table")
                conn.commit()
                
            # 2. Update configurations table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='configurations'")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(configurations)")
                cfg_columns = [col[1] for col in cursor.fetchall()]
                if "sla_success_rate" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN sla_success_rate REAL DEFAULT 95.0")
                    print("Self-healing: added sla_success_rate column to configurations table")
                if "sla_latency" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN sla_latency REAL DEFAULT 500.0")
                    print("Self-healing: added sla_latency column to configurations table")
                if "sla_packet_loss" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN sla_packet_loss REAL DEFAULT 2.0")
                    print("Self-healing: added sla_packet_loss column to configurations table")
                if "sla_jitter" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN sla_jitter REAL DEFAULT 30.0")
                    print("Self-healing: added sla_jitter column to configurations table")
                if "cross_confirm_limit" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN cross_confirm_limit INTEGER DEFAULT 10")
                    print("Self-healing: added cross_confirm_limit column to configurations table")
                if "camera_publishers" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN camera_publishers TEXT DEFAULT '1,2,3,4,5'")
                    print("Self-healing: added camera_publishers column to configurations table")
                if "screen_share_publishers" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN screen_share_publishers TEXT DEFAULT '2'")
                    print("Self-healing: added screen_share_publishers column to configurations table")
                if "mic_publishers" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN mic_publishers TEXT DEFAULT '1,2,3,4,5'")
                    print("Self-healing: added mic_publishers column to configurations table")
                if "viewer_bots" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN viewer_bots TEXT DEFAULT '6-1000'")
                    print("Self-healing: added viewer_bots column to configurations table")
                if "viewer_mode" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN viewer_mode TEXT DEFAULT 'receive_only'")
                    print("Self-healing: added viewer_mode column to configurations table")
                if "auto_camera" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN auto_camera BOOLEAN DEFAULT 0")
                    print("Self-healing: added auto_camera column to configurations table")
                if "auto_mic" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN auto_mic BOOLEAN DEFAULT 0")
                    print("Self-healing: added auto_mic column to configurations table")
                if "auto_screen_share" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN auto_screen_share BOOLEAN DEFAULT 0")
                    print("Self-healing: added auto_screen_share column to configurations table")
                if "disable_ram_scenario_opt" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN disable_ram_scenario_opt BOOLEAN DEFAULT 0")
                    print("Self-healing: added disable_ram_scenario_opt column to configurations table")
                if "refresh_bots" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN refresh_bots INTEGER DEFAULT 0")
                    print("Self-healing: added refresh_bots column to configurations table")
                if "disable_abnormal_behavior" not in cfg_columns:
                    cursor.execute("ALTER TABLE configurations ADD COLUMN disable_abnormal_behavior BOOLEAN DEFAULT 0")
                    print("Self-healing: added disable_abnormal_behavior column to configurations table")
                conn.commit()
                
            conn.close()
        except Exception as e:
            print(f"Self-healing SQLite migration failed: {e}")

    # Initialize plugins
    db.init_app(app)
    socketio.init_app(app)
    
    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # Self-healing database cleanup and adoption of running sessions on startup
    with app.app_context():
        try:
            db.create_all()
            from app.runner import adopt_running_sessions
            adopt_running_sessions(app, socketio)
        except Exception as e:
            print(f"Startup database cleanup/adoption failed: {e}")
            
    # Auto-create mobile UI test directory structure on startup
    try:
        mobile_dir = os.path.join(project_root, "mobile_ui_tests")
        flows_dir = os.path.join(mobile_dir, "flows")
        os.makedirs(flows_dir, exist_ok=True)
    except Exception as e:
        print(f"Failed to create mobile UI test directories: {e}")
    
    # Web UI Page Routes (Jinja static wrappers)
    @app.route('/')
    def index():
        token = request.cookies.get('token')
        if token:
            try:
                import jwt
                from app.auth import SECRET_KEY
                jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
                return render_template('dashboard.html')
            except Exception:
                pass
        return redirect(url_for('login_page'))
        
    @app.route('/login')
    def login_page():
        token = request.cookies.get('token')
        if token:
            try:
                import jwt
                from app.auth import SECRET_KEY
                jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
                return redirect(url_for('index'))
            except Exception:
                # If invalid or expired token cookie, clear it to avoid loops
                response = make_response(render_template('login.html'))
                response.delete_cookie('token')
                return response
        return render_template('login.html')
        
    # --- Socket.IO Room Coordination ---
    @socketio.on('join')
    def on_join(data):
        session_id = data.get('session_id')
        if session_id:
            room = f"session_{session_id}"
            join_room(room)
            print(f"Socket Client joined room: {room}")
            
    @socketio.on('leave')
    def on_leave(data):
        session_id = data.get('session_id')
        if session_id:
            room = f"session_{session_id}"
            leave_room(room)
            print(f"Socket Client left room: {room}")
            
    return app
