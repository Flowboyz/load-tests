from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash
from database import Base

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default='Viewer', nullable=False)  # Admin, Operator, Viewer
    api_key = Column(String(120), unique=True, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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

class Configuration(Base):
    __tablename__ = 'configurations'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    
    # Bot/room configurations
    room = Column(String(100), default='testinggg')
    bots = Column(Integer, default=50)
    stagger = Column(Float, default=1.0)
    batch = Column(Integer, default=3)
    concurrency = Column(Integer, default=100)
    leave = Column(Integer, default=0)
    
    # WebRTC/Media configurations
    webrtc_enabled = Column(Boolean, default=False)
    media_quality = Column(String(20), default='medium')
    max_subscriptions = Column(Integer, default=2)
    decode_downlink = Column(Boolean, default=False)
    
    # Dynamic Scenario configurations
    test_scenarios = Column(String(255), default='camera_toggle,mic_toggle,hand_raise,chat')
    action_interval = Column(Float, default=30.0)
    chat_interval = Column(Float, default=60.0)
    confirm_timeout = Column(Float, default=5.0)
    max_retries = Column(Integer, default=5)
    
    # Enable/Disable triggers (negative conditions)
    no_chat = Column(Boolean, default=False)
    no_camera = Column(Boolean, default=False)
    no_mic = Column(Boolean, default=False)
    no_handraise = Column(Boolean, default=False)
    no_screen_share = Column(Boolean, default=False)
    no_cross_confirm = Column(Boolean, default=False)
    
    # Endpoint and auth configurations
    frontend = Column(String(255), default='https://edge.konn3ct.net')
    signal = Column(String(255), default='konn3ctedge.konn3ct.net')
    jwt_secret = Column(String(255), nullable=True)
    
    # Bot specific identifiers
    host_bot_id = Column(Integer, default=1)
    presenter_bot_id = Column(Integer, default=2)
    
    # Network condition distributions
    network_conditions = Column(Text, default='ethernet:20,wi-fi:50,4g:20,3g:10')
    network_degradation = Column(Boolean, default=False)
    degradation_interval = Column(Integer, default=300)
    
    # Browser/OS/Device distributions
    browser_distribution = Column(Text, default='chrome:30,safari:20,firefox:15,edge:10,brave:5,chrome_mobile:10,safari_mobile:5,opera:3,samsung:2')
    device_distribution = Column(Text, default='desktop:70,mobile:20,tablet:10')
    os_distribution = Column(Text, default='windows:40,macos:30,linux:10,ios:12,android:8')
    
    # SLA & Browser Launch parameters (JSON Text fields)
    viewer_bots = Column(Text, default='6-10000')
    sla_thresholds = Column(Text, nullable=True)
    browser_launch_options = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        # We fetch all mapped columns dynamically
        return {col.name: getattr(self, col.name) for col in self.__table__.columns}

class TestSession(Base):
    __tablename__ = 'test_sessions'
    
    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey('configurations.id', ondelete='SET NULL'), nullable=True)
    name = Column(String(100), nullable=False)
    status = Column(String(20), default='pending', nullable=False)  # pending, running, paused, completed, stopped, failed
    pid = Column(Integer, nullable=True)
    
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    
    # Output file paths
    report_log_path = Column(String(255), nullable=True)
    report_docx_path = Column(String(255), nullable=True)
    report_pdf_path = Column(String(255), nullable=True)
    report_csv_path = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Relationship to configuration
    config = relationship('Configuration', backref='sessions')

    def to_dict(self):
        return {
            "id": self.id,
            "config_id": self.config_id,
            "name": self.name,
            "status": self.status,
            "pid": self.pid,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "report_log_path": self.report_log_path,
            "report_docx_path": self.report_docx_path,
            "report_pdf_path": self.report_pdf_path,
            "report_csv_path": self.report_csv_path,
            "error_message": self.error_message
        }

class SessionMetric(Base):
    __tablename__ = 'session_metrics'
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('test_sessions.id', ondelete='CASCADE'), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Bot status counts
    connected_bots = Column(Integer, default=0)
    connecting_bots = Column(Integer, default=0)
    failed_bots = Column(Integer, default=0)
    reconnecting_bots = Column(Integer, default=0)
    active_bots = Column(Integer, default=0)
    
    # Host resource metrics
    cpu_usage = Column(Float, default=0.0)
    ram_usage = Column(Float, default=0.0)
    net_throughput_kbps = Column(Float, default=0.0)
    
    # WebRTC quality metrics
    avg_latency = Column(Float, default=0.0)
    ack_latency = Column(Float, default=0.0)
    peak_latency = Column(Float, default=0.0)
    packet_loss = Column(Float, default=0.0)
    jitter = Column(Float, default=0.0)
    bitrate = Column(Integer, default=0)  # in kbps
    
    # Load test activity metrics
    join_rate = Column(Float, default=0.0)
    avg_join_time = Column(Float, default=0.0)
    mps = Column(Float, default=0.0)
    eps = Column(Float, default=0.0)
    
    session = relationship('TestSession', backref='metrics')

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
