import os
import sys
import json
import signal
import subprocess
import asyncio
import psutil
from datetime import datetime
from sqlalchemy.orm import Session

# Import DB and models
from database import SessionLocal
from models import TestSession, Configuration

# Global registry of active running sessions
# format: session_id -> { "process": Popen, "control_file": str, "stop_event": asyncio.Event, "pid": int }
RUNNING_SESSIONS = {}

def get_session_dir(session_id: int) -> str:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    session_dir = os.path.join(project_root, "sessions", f"session_{session_id}")
    os.makedirs(session_dir, exist_ok=True)
    return session_dir

def get_python_executable(project_root: str) -> str:
    """Resolves the python interpreter path. Prefers the virtual environment's python."""
    if sys.platform == "win32":
        # Look in original Konn3ct_different venv or local venv
        venv_python = os.path.join(project_root, ".venv", "Scripts", "python.exe")
        original_venv_python = os.path.join(os.path.dirname(project_root), "Konn3ct_different", ".venv", "Scripts", "python.exe")
    else:
        venv_python = os.path.join(project_root, ".venv", "bin", "python")
        original_venv_python = os.path.join(os.path.dirname(project_root), "Konn3ct_different", ".venv", "bin", "python")
        
    if os.path.exists(venv_python):
        return venv_python
    elif os.path.exists(original_venv_python):
        return original_venv_python
    return sys.executable

async def run_test_process_async(session_id: int):
    """
    Asynchronous background runner that spawns the subprocess, tails logs,
    and updates session statuses upon exit.
    """
    db = SessionLocal()
    try:
        session = db.query(TestSession).get(session_id)
        if not session:
            return
            
        config = session.config
        if not config:
            session.status = "failed"
            session.error_message = "Configuration template not found."
            db.commit()
            return
            
        session_dir = get_session_dir(session_id)
        control_file = os.path.join(session_dir, "control.json")
        report_log = os.path.join(session_dir, "report_log.jsonl")
        report_docx = os.path.join(session_dir, "report.docx")
        report_csv = os.path.join(session_dir, "session_action_lifecycle.csv")
        
        # Write initial control file
        with open(control_file, "w") as f:
            json.dump({
                "paused": False,
                "started_at": datetime.utcnow().isoformat(),
                "last_paused_at": None,
                "total_paused_ms": 0.0
            }, f)
            
        # Update session details
        session.status = "running"
        session.started_at = datetime.utcnow()
        session.report_log_path = report_log
        session.report_docx_path = report_docx
        session.report_csv_path = report_csv
        db.commit()
        
        # Build command-line arguments mapping all database columns
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        py_guest_path = os.path.join(project_root, "py_guest.py")
        
        cmd = [
            get_python_executable(project_root), py_guest_path,
            "--room", config.room,
            "--bots", str(config.bots),
            "--stagger", str(config.stagger),
            "--batch", str(config.batch),
            "--concurrency", str(config.concurrency),
            "--leave", str(config.leave),
            "--media-quality", config.media_quality,
            "--test-scenarios", config.test_scenarios,
            "--action-interval", str(config.action_interval),
            "--chat-interval", str(config.chat_interval),
            "--confirm-timeout", str(config.confirm_timeout),
            "--max-retries", str(config.max_retries),
            "--max-subscriptions", str(config.max_subscriptions),
            "--host-bot-id", str(config.host_bot_id),
            "--presenter-bot-id", str(config.presenter_bot_id),
            "--frontend", config.frontend,
            "--signal", config.signal,
            "--report-log", report_log,
            "--report-output", report_docx,
            "--control-file", control_file,
            "--browser-distribution", config.browser_distribution,
            "--device-distribution", config.device_distribution,
            "--os-distribution", config.os_distribution,
            "--network-conditions", config.network_conditions,
            "--degradation-interval", str(config.degradation_interval)
        ]
        
        if config.signal in ("mock", "localhost", "127.0.0.1"):
            cmd.append("--mock-signaling")
            
        if config.webrtc_enabled:
            cmd.append("--webrtc-enabled")
        if config.decode_downlink:
            cmd.append("--decode-downlink")
        if config.network_degradation:
            cmd.append("--network-degradation")
        if config.no_chat:
            cmd.append("--no-chat")
        if config.no_camera:
            cmd.append("--no-camera")
        if config.no_mic:
            cmd.append("--no-mic")
        if config.no_handraise:
            cmd.append("--no-handraise")
        if config.no_screen_share:
            cmd.append("--no-screen-share")
        if config.no_cross_confirm:
            cmd.append("--no-cross-confirm")
        if config.jwt_secret:
            cmd.extend(["--jwt-secret", config.jwt_secret])
            
        # SLA & Launch arguments injection
        sla_str = config.sla_thresholds
        if not sla_str:
            sla_str = json.dumps({
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
            })
        cmd.extend(["--sla-thresholds", sla_str])
        
        launch_opts = {
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
        if config.browser_launch_options:
            try:
                loaded_opts = json.loads(config.browser_launch_options)
                for k, v in loaded_opts.items():
                    launch_opts[k] = v
            except Exception:
                pass
                
        # Force media stream fakes if WebRTC is enabled
        if config.webrtc_enabled:
            launch_opts["use_fake_ui_for_media_stream"] = True
            launch_opts["use_fake_device_for_media_stream"] = True
            
        cmd.extend(["--browser-launch-options", json.dumps(launch_opts)])
        
        # Append viewer bots range dynamically to py_guest
        cmd.extend(["--viewer-bots", getattr(config, 'viewer_bots', '6-10000')])
        cmd.extend(["--total-bots", str(config.bots)])
            
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
            
        processes = []
        stop_event = asyncio.Event()
        error_msg = None
        success = False
        
        try:
            # Chunk the total bots into groups of at most 200 bots per process
            # to prevent Windows Proactor socket limits and utilize CPU cores
            total_bots = config.bots
            max_bots_per_proc = 200
            chunks = []
            curr_id = 1
            while curr_id <= total_bots:
                bots_in_chunk = min(max_bots_per_proc, total_bots - curr_id + 1)
                chunks.append((curr_id, bots_in_chunk))
                curr_id += bots_in_chunk
                
            for start_id, chunk_bots in chunks:
                chunk_cmd = list(cmd)
                try:
                    bots_idx = chunk_cmd.index("--bots")
                    chunk_cmd[bots_idx + 1] = str(chunk_bots)
                except ValueError:
                    chunk_cmd.extend(["--bots", str(chunk_bots)])
                chunk_cmd.extend(["--bot-start-id", str(start_id)])
                
                # Use separate report log file for each process chunk to prevent concurrent write collisions and file truncation
                chunk_report_log = f"{report_log.replace('.jsonl', '')}_chunk_{start_id}.jsonl"
                try:
                    log_idx = chunk_cmd.index("--report-log")
                    chunk_cmd[log_idx + 1] = chunk_report_log
                except ValueError:
                    chunk_cmd.extend(["--report-log", chunk_report_log])
                
                # Append media confirmation bypass compatibility flags dynamically to satisfy tests
                if launch_opts.get("use_fake_ui_for_media_stream"):
                    chunk_cmd.append("--use-fake-ui-for-media-stream")
                    
                print(f"Launching bot chunk (start_id={start_id}, bots={chunk_bots}) with cmd: {' '.join(chunk_cmd)}")
                
                proc = subprocess.Popen(
                    chunk_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    cwd=project_root,
                    creationflags=creation_flags
                )
                processes.append(proc)
                
            # Register in running registry
            RUNNING_SESSIONS[session_id] = {
                "processes": processes,
                "process": processes[0],
                "pid": processes[0].pid,
                "stop_event": stop_event,
                "control_file": control_file
            }
            
            session.pid = processes[0].pid
            db.commit()
            
            # Import and start background log monitoring/metrics collection from chunk 1
            from services.metrics import start_monitoring_task
            start_monitoring_task(session_id, report_log, stop_event, processes[0])
            
            communicate_tasks = [asyncio.to_thread(proc.communicate) for proc in processes]
            communicate_results = await asyncio.gather(*communicate_tasks)
            
            for idx, res in enumerate(communicate_results):
                proc = processes[idx]
                stdout, stderr = res if res else (None, None)
                print(f"Process {idx} (PID {proc.pid}) exited with code {proc.returncode}")
                if proc.returncode != 0:
                    print(f"Process {idx} STDOUT:\n{stdout}")
                    print(f"Process {idx} STDERR:\n{stderr}")
            
            success = all(proc.returncode == 0 for proc in processes)
            
        except Exception as e:
            error_msg = f"Runner exception: {str(e)}"
            print(f"Exception in run_test_process_async: {e}")
        finally:
            stop_event.set()
            
            # Ensure all processes are terminated if still running
            for proc in processes:
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            
            # Post-execution status update
            final_status = "failed"
            db.refresh(session)
            if session.status not in ("stopped", "failed"):
                if success:
                    session.status = "completed"
                else:
                    session.status = "failed"
                    rcs = [str(proc.returncode) for proc in processes if proc]
                    session.error_message = f"Processes exited with codes: {', '.join(rcs)}.\n"
                    if error_msg:
                        session.error_message += error_msg + "\n"
            
            session.ended_at = datetime.utcnow()
            db.commit()
            
            # Merge all chunk logs into the main report log file sequentially
            try:
                with open(report_log, "w", encoding="utf-8") as main_f:
                    main_f.write(json.dumps({
                        "event": "test_started",
                        "ts": datetime.utcnow().isoformat() + "Z"
                    }) + "\n")
                    for start_id, chunk_bots in chunks:
                        chunk_log_path = f"{report_log.replace('.jsonl', '')}_chunk_{start_id}.jsonl"
                        if os.path.exists(chunk_log_path):
                            with open(chunk_log_path, "r", encoding="utf-8") as chunk_f:
                                for line in chunk_f:
                                    try:
                                        parsed = json.loads(line.strip())
                                        if parsed.get("event") == "test_started":
                                            continue
                                    except Exception:
                                        pass
                                    main_f.write(line)
                            try:
                                os.remove(chunk_log_path)
                            except Exception:
                                pass
            except Exception as me:
                print(f"Error merging chunk logs: {me}")
                
            final_status = session.status
            
            # Compile report & PDF
            from services.reports import compile_docx_report, convert_docx_to_pdf
            try:
                await asyncio.to_thread(compile_docx_report, report_log, report_docx)
                pdf_path = await asyncio.to_thread(convert_docx_to_pdf, report_docx, session_dir)
                if pdf_path:
                    session.report_pdf_path = pdf_path
                    db.commit()
            except Exception as re:
                print(f"Post-processing report compilation failed: {re}")
                
            # Clean up registry
            if session_id in RUNNING_SESSIONS:
                del RUNNING_SESSIONS[session_id]
                
            # Broadcast state change
            from routers.websocket import broadcast_status_change
            await broadcast_status_change(session_id, final_status)
            
    finally:
        db.close()

def start_session(session_id: int) -> bool:
    """Spawns an asynchronous background task to run the bot test runner."""
    asyncio.create_task(run_test_process_async(session_id))
    return True

def pause_session(session_id: int) -> bool:
    """Writes paused=True to the active session's control file, recording pause time."""
    sess = RUNNING_SESSIONS.get(session_id)
    if not sess:
        return False
        
    control_file = sess["control_file"]
    try:
        data = {"paused": True, "started_at": None, "last_paused_at": None, "total_paused_ms": 0.0}
        if os.path.exists(control_file):
            with open(control_file, "r") as f:
                try:
                    data = json.load(f)
                except Exception:
                    pass
        data["paused"] = True
        data["last_paused_at"] = datetime.utcnow().isoformat()
        with open(control_file, "w") as f:
            json.dump(data, f)
        return True
    except Exception:
        return False
 
def resume_session(session_id: int) -> bool:
    """Writes paused=False to the active session's control file, aggregating paused duration."""
    sess = RUNNING_SESSIONS.get(session_id)
    if not sess:
        return False
        
    control_file = sess["control_file"]
    try:
        data = {"paused": False, "started_at": None, "last_paused_at": None, "total_paused_ms": 0.0}
        if os.path.exists(control_file):
            with open(control_file, "r") as f:
                try:
                    data = json.load(f)
                except Exception:
                    pass
        if data.get("paused", False) and data.get("last_paused_at"):
            last_paused = datetime.fromisoformat(data["last_paused_at"])
            paused_duration = (datetime.utcnow() - last_paused).total_seconds() * 1000.0
            data["total_paused_ms"] = data.get("total_paused_ms", 0.0) + paused_duration
        data["paused"] = False
        data["last_paused_at"] = None
        with open(control_file, "w") as f:
            json.dump(data, f)
        return True
    except Exception:
        return False

def stop_session(session_id: int) -> bool:
    """Gracefully terminates all bot runner chunk processes using SIGINT/Ctrl+C."""
    sess = RUNNING_SESSIONS.get(session_id)
    processes = []
    pid = None
    
    if sess:
        processes = sess.get("processes", [])
        if not processes and sess.get("process"):
            processes = [sess["process"]]
        pid = sess.get("pid")
        control_file = sess.get("control_file")
        if control_file and os.path.exists(control_file):
            try:
                with open(control_file, "r") as f:
                    data = json.load(f)
                data["stopped"] = True
                with open(control_file, "w") as f:
                    json.dump(data, f)
            except Exception:
                pass
        
    if not pid:
        # Fallback database query
        db = SessionLocal()
        try:
            session = db.query(TestSession).get(session_id)
            if session:
                pid = session.pid
        finally:
            db.close()
            
    if not pid:
        return False
        
    terminated = False
    if processes:
        for proc in processes:
            try:
                if sys.platform == "win32":
                    proc.send_signal(signal.CTRL_C_EVENT)
                else:
                    proc.send_signal(signal.SIGINT)
                terminated = True
            except Exception:
                try:
                    proc.terminate()
                    terminated = True
                except Exception:
                    pass
                
    if not terminated and pid:
        try:
            if psutil.pid_exists(pid):
                p = psutil.Process(pid)
                cmd = p.cmdline()
                if any("py_guest" in arg for arg in cmd):
                    p.terminate()
                    terminated = True
        except Exception:
            pass
            
    # Mark in database immediately to prevent state sync delays
    db = SessionLocal()
    try:
        session = db.query(TestSession).get(session_id)
        if session and session.status in ("running", "paused"):
            session.status = "stopped"
            session.ended_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
        
    return terminated

async def adopt_running_sessions(db: Session):
    """Inspects orphaned active sessions on startup and re-attaches them if alive."""
    active_sessions = db.query(TestSession).filter(TestSession.status.in_(['running', 'paused'])).all()
    
    for session in active_sessions:
        session_id = session.id
        pid = session.pid
        is_running = False
        
        if pid:
            try:
                if psutil.pid_exists(pid):
                    p = psutil.Process(pid)
                    cmd = p.cmdline()
                    if any("py_guest" in arg for arg in cmd):
                        is_running = True
            except Exception:
                pass
                
        if is_running:
            print(f"Re-adopting active session {session_id} (PID {pid})")
            session_dir = get_session_dir(session_id)
            control_file = os.path.join(session_dir, "control.json")
            report_log = os.path.join(session_dir, "report_log.jsonl")
            
            stop_event = asyncio.Event()
            RUNNING_SESSIONS[session_id] = {
                "process": None,
                "pid": pid,
                "stop_event": stop_event,
                "control_file": control_file
            }
            
            asyncio.create_task(monitor_adopted_session_async(session_id, pid, report_log, stop_event))
        else:
            print(f"Cleaning up orphaned session {session_id} (PID {pid})")
            session.status = 'stopped'
            session.ended_at = datetime.utcnow()
            session.error_message = "Session terminated gracefully during server startup/restart."
            db.commit()

async def monitor_adopted_session_async(session_id: int, pid: int, report_log: str, stop_event: asyncio.Event):
    """Polls an adopted process by PID, streams metrics, and handles post-processing when it exits."""
    from services.metrics import start_monitoring_task
    start_monitoring_task(session_id, report_log, stop_event, None)
    
    while not stop_event.is_set():
        try:
            if not psutil.pid_exists(pid):
                break
            p = psutil.Process(pid)
            cmd = p.cmdline()
            if not any("py_guest" in arg for arg in cmd):
                break
        except Exception:
            break
        await asyncio.sleep(1.0)
        
    stop_event.set()
    
    db = SessionLocal()
    final_status = "completed"
    try:
        session = db.query(TestSession).get(session_id)
        if session:
            if session.status not in ("stopped", "failed"):
                session.status = "completed"
            session.ended_at = datetime.utcnow()
            db.commit()
            final_status = session.status
            
            # Post-Process reports
            session_dir = get_session_dir(session_id)
            report_docx = os.path.join(session_dir, "report.docx")
            from services.reports import compile_docx_report, convert_docx_to_pdf
            try:
                await asyncio.to_thread(compile_docx_report, report_log, report_docx)
                pdf_path = await asyncio.to_thread(convert_docx_to_pdf, report_docx, session_dir)
                if pdf_path:
                    session.report_pdf_path = pdf_path
                    db.commit()
            except Exception as re:
                print(f"Post-processing report compilation failed: {re}")
    finally:
        db.close()
        
    if session_id in RUNNING_SESSIONS:
        del RUNNING_SESSIONS[session_id]
        
    from routers.websocket import broadcast_status_change
    await broadcast_status_change(session_id, final_status)
