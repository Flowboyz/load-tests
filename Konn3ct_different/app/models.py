from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='Viewer', nullable=False)  # Admin, Operator, Viewer
    api_key = db.Column(db.String(120), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "api_key": self.api_key,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Configuration(db.Model):
    __tablename__ = 'configurations'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Bot/room configurations
    room = db.Column(db.String(100), default='testinggg')
    bots = db.Column(db.Integer, default=50)
    stagger = db.Column(db.Float, default=1.0)
    batch = db.Column(db.Integer, default=3)
    concurrency = db.Column(db.Integer, default=100)
    leave = db.Column(db.Integer, default=0)
    start_id = db.Column(db.Integer, default=1)
    
    # WebRTC/Media configurations
    webrtc_enabled = db.Column(db.Boolean, default=False)
    media_quality = db.Column(db.String(20), default='medium')
    max_subscriptions = db.Column(db.Integer, default=2)
    decode_downlink = db.Column(db.Boolean, default=False)
    
    # Dynamic Scenario configurations
    test_scenarios = db.Column(db.String(255), default='camera_toggle,mic_toggle,hand_raise,chat')
    action_interval = db.Column(db.Float, default=30.0)
    chat_interval = db.Column(db.Float, default=60.0)
    confirm_timeout = db.Column(db.Float, default=5.0)
    max_retries = db.Column(db.Integer, default=5)
    
    # Enable/Disable triggers (negative conditions)
    no_chat = db.Column(db.Boolean, default=False)
    no_camera = db.Column(db.Boolean, default=False)
    no_mic = db.Column(db.Boolean, default=False)
    no_handraise = db.Column(db.Boolean, default=False)
    no_screen_share = db.Column(db.Boolean, default=False)
    no_cross_confirm = db.Column(db.Boolean, default=False)
    
    # Endpoint and auth configurations
    frontend = db.Column(db.String(255), default='https://edge.konn3ct.net')
    signal = db.Column(db.String(255), default='konn3ctedge.konn3ct.net')
    jwt_secret = db.Column(db.String(255), nullable=True)
    
    # Bot specific identifiers
    host_bot_id = db.Column(db.Integer, default=1)
    presenter_bot_id = db.Column(db.Integer, default=2)
    
    # Network condition distributions
    network_conditions = db.Column(db.Text, default='ethernet:20,wi-fi:50,4g:20,3g:10')
    network_degradation = db.Column(db.Boolean, default=False)
    degradation_interval = db.Column(db.Integer, default=300)
    
    # Browser/OS/Device distributions
    browser_distribution = db.Column(db.Text, default='chrome:30,safari:20,firefox:15,edge:10,brave:5,chrome_mobile:10,safari_mobile:5,opera:3,samsung:2')
    device_distribution = db.Column(db.Text, default='desktop:70,mobile:20,tablet:10')
    os_distribution = db.Column(db.Text, default='windows:40,macos:30,linux:10,ios:12,android:8')
    
    # SLA thresholds configurations
    sla_success_rate = db.Column(db.Float, default=95.0, nullable=False)
    sla_latency = db.Column(db.Float, default=500.0, nullable=False)
    sla_packet_loss = db.Column(db.Float, default=2.0, nullable=False)
    sla_jitter = db.Column(db.Float, default=30.0, nullable=False)
    sla_join_latency = db.Column(db.Float, default=5.0, nullable=False)
    sla_min_fps = db.Column(db.Float, default=15.0, nullable=False)
    sla_max_disconnects = db.Column(db.Float, default=1.0, nullable=False)
    sla_min_bitrate = db.Column(db.Float, default=250.0, nullable=False)
    
    # RAM & Scenario Optimization
    cross_confirm_limit = db.Column(db.Integer, default=10, nullable=False)
    camera_publishers = db.Column(db.Text, default='1,2,3,4,5')
    screen_share_publishers = db.Column(db.Text, default='2')
    mic_publishers = db.Column(db.Text, default='1,2,3,4,5')
    viewer_bots = db.Column(db.Text, default='6-10000')
    viewer_mode = db.Column(db.String(50), default='receive_only')
    auto_camera = db.Column(db.Boolean, default=False)
    auto_mic = db.Column(db.Boolean, default=False)
    auto_screen_share = db.Column(db.Boolean, default=False)
    disable_ram_scenario_opt = db.Column(db.Boolean, default=False)
    refresh_bots = db.Column(db.Integer, default=0)
    disable_abnormal_behavior = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class TestSession(db.Model):
    __tablename__ = 'test_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey('configurations.id', ondelete='SET NULL'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, running, paused, completed, stopped, failed
    pid = db.Column(db.Integer, nullable=True)
    
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    
    # Session Timer attributes
    accumulated_duration = db.Column(db.Integer, default=0, nullable=False)
    last_resume_time = db.Column(db.DateTime, nullable=True)
    
    # Output file paths
    report_log_path = db.Column(db.String(255), nullable=True)
    report_docx_path = db.Column(db.String(255), nullable=True)
    report_pdf_path = db.Column(db.String(255), nullable=True)
    report_csv_path = db.Column(db.String(255), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    # Cluster scaling variables
    total_expected_workers = db.Column(db.Integer, default=1, nullable=False)
    uploaded_workers_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Relationship to configuration
    config = db.relationship('Configuration', backref='sessions')

    def to_dict(self):
        elapsed = self.accumulated_duration
        if self.status == 'running' and self.last_resume_time:
            elapsed += int((datetime.utcnow() - self.last_resume_time).total_seconds())
            
        return {
            "id": self.id,
            "config_id": self.config_id,
            "config": self.config.to_dict() if self.config else None,
            "name": self.name,
            "status": self.status,
            "pid": self.pid,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "report_log_path": self.report_log_path,
            "report_docx_path": self.report_docx_path,
            "report_pdf_path": self.report_pdf_path,
            "report_csv_path": self.report_csv_path,
            "error_message": self.error_message,
            "accumulated_duration": self.accumulated_duration,
            "last_resume_time": self.last_resume_time.isoformat() if self.last_resume_time else None,
            "elapsed_seconds": elapsed,
            "total_expected_workers": self.total_expected_workers,
            "uploaded_workers_count": self.uploaded_workers_count
        }

class WorkerNode(db.Model):
    __tablename__ = 'worker_nodes'
    
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(20), default='idle', nullable=False)  # idle, active, offline
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "ip_address": self.ip_address,
            "status": self.status,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None
        }

class SessionMetric(db.Model):
    __tablename__ = 'session_metrics'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('test_sessions.id', ondelete='CASCADE'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Bot status counts
    connected_bots = db.Column(db.Integer, default=0)
    connecting_bots = db.Column(db.Integer, default=0)
    failed_bots = db.Column(db.Integer, default=0)
    reconnecting_bots = db.Column(db.Integer, default=0)
    
    # Host resource metrics
    cpu_usage = db.Column(db.Float, default=0.0)
    ram_usage = db.Column(db.Float, default=0.0)
    
    # WebRTC quality metrics
    avg_latency = db.Column(db.Float, default=0.0)
    packet_loss = db.Column(db.Float, default=0.0)
    jitter = db.Column(db.Float, default=0.0)
    bitrate = db.Column(db.Integer, default=0)  # in kbps
    
    session = db.relationship('TestSession', backref=db.backref('metrics', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "connected_bots": self.connected_bots,
            "connecting_bots": self.connecting_bots,
            "failed_bots": self.failed_bots,
            "reconnecting_bots": self.reconnecting_bots,
            "cpu_usage": self.cpu_usage,
            "ram_usage": self.ram_usage,
            "avg_latency": self.avg_latency,
            "packet_loss": self.packet_loss,
            "jitter": self.jitter,
            "bitrate": self.bitrate
        }
