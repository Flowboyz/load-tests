import os
import json
import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, HTTPException, status, Response
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from database import get_db
from models import User, Configuration, TestSession, SessionMetric
from auth import get_current_user, RoleChecker, SECRET_KEY, ALGORITHM
from services.bot_runner import (
    start_session, pause_session, resume_session, stop_session,
    get_session_dir, RUNNING_SESSIONS
)

router = APIRouter()

# Schema validators for requests
class LoginRequest(BaseModel):
    username: str
    password: str

class ConfigurationCreateUpdate(BaseModel):
    name: str
    description: Optional[str] = None
    room: Optional[str] = 'testinggg'
    bots: Optional[int] = 50
    stagger: Optional[float] = 1.0
    batch: Optional[int] = 3
    concurrency: Optional[int] = 100
    leave: Optional[int] = 0
    webrtc_enabled: Optional[bool] = False
    media_quality: Optional[str] = 'medium'
    max_subscriptions: Optional[int] = 2
    decode_downlink: Optional[bool] = False
    test_scenarios: Optional[str] = 'camera_toggle,mic_toggle,hand_raise,chat'
    action_interval: Optional[float] = 30.0
    chat_interval: Optional[float] = 60.0
    confirm_timeout: Optional[float] = 5.0
    max_retries: Optional[int] = 5
    no_chat: Optional[bool] = False
    no_camera: Optional[bool] = False
    no_mic: Optional[bool] = False
    no_handraise: Optional[bool] = False
    no_screen_share: Optional[bool] = False
    no_cross_confirm: Optional[bool] = False
    frontend: Optional[str] = 'https://edge.konn3ct.net'
    signal: Optional[str] = 'konn3ctedge.konn3ct.net'
    jwt_secret: Optional[str] = None
    host_bot_id: Optional[int] = 1
    presenter_bot_id: Optional[int] = 2
    network_conditions: Optional[str] = 'ethernet:20,wi-fi:50,4g:20,3g:10'
    network_degradation: Optional[bool] = False
    degradation_interval: Optional[int] = 300
    browser_distribution: Optional[str] = 'chrome:30,safari:20,firefox:15,edge:10,brave:5,chrome_mobile:10,safari_mobile:5,opera:3,samsung:2'
    device_distribution: Optional[str] = 'desktop:70,mobile:20,tablet:10'
    os_distribution: Optional[str] = 'windows:40,macos:30,linux:10,ios:12,android:8'
    
    # SLA & Browser Launch parameters
    viewer_bots: Optional[str] = '6-10000'
    sla_thresholds: Optional[str] = None
    browser_launch_options: Optional[str] = None

class StartSessionRequest(BaseModel):
    config_id: Optional[int] = None
    session_name: Optional[str] = None
    # Ad-hoc parameter overrides support
    room: Optional[str] = None
    bots: Optional[int] = None
    stagger: Optional[float] = None
    batch: Optional[int] = None
    concurrency: Optional[int] = None
    leave: Optional[int] = None
    webrtc_enabled: Optional[bool] = None
    media_quality: Optional[str] = None
    max_subscriptions: Optional[int] = None
    decode_downlink: Optional[bool] = None
    test_scenarios: Optional[str] = None
    action_interval: Optional[float] = None
    chat_interval: Optional[float] = None
    confirm_timeout: Optional[float] = None
    max_retries: Optional[int] = None
    no_chat: Optional[bool] = None
    no_camera: Optional[bool] = None
    no_mic: Optional[bool] = None
    no_handraise: Optional[bool] = None
    no_screen_share: Optional[bool] = None
    no_cross_confirm: Optional[bool] = None
    frontend: Optional[str] = None
    signal: Optional[str] = None
    jwt_secret: Optional[str] = None
    host_bot_id: Optional[int] = None
    presenter_bot_id: Optional[int] = None
    network_conditions: Optional[str] = None
    network_degradation: Optional[bool] = None
    degradation_interval: Optional[int] = None
    browser_distribution: Optional[str] = None
    device_distribution: Optional[str] = None
    os_distribution: Optional[str] = None
    
    # SLA & Browser Launch overrides
    viewer_bots: Optional[str] = None
    sla_thresholds: Optional[str] = None
    browser_launch_options: Optional[str] = None

# --- Helper logic ---
def get_active_session(db: Session) -> Optional[TestSession]:
    return db.query(TestSession).filter(TestSession.status.in_(["running", "paused"])).order_by(TestSession.id.desc()).first()

# --- Auth Routes ---
@router.post("/api/auth/login")
async def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not user.check_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid credentials!")
        
    token = jwt.encode({
        'user_id': user.id,
        'role': user.role,
        'exp': datetime.utcnow() + timedelta(hours=24)
    }, SECRET_KEY, algorithm=ALGORITHM)
    
    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=24 * 60 * 60
    )
    return {"message": "Login successful!", "user": user.to_dict()}

@router.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="token")
    return {"message": "Logout successful!"}

@router.get("/api/auth/me")
async def me(current_user: User = Depends(get_current_user)):
    return current_user.to_dict()

# --- Configuration Presets CRUD ---
@router.get("/api/configurations")
async def get_configurations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    configs = db.query(Configuration).order_by(Configuration.created_at.desc()).all()
    return [c.to_dict() for c in configs]

@router.post("/api/configurations", status_code=201)
async def create_configuration(
    cfg_data: ConfigurationCreateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin", "Operator"]))
):
    if db.query(Configuration).filter(Configuration.name == cfg_data.name).first():
        raise HTTPException(status_code=400, detail="A configuration with this name already exists!")
        
    cfg = Configuration(**cfg_data.dict())
    db.add(cfg)
    db.commit()
    return cfg.to_dict()

@router.get("/api/configurations/{cfg_id}")
async def get_configuration(cfg_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cfg = db.query(Configuration).get(cfg_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration template not found!")
    return cfg.to_dict()

@router.put("/api/configurations/{cfg_id}")
async def update_configuration(
    cfg_id: int,
    cfg_data: ConfigurationCreateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin", "Operator"]))
):
    cfg = db.query(Configuration).get(cfg_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration template not found!")
        
    for k, v in cfg_data.dict(exclude_unset=True).items():
        setattr(cfg, k, v)
        
    db.commit()
    return cfg.to_dict()

@router.delete("/api/configurations/{cfg_id}")
async def delete_configuration(
    cfg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin"]))
):
    cfg = db.query(Configuration).get(cfg_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration template not found!")
    db.delete(cfg)
    db.commit()
    return {"message": "Configuration template deleted!"}

# --- SLA & Browser Launch Schemas & Endpoints ---
class SLAConfigUpdate(BaseModel):
    max_ack_latency: int
    max_join_time: int
    max_connection_time: int
    max_webrtc_setup_time: int
    max_ice_negotiation_time: int
    max_dtls_handshake_time: int
    max_packet_loss: float
    max_jitter: float
    min_success_rate: float
    max_cpu_usage: float
    max_memory_usage: float

class BrowserLaunchUpdate(BaseModel):
    use_fake_ui_for_media_stream: bool
    use_fake_device_for_media_stream: bool
    autoplay_policy: str
    disable_notifications: bool
    disable_popup_blocking: bool
    disable_infobars: bool
    disable_dev_shm_usage: bool
    no_sandbox: bool
    ignore_certificate_errors: bool
    disable_web_security: bool
    allow_running_insecure_content: bool
    custom_flags: str

@router.get("/api/configurations/{cfg_id}/sla")
async def get_sla_config(cfg_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cfg = db.query(Configuration).get(cfg_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration template not found!")
    if cfg.sla_thresholds:
        try:
            return json.loads(cfg.sla_thresholds)
        except Exception:
            pass
    return {
        "max_ack_latency": 500,
        "max_join_time": 2000,
        "max_connection_time": 15000,
        "max_webrtc_setup_time": 5000,
        "max_ice_negotiation_time": 500,
        "max_dtls_handshake_time": 500,
        "max_packet_loss": 2.0,
        "max_jitter": 30.0,
        "min_success_rate": 99.0,
        "max_cpu_usage": 60.0,
        "max_memory_usage": 70.0
    }

@router.put("/api/configurations/{cfg_id}/sla")
async def update_sla_config(
    cfg_id: int,
    sla_data: SLAConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin", "Operator"]))
):
    cfg = db.query(Configuration).get(cfg_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration template not found!")
    if sla_data.max_ack_latency <= 0 or sla_data.max_join_time <= 0:
        raise HTTPException(status_code=400, detail="Thresholds must be positive integers.")
    if not (0 <= sla_data.max_packet_loss <= 100) or not (0 <= sla_data.min_success_rate <= 100):
        raise HTTPException(status_code=400, detail="Percentages must be between 0 and 100.")
    cfg.sla_thresholds = json.dumps(sla_data.dict())
    db.commit()
    return json.loads(cfg.sla_thresholds)

@router.get("/api/configurations/{cfg_id}/browser-launch")
async def get_browser_launch_config(cfg_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cfg = db.query(Configuration).get(cfg_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration template not found!")
    if cfg.browser_launch_options:
        try:
            return json.loads(cfg.browser_launch_options)
        except Exception:
            pass
    return {
        "use_fake_ui_for_media_stream": True,
        "use_fake_device_for_media_stream": True,
        "autoplay_policy": "no-user-gesture-required",
        "disable_notifications": True,
        "disable_popup_blocking": True,
        "disable_infobars": True,
        "disable_dev_shm_usage": True,
        "no_sandbox": True,
        "ignore_certificate_errors": True,
        "disable_web_security": True,
        "allow_running_insecure_content": True,
        "custom_flags": ""
    }

@router.put("/api/configurations/{cfg_id}/browser-launch")
async def update_browser_launch_config(
    cfg_id: int,
    launch_data: BrowserLaunchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin", "Operator"]))
):
    cfg = db.query(Configuration).get(cfg_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration template not found!")
    cfg.browser_launch_options = json.dumps(launch_data.dict())
    db.commit()
    return json.loads(cfg.browser_launch_options)

@router.post("/api/configurations/{cfg_id}/save")
async def save_configuration_preset(
    cfg_id: int,
    cfg_data: ConfigurationCreateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin", "Operator"]))
):
    cfg = db.query(Configuration).get(cfg_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration template not found!")
    for k, v in cfg_data.dict(exclude_unset=True).items():
        if v is not None:
            setattr(cfg, k, v)
    db.commit()
    return cfg.to_dict()

@router.post("/api/configurations/{cfg_id}/load")
async def load_configuration_preset(
    cfg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cfg = db.query(Configuration).get(cfg_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration template not found!")
    return cfg.to_dict()

# --- Test Sessions Execution Routes ---
@router.get("/api/sessions")
async def get_sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sessions = db.query(TestSession).order_by(
        TestSession.started_at.desc() if TestSession.started_at else TestSession.id.desc()
    ).all()
    return [s.to_dict() for s in sessions]

@router.get("/api/sessions/{session_id}")
async def get_session(session_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = db.query(TestSession).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found!")
    result = session.to_dict()
    if session.config:
        result["config"] = session.config.to_dict()
        
    # Calculate elapsed active duration by reading control.json timing details
    session_dir = get_session_dir(session_id)
    control_file = os.path.join(session_dir, "control.json")
    elapsed_ms = 0.0
    paused = False
    
    if session.status in ("running", "paused") and os.path.exists(control_file):
        try:
            with open(control_file, "r") as f:
                cdata = json.load(f)
                paused = cdata.get("paused", False)
                started_at_str = cdata.get("started_at")
                total_paused_ms = cdata.get("total_paused_ms", 0.0)
                last_paused_at_str = cdata.get("last_paused_at")
                
                if started_at_str:
                    t_start = datetime.fromisoformat(started_at_str)
                    if paused and last_paused_at_str:
                        t_pause = datetime.fromisoformat(last_paused_at_str)
                        elapsed_ms = (t_pause - t_start).total_seconds() * 1000.0 - total_paused_ms
                    else:
                        elapsed_ms = (datetime.utcnow() - t_start).total_seconds() * 1000.0 - total_paused_ms
        except Exception:
            pass
    elif session.ended_at and session.started_at:
        # Check if control_file contains pause duration for finished sessions
        total_paused_ms = 0.0
        if os.path.exists(control_file):
            try:
                with open(control_file, "r") as f:
                    cdata = json.load(f)
                    total_paused_ms = cdata.get("total_paused_ms", 0.0)
            except Exception:
                pass
        elapsed_ms = (session.ended_at - session.started_at).total_seconds() * 1000.0 - total_paused_ms
        
    if elapsed_ms < 0.0:
        elapsed_ms = 0.0
        
    result["elapsed_ms"] = elapsed_ms
    result["paused"] = paused
    return result

@router.post("/api/sessions/start", status_code=201)
async def start_test(
    req: StartSessionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin", "Operator"]))
):
    # Check for active running session
    if get_active_session(db):
        raise HTTPException(status_code=400, detail="A load test session is currently running. Stop it first.")
        
    session_name = req.session_name
    if not session_name:
        session_name = f"Test Run - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        
    cfg = None
    if req.config_id:
        cfg = db.query(Configuration).get(req.config_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Configuration template not found!")
            
    if not cfg:
        # Create an ad-hoc transient configuration for this execution
        name = f"Ad-hoc Temp {int(datetime.utcnow().timestamp())}"
        data = req.dict(exclude={'config_id', 'session_name'}, exclude_unset=True)
        # Apply defaults for unset transient config parameters
        temp_cfg = ConfigurationCreateUpdate(name=name, **data)
        cfg = Configuration(**temp_cfg.dict())
        db.add(cfg)
        db.commit()
        db.refresh(cfg)

    # Create new session entry
    new_sess = TestSession(
        config_id=cfg.id,
        name=session_name,
        status="pending"
    )
    db.add(new_sess)
    db.commit()
    db.refresh(new_sess)
    
    # Trigger runner background process
    start_session(new_sess.id)
    
    return new_sess.to_dict()

@router.post("/api/sessions/{session_id}/pause")
async def pause_test(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin", "Operator"]))
):
    session = db.query(TestSession).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found!")
    if session.status != "running":
        raise HTTPException(status_code=400, detail="Only running sessions can be paused!")
        
    success = pause_session(session_id)
    if success:
        session.status = "paused"
        db.commit()
        from routers.websocket import broadcast_status_change
        await broadcast_status_change(session_id, "paused")
        return {"message": "Test session paused."}
        
    raise HTTPException(status_code=500, detail="Failed to pause test session.")

@router.post("/api/sessions/{session_id}/resume")
async def resume_test(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin", "Operator"]))
):
    session = db.query(TestSession).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found!")
    if session.status != "paused":
        raise HTTPException(status_code=400, detail="Only paused sessions can be resumed!")
        
    success = resume_session(session_id)
    if success:
        session.status = "running"
        db.commit()
        from routers.websocket import broadcast_status_change
        await broadcast_status_change(session_id, "running")
        return {"message": "Test session resumed."}
        
    raise HTTPException(status_code=500, detail="Failed to resume test session.")

@router.post("/api/sessions/{session_id}/stop")
async def stop_test_run(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["Admin", "Operator"]))
):
    session = db.query(TestSession).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found!")
    if session.status not in ("running", "paused"):
        raise HTTPException(status_code=400, detail="Session is not active!")
        
    success = stop_session(session_id)
    
    session.status = "stopped"
    session.ended_at = datetime.utcnow()
    db.commit()
    
    from routers.websocket import broadcast_status_change
    await broadcast_status_change(session_id, "stopped")
    
    if success:
        return {"message": "Test session stopped gracefully."}
    return {"message": "Test session stopped (force database override)."}

@router.get("/api/sessions/{session_id}/logs")
async def get_session_logs(
    session_id: int,
    limit: Optional[int] = 200,
    search: Optional[str] = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    session = db.query(TestSession).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found!")
        
    session_dir = get_session_dir(session_id)
    log_path = os.path.join(session_dir, "report_log.jsonl")
    
    if not os.path.exists(log_path):
        return []
        
    logs = []
    search_query = search.lower()
    
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    evt = json.loads(line.strip())
                    if search_query and search_query not in line.lower():
                        continue
                    logs.append(evt)
                except Exception:
                    pass
    except Exception:
        pass
        
    return logs[-limit:]

@router.get("/api/sessions/{session_id}/metrics")
async def get_session_metrics(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    metrics = db.query(SessionMetric).filter(SessionMetric.session_id == session_id).order_by(
        SessionMetric.timestamp.asc()
    ).all()
    return [m.to_dict() for m in metrics]

# --- Top Level Control APIs (Direct Integrations) ---
@router.post("/start", status_code=201)
async def top_start(req: StartSessionRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Convenience top-level REST endpoint to start a session."""
    return await start_test(req, db, current_user)

@router.post("/stop")
async def top_stop(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Convenience top-level REST endpoint to stop the active session."""
    active = get_active_session(db)
    if not active:
        raise HTTPException(status_code=400, detail="No active running session found.")
    return await stop_test_run(active.id, db, current_user)

@router.post("/pause")
async def top_pause(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Convenience top-level REST endpoint to pause the active session."""
    active = get_active_session(db)
    if not active:
        raise HTTPException(status_code=400, detail="No active running session found.")
    return await pause_test(active.id, db, current_user)

@router.post("/resume")
async def top_resume(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Convenience top-level REST endpoint to resume the active session."""
    active = get_active_session(db)
    if not active:
        raise HTTPException(status_code=400, detail="No active running session found.")
    return await resume_test(active.id, db, current_user)

@router.get("/status")
async def top_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Convenience top-level REST endpoint to check session status."""
    active = get_active_session(db)
    if active:
        return {"status": active.status, "session_id": active.id, "name": active.name}
    
    # Return last run if no active one
    last = db.query(TestSession).order_by(TestSession.id.desc()).first()
    if last:
        return {"status": last.status, "session_id": last.id, "name": last.name}
    return {"status": "idle", "session_id": None, "name": None}

@router.get("/metrics")
async def top_metrics(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Convenience top-level REST endpoint to fetch latest metrics of active session."""
    active = get_active_session(db)
    if not active:
        raise HTTPException(status_code=400, detail="No active session currently running.")
        
    latest_metric = db.query(SessionMetric).filter(
        SessionMetric.session_id == active.id
    ).order_by(SessionMetric.timestamp.desc()).first()
    
    if latest_metric:
        return latest_metric.to_dict()
    return {"message": "Active session exists, but no metrics collected yet."}
