import os
from flask import Flask, render_template, redirect, url_for, request
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
        
    app.config['SECRET_KEY'] = os.environ.get("DASHBOARD_SECRET_KEY", "konn3ct-super-secret-key-12345")
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Run self-healing SQLite migrations
    import sqlite3
    if db_uri.startswith("sqlite:///"):
        db_path = db_uri.replace("sqlite:///", "")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
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
    
    # Web UI Page Routes (Jinja static wrappers)
    @app.route('/')
    def index():
        token = request.cookies.get('token')
        if not token:
            return redirect(url_for('login_page'))
        return render_template('dashboard.html')
        
    @app.route('/login')
    def login_page():
        token = request.cookies.get('token')
        if token:
            return redirect(url_for('index'))
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
