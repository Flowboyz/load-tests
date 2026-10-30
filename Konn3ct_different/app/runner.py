import os
import sys
import json
import time
import signal
import psutil
import subprocess
import threading
from datetime import datetime
from app.models import db, TestSession, SessionMetric, Configuration

# Global registry to hold active running sessions
# format: session_id -> { "process": Popen, "stop_event": ThreadEvent, "control_file": str }
RUNNING_SESSIONS = {}
RUNNING_SESSIONS_LOCK = threading.Lock()

def _normalize_project_root(project_root):
    if not project_root:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    norm = os.path.normpath(project_root)
    if os.path.basename(norm) == "app":
        return os.path.dirname(norm)
    return norm

def get_session_dir(session_id, *args):
    """
    Returns the session folder path. Supports:
      get_session_dir(session_id)
      get_session_dir(project_root, session_id)
    """
    if isinstance(session_id, str) and args:
        project_root = _normalize_project_root(session_id)
        actual_session_id = args[0]
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        actual_session_id = session_id
        
    session_dir = os.path.join(project_root, "sessions", f"session_{actual_session_id}")
    os.makedirs(session_dir, exist_ok=True)
    return session_dir

def get_python_executable(project_root):
    """
    Resolves the python interpreter path. Prefers the virtual environment's python
    to guarantee all dependencies (docx, aiortc, etc.) are available.
    """
    project_root = _normalize_project_root(project_root)
    if sys.platform == "win32":
        candidates = [
            os.path.join(project_root, ".venv", "Scripts", "python.exe"),
            os.path.join(project_root, "venv", "Scripts", "python.exe"),
        ]
    else:
        candidates = [
            os.path.join(project_root, ".venv", "bin", "python"),
            os.path.join(project_root, "venv", "bin", "python"),
        ]
        
    for c in candidates:
        if os.path.exists(c):
            return c
    return sys.executable

def run_test_process(app, socketio, session_id):
    """
    Background worker that runs the subprocess, tails logs, aggregates metrics, 
    and converts the final docx report to pdf.
    """
    import traceback
    
    # Initialize all block-scoped variables to prevent UnboundLocalError/NameError in finally block
    processes = []
    stop_event = threading.Event()
    error_msg = None
    success = False
    test_start_time = datetime.utcnow().isoformat() + "Z"
    report_log = None
    report_docx = None
    report_pdf = None
    report_csv = None
    session_dir = None
    project_root = None
    chunks = []
    
    try:
        with app.app_context():
            session = TestSession.query.get(session_id)
            if not session:
                return
                
            config = session.config
            if not config:
                session.status = "failed"
                session.error_message = "Configuration template not found."
                db.session.commit()
                return
                
            session_dir = get_session_dir(session_id)
            control_file = os.path.join(session_dir, "control.json")
            report_log = os.path.join(session_dir, "report_log.jsonl")
            report_docx = os.path.join(session_dir, "report.docx")
            report_pdf = os.path.join(session_dir, "report.pdf")
            report_csv = os.path.join(session_dir, "session_action_lifecycle.csv")
            
            # Write initial control file
            with open(control_file, "w") as f:
                json.dump({"paused": False}, f)
                
            # Record actual UTC test start time
            test_start_time = datetime.utcnow().isoformat() + "Z"
            
            # Update session details
            session.status = "running"
            session.started_at = datetime.utcnow()
            session.last_resume_time = datetime.utcnow()
            session.accumulated_duration = 0
            session.report_log_path = report_log
            session.report_docx_path = report_docx
            session.report_csv_path = report_csv
            db.session.commit()
            
            # Build command-line arguments mapping all database columns
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            py_guest_path = os.path.join(project_root, "py_guest.py")
            
            is_large_scale = (config.bots > 50) or getattr(config, 'large_room_mode', False) or ("large_room" in (config.test_scenarios or "").lower())
            force_all_publishers = getattr(config, 'disable_ram_scenario_opt', False) or getattr(config, 'auto_camera', False)

            if force_all_publishers or (not is_large_scale and getattr(config, 'camera_publishers', '') in ('1,2,3,4,5', 'all', '1-10000', '')):
                cam_pub_arg = "1-10000"
            else:
                cam_pub_arg = str(getattr(config, 'camera_publishers', '') or "1,2,3,4,5")

            if force_all_publishers or getattr(config, 'auto_mic', False) or (not is_large_scale and getattr(config, 'mic_publishers', '') in ('1,2,3,4,5', 'all', '1-10000', '')):
                mic_pub_arg = "1-10000"
            else:
                mic_pub_arg = str(getattr(config, 'mic_publishers', '') or "1,2,3,4,5")

            if force_all_publishers or (not is_large_scale and getattr(config, 'viewer_bots', '') in ('6-10000', '6-1000', '')):
                viewer_bots_arg = ""
                viewer_mode_arg = "normal_participant"
            else:
                raw_viewers = str(getattr(config, 'viewer_bots', '') or "6-10000")
                if raw_viewers in ("6-1000", "6-10000", ""):
                    raw_viewers = f"6-{max(10000, config.bots + 1000)}"
                viewer_bots_arg = raw_viewers
                viewer_mode_arg = getattr(config, 'viewer_mode', "receive_only") or "receive_only"

            cmd = [
                get_python_executable(project_root), py_guest_path,
                "--room", config.room,
                "--bots", str(config.bots),
                "--start-id", str(getattr(config, 'start_id', 1)),
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
                "--degradation-interval", str(config.degradation_interval),
                "--sla-success-rate", str(getattr(config, 'sla_success_rate', 95.0)),
                "--sla-latency", str(getattr(config, 'sla_latency', 500.0)),
                "--sla-packet-loss", str(getattr(config, 'sla_packet_loss', 2.0)),
                "--sla-jitter", str(getattr(config, 'sla_jitter', 30.0)),
                "--cross-confirm-limit", str(999999 if getattr(config, 'disable_ram_scenario_opt', False) else getattr(config, 'cross_confirm_limit', 10)),
                "--camera-publishers", cam_pub_arg,
                "--screen-share-publishers", "1-10000" if getattr(config, 'disable_ram_scenario_opt', False) else getattr(config, 'screen_share_publishers', "2"),
                "--mic-publishers", mic_pub_arg,
                "--viewer-bots", viewer_bots_arg,
                "--viewer-mode", viewer_mode_arg,
                "--refresh-bots", str(getattr(config, 'refresh_bots', 0) or 0)
            ]
            
            # Add flags
            if getattr(config, 'disable_abnormal_behavior', False):
                cmd.append("--disable-abnormal-behavior")
            if "chaos" in (config.test_scenarios or "").lower() or getattr(config, 'enable_chaos', False):
                cmd.append("--enable-chaos")
            if config.webrtc_enabled:
                cmd.append("--webrtc-enabled")
            if config.decode_downlink:
                cmd.append("--decode-downlink")
            if config.network_degradation:
                cmd.append("--network-degradation")
            if getattr(config, 'auto_camera', False):
                cmd.append("--auto-camera")
            if getattr(config, 'auto_mic', False):
                cmd.append("--auto-mic")
            if getattr(config, 'auto_screen_share', False):
                cmd.append("--auto-screen-share")
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
            jwt_secret_val = config.jwt_secret or os.environ.get("JWT_SECRET")
            if jwt_secret_val:
                cmd.extend(["--jwt-secret", jwt_secret_val])
            if getattr(config, 'large_room_mode', False) or "large_room" in (config.test_scenarios or "").lower():
                cmd.append("--large-room-mode")
            if getattr(config, 'conversational_audio', True):
                cmd.append("--conversational-audio")
            if getattr(config, 'speaker_promotion_storm', False) or "speaker_promotion" in (config.test_scenarios or "").lower():
                cmd.append("--speaker-promotion-storm")
            
            # Auto-scale configurations when spawned from dashboard
            if config.bots >= 2000:
                if "--lightweight" not in cmd:
                    cmd.append("--lightweight")
                if "--no-cross-confirm" not in cmd:
                    cmd.append("--no-cross-confirm")
                # Override cross-confirm-limit to 3 if present in args
                try:
                    idx = cmd.index("--cross-confirm-limit")
                    cmd[idx + 1] = "3"
                except ValueError:
                    cmd.extend(["--cross-confirm-limit", "3"])

            # Always append chromium launch bypass flag compatibility argument
            cmd.append("--use-fake-ui-for-media-stream")
                 
            print(f"Launching bot session {session_id} with cmd: {' '.join(cmd)}")
            
            # Spawn the process in a new process group to allow clean signalling
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
                
            processes = []
            stop_event = threading.Event()
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
                    
                stagger_val = config.stagger if hasattr(config, 'stagger') else 1.0
                batch_val = config.batch if hasattr(config, 'batch') else 3

                for idx, (start_id, chunk_bots) in enumerate(chunks):
                    chunk_cmd = list(cmd)
                    try:
                        bots_idx = chunk_cmd.index("--bots")
                        chunk_cmd[bots_idx + 1] = str(chunk_bots)
                    except ValueError:
                        chunk_cmd.extend(["--bots", str(chunk_bots)])
                    try:
                        start_idx = chunk_cmd.index("--start-id")
                        chunk_cmd[start_idx + 1] = str(start_id)
                    except ValueError:
                        chunk_cmd.extend(["--start-id", str(start_id)])
                    
                    # Calculate startup delay to stagger process chunks sequentially
                    startup_delay = idx * (max_bots_per_proc / batch_val) * stagger_val
                    chunk_cmd.extend(["--startup-delay", f"{startup_delay:.2f}"])
                    
                    # Use separate report log file for each process chunk to prevent concurrent write collisions and file truncation
                    chunk_report_log = f"{report_log.replace('.jsonl', '')}_chunk_{start_id}.jsonl"
                    try:
                        log_idx = chunk_cmd.index("--report-log")
                        chunk_cmd[log_idx + 1] = chunk_report_log
                    except ValueError:
                        chunk_cmd.extend(["--report-log", chunk_report_log])
                    
                    print(f"Launching bot chunk (start_id={start_id}, bots={chunk_bots}) with delay={startup_delay:.2f}s, cmd: {' '.join(chunk_cmd)}")
                    
                    proc = subprocess.Popen(
                        chunk_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        cwd=project_root,
                        creationflags=creation_flags
                    )
                    processes.append(proc)
                    
                with RUNNING_SESSIONS_LOCK:
                    RUNNING_SESSIONS[session_id] = {
                        "processes": processes,
                        "process": processes[0],
                        "stop_event": stop_event,
                        "control_file": control_file
                    }
                    
                session.pid = processes[0].pid
                db.session.commit()
                
                # Start log parsing and metric streaming thread
                metrics_thread = socketio.start_background_task(
                    stream_metrics_and_logs, app, socketio, session_id, report_log, stop_event, processes[0]
                )
                
                # Emit status change to running
                if socketio:
                    socketio.emit('session_status_changed', {
                        'session_id': session_id,
                        'status': 'running',
                        'elapsed_seconds': 0
                    }, room=f"session_{session_id}")
                
                # Wait for all processes to complete using non-blocking greenlet polling
                while any(proc.poll() is None for proc in processes) and not stop_event.is_set():
                    socketio.sleep(0.5)
                    
                if stop_event.is_set():
                    for proc in processes:
                        if proc and proc.poll() is None:
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                                
                success = all(proc.returncode == 0 for proc in processes if proc.poll() is not None)
                
            except Exception as e:
                error_msg = f"Runner exception: {str(e)}"
                print(f"Exception in run_test_process: {e}")
            finally:
                # Set stop event to terminate log readers
                stop_event.set()
                
                # Ensure all processes are terminated if still running
                for proc in processes:
                    if proc and proc.poll() is None:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                
                # Update database with completion status
                final_status = "failed"
                accumulated_secs = 0
                with app.app_context():
                    session = TestSession.query.get(session_id)
                    if session:
                        if session.status not in ("stopped", "failed"):
                            if success:
                                session.status = "completed"
                            else:
                                session.status = "failed"
                                rcs = [str(proc.returncode) for proc in processes if proc]
                                session.error_message = f"Processes exited with codes: {', '.join(rcs)}.\n"
                                if error_msg:
                                    session.error_message += error_msg + "\n"
                        
                        if session.last_resume_time:
                            elapsed = (datetime.utcnow() - session.last_resume_time).total_seconds()
                            session.accumulated_duration += int(elapsed)
                        session.last_resume_time = None
                        session.ended_at = datetime.utcnow()
                        accumulated_secs = session.accumulated_duration
                        
                        # Merge all chunk logs into the main report log file
                        if report_log and test_start_time:
                            try:
                                with open(report_log, "w", encoding="utf-8") as main_f:
                                    main_f.write(json.dumps({
                                        "event": "test_started",
                                        "ts": test_start_time
                                    }) + "\n")
                                    if chunks:
                                        for start_id, chunk_bots in chunks:
                                            chunk_log_path = f"{report_log.replace('.jsonl', '')}_chunk_{start_id}.jsonl"
                                            if os.path.exists(chunk_log_path):
                                                with open(chunk_log_path, "r", encoding="utf-8") as chunk_f:
                                                    for idx, line in enumerate(chunk_f):
                                                        if idx == 0 and "test_started" in line:
                                                            continue
                                                        main_f.write(line)
                                                try:
                                                    os.remove(chunk_log_path)
                                                except Exception:
                                                    pass
                            except Exception as me:
                                print(f"Error merging chunk logs: {me}")
                                
                        # Post-Process: Compile report if log file or chunk files exist
                        has_log_or_chunks = os.path.exists(report_log)
                        if not has_log_or_chunks:
                            import glob
                            base_dir = os.path.dirname(report_log) or "."
                            base_name = os.path.basename(report_log).replace(".jsonl", "")
                            pattern = os.path.join(base_dir, f"{base_name}_chunk_*.jsonl")
                            has_log_or_chunks = bool(glob.glob(pattern))

                        if project_root and report_log and report_docx and has_log_or_chunks:
                            try:
                                sla_overrides = {}
                                if session.config:
                                    sla_overrides['sla_success_rate'] = getattr(session.config, 'sla_success_rate', None)
                                    sla_overrides['sla_latency'] = getattr(session.config, 'sla_latency', None)
                                    sla_overrides['sla_packet_loss'] = getattr(session.config, 'sla_packet_loss', None)
                                    sla_overrides['sla_jitter'] = getattr(session.config, 'sla_jitter', None)
                                    sla_overrides['sla_join_latency'] = getattr(session.config, 'sla_join_latency', None)
                                    sla_overrides['sla_min_fps'] = getattr(session.config, 'sla_min_fps', None)
                                    sla_overrides['sla_max_disconnects'] = getattr(session.config, 'sla_max_disconnects', None)
                                    sla_overrides['sla_min_bitrate'] = getattr(session.config, 'sla_min_bitrate', None)
                                compile_report_log(project_root, report_log, report_docx, **sla_overrides)
                                
                                # Cache AI verdict and recommendations in DB
                                session_json_path = os.path.join(session_dir, "session_report_data.json") if session_dir else ""
                                temp_json_path = session_json_path if (session_json_path and os.path.exists(session_json_path)) else os.path.join(project_root, "_report_data.json")
                                if os.path.exists(temp_json_path):
                                    try:
                                        with open(temp_json_path, "r", encoding="utf-8") as tjf:
                                            tdata = json.load(tjf)
                                            session.ai_verdict = tdata.get("qa_verdict")
                                            session.ai_engine_used = tdata.get("engine_attribution", {}).get("engine_name")
                                            if tdata.get("ai_advisory"):
                                                session.ai_recommendations_json = json.dumps(tdata["ai_advisory"])
                                    except Exception as db_e:
                                        print(f"Note: Could not parse AI report data for DB caching: {db_e}")
                                if session_dir:
                                    csv_candidate = os.path.join(session_dir, "session_action_lifecycle.csv")
                                    if os.path.exists(csv_candidate):
                                        session.report_csv_path = csv_candidate
                            except Exception as cre:
                                print(f"Error compiling report log: {cre}")
                                
                        # Convert DOCX to PDF using LibreOffice / Playwright / Pure-Python fallback
                        if report_docx and session_dir and os.path.exists(report_docx):
                            try:
                                pdf_path = convert_docx_to_pdf(report_docx, session_dir)
                                if pdf_path:
                                    session.report_pdf_path = pdf_path
                            except Exception as cpe:
                                print(f"Error converting docx to pdf: {cpe}")
                            
                        db.session.commit()
                        final_status = session.status

                    
                with RUNNING_SESSIONS_LOCK:
                    if session_id in RUNNING_SESSIONS:
                        del RUNNING_SESSIONS[session_id]
                        
                # Emit complete event
                socketio.emit('session_status_changed', {
                    'session_id': session_id,
                    'status': final_status,
                    'elapsed_seconds': accumulated_secs
                }, room=f"session_{session_id}")
    except Exception as e:
        traceback.print_exc()
        try:
            with app.app_context():
                session = TestSession.query.get(session_id)
                if session:
                    session.status = "failed"
                    session.error_message = f"Startup failed: {str(e)}\n{traceback.format_exc()}"
                    db.session.commit()
        except Exception as db_ex:
            print(f"Failed to record startup crash in DB: {db_ex}")
            
        with RUNNING_SESSIONS_LOCK:
            if session_id in RUNNING_SESSIONS:
                del RUNNING_SESSIONS[session_id]
                
        socketio.emit('session_status_changed', {
            'session_id': session_id,
            'status': 'failed',
            'elapsed_seconds': 0
        }, room=f"session_{session_id}")

def stream_metrics_and_logs(app, socketio, session_id, log_path, stop_event, process):
    """
    Reads the JSONL log file as it grows, parses the metrics, collects CPU/RAM,
    and broadcasts updates to socket.io.
    Supports tailing multiple parallel chunk logs.
    """
    import glob
    session_dir = os.path.dirname(log_path)
    base_name = os.path.basename(log_path)
    base_prefix = base_name.replace(".jsonl", "")
    
    # Wait for any log file to be created (chunk or single log, up to 15 seconds)
    start_wait = time.time()
    found_log = False
    while time.time() - start_wait < 15.0 and not stop_event.is_set():
        chunk_pattern = os.path.join(session_dir, f"{base_prefix}_chunk_*.jsonl")
        single_log = os.path.join(session_dir, f"{base_prefix}.jsonl")
        if glob.glob(chunk_pattern) or os.path.exists(single_log):
            found_log = True
            break
        if process and process.poll() is not None:
            break
        socketio.sleep(0.2)
        
    if not found_log:
        return

    # Running aggregation state
    metrics_state = {
        "connected_bots": 0,
        "connecting_bots": 0,
        "failed_bots": 0,
        "reconnecting_bots": 0,
        "left_bots": 0,
        "latencies": [],
        "packet_losses": [],
        "jitters": [],
        "bitrates": [],
        "status_counts": {"sent": 0, "acknowledged": 0, "broadcasted": 0, "observed": 0, "rendered": 0, "timed-out": 0, "failed": 0, "unsupported": 0},
        "timeout_stages": {"ack-timeout": 0, "broadcast-timeout": 0, "observer-timeout": 0, "ui-render-timeout": 0, "id-correlation-mismatch": 0},
        "unsupported_reasons": {},
        "turn_count": 0,
        "relay_count": 0,
        "global_peak_latency": 0.0
    }
    
    connecting_ids = set()
    reconnecting_ids = set()
    joined_ids = set()
    failed_ids = set()
    left_ids = set()

    def sync_bot_counts():
        metrics_state["connected_bots"] = len(joined_ids)
        metrics_state["connecting_bots"] = len(connecting_ids)
        metrics_state["reconnecting_bots"] = len(reconnecting_ids)
        metrics_state["failed_bots"] = len(failed_ids)
        metrics_state["left_bots"] = len(left_ids)

    # Load session configuration details for batch tracking
    start_id = 1
    total_bots = 50
    batch_size = 500
    expected_workers = 1
    with app.app_context():
        from app.models import TestSession
        session = TestSession.query.get(session_id)
        if session and session.config:
            start_id = getattr(session.config, 'start_id', 1)
            total_bots = session.config.bots
            expected_workers = session.total_expected_workers
            if expected_workers <= 1:
                expected_workers = max(1, (total_bots + batch_size - 1) // batch_size)

    joined_by_batch = [set() for _ in range(expected_workers)]
    failed_by_batch = [set() for _ in range(expected_workers)]

    # Batching variables for raw events
    buffered_raw_events = []
    last_raw_emit_time = time.time()
    last_metrics_emit_time = time.time()
    
    open_files = {} # chunk_id -> file_object
    line_buffers = {} # chunk_id -> string
    
    try:
        while not stop_event.is_set():
            # 1. Discover all active chunk files or single report_log
            pattern = os.path.join(session_dir, f"{base_prefix}_chunk_*.jsonl")
            chunk_files = glob.glob(pattern)
            if not chunk_files:
                single_log = os.path.join(session_dir, f"{base_prefix}.jsonl")
                if os.path.exists(single_log):
                    chunk_files = [single_log]
            
            any_new_lines = False
            
            for file_path in chunk_files:
                filename = os.path.basename(file_path)
                try:
                    chunk_id = int(filename.split("_chunk_")[-1].replace(".jsonl", ""))
                except Exception:
                    chunk_id = filename
                    
                if chunk_id not in open_files:
                    try:
                        f = open(file_path, "r", encoding="utf-8")
                        open_files[chunk_id] = f
                    except Exception:
                        continue
                        
                if chunk_id not in line_buffers:
                    line_buffers[chunk_id] = ""
                    
                f = open_files[chunk_id]
                while True:
                    where = f.tell()
                    line = f.readline()
                    if not line:
                        f.seek(where)
                        break
                    if not line.endswith("\n"):
                        f.seek(where)
                        break
                        
                    any_new_lines = True
                    complete_line = line.strip()
                    if not complete_line:
                        continue
                    
                    try:
                        event = json.loads(complete_line)
                        etype = event.get("event")
                        
                        # Buffer raw event for console log viewer
                        buffered_raw_events.append(event)
                        if len(buffered_raw_events) >= 50 or (time.time() - last_raw_emit_time > 0.2):
                            socketio.emit('session_raw_events_batch', {
                                'session_id': session_id,
                                'events': buffered_raw_events
                            }, room=f"session_{session_id}")
                            buffered_raw_events = []
                            last_raw_emit_time = time.time()
                            
                        # Process metrics
                        bot_id = event.get("bot_id")
                        
                        if etype == "bot_connecting" and bot_id:
                            connecting_ids.add(bot_id)
                            reconnecting_ids.discard(bot_id)
                            joined_ids.discard(bot_id)
                            failed_ids.discard(bot_id)
                            left_ids.discard(bot_id)
                            sync_bot_counts()
                        elif etype == "bot_reconnecting" and bot_id:
                            reconnecting_ids.add(bot_id)
                            connecting_ids.discard(bot_id)
                            joined_ids.discard(bot_id)
                            failed_ids.discard(bot_id)
                            sync_bot_counts()
                            # Update batch tracking
                            batch_idx = (bot_id - start_id) // batch_size
                            if 0 <= batch_idx < expected_workers:
                                joined_by_batch[batch_idx].discard(bot_id)
                        elif etype in ("bot_joined", "bot_waiting") and bot_id:
                            joined_ids.add(bot_id)
                            connecting_ids.discard(bot_id)
                            reconnecting_ids.discard(bot_id)
                            failed_ids.discard(bot_id)
                            left_ids.discard(bot_id)
                            sync_bot_counts()
                            # Update batch tracking
                            batch_idx = (bot_id - start_id) // batch_size
                            if 0 <= batch_idx < expected_workers:
                                joined_by_batch[batch_idx].add(bot_id)
                                failed_by_batch[batch_idx].discard(bot_id)
                        elif etype == "bot_failed" and bot_id:
                            failed_ids.add(bot_id)
                            connecting_ids.discard(bot_id)
                            reconnecting_ids.discard(bot_id)
                            joined_ids.discard(bot_id)
                            sync_bot_counts()
                            # Update batch tracking
                            batch_idx = (bot_id - start_id) // batch_size
                            if 0 <= batch_idx < expected_workers:
                                failed_by_batch[batch_idx].add(bot_id)
                                joined_by_batch[batch_idx].discard(bot_id)
                        elif etype == "bot_left" and bot_id:
                            left_ids.add(bot_id)
                            connecting_ids.discard(bot_id)
                            reconnecting_ids.discard(bot_id)
                            joined_ids.discard(bot_id)
                            sync_bot_counts()
                            # Update batch tracking
                            batch_idx = (bot_id - start_id) // batch_size
                            if 0 <= batch_idx < expected_workers:
                                joined_by_batch[batch_idx].discard(bot_id)
                        elif etype == "action_logged":
                            act_type = event.get("action_type")
                            status = event.get("status")
                            final_status = event.get("final_status")
                            lat = event.get("latency_ms")
                            
                            if act_type == "webrtc_connection" and bot_id:
                                if status == "confirmed":
                                    reconnecting_ids.discard(bot_id)
                                    connecting_ids.discard(bot_id)
                                    sync_bot_counts()
                            
                            if lat is not None:
                                metrics_state["latencies"].append(lat)
                                if lat > metrics_state["global_peak_latency"]:
                                    metrics_state["global_peak_latency"] = lat
                                
                            # Update propagation lifecycle counts
                            resolved_status = final_status or status
                            if resolved_status == "confirmed":
                                resolved_status = "acknowledged"
                            elif resolved_status in ("timeout", "timed_out"):
                                resolved_status = "timed-out"
                            elif resolved_status and resolved_status.startswith("observed"):
                                resolved_status = "observed"
                                
                            if resolved_status in metrics_state["status_counts"]:
                                metrics_state["status_counts"][resolved_status] += 1
                                
                            if resolved_status == "timed-out":
                                t_stage = event.get("timeout_stage")
                                if t_stage in metrics_state["timeout_stages"]:
                                    metrics_state["timeout_stages"][t_stage] += 1
                                    
                            if resolved_status == "unsupported":
                                reason = event.get("unsupported_reason", "unknown")
                                metrics_state["unsupported_reasons"][reason] = metrics_state["unsupported_reasons"].get(reason, 0) + 1
                                
                        elif etype == "webrtc_stats_logged":
                            rtt = event.get("rtt")
                            loss = event.get("packet_loss")
                            jitter = event.get("jitter")
                            bitrate = event.get("bitrate")
                            turn_usage = event.get("turn_usage")
                            cand_type = event.get("candidate_pair_type")
                            
                            if rtt is not None:
                                metrics_state["latencies"].append(rtt)
                                if rtt > metrics_state["global_peak_latency"]:
                                    metrics_state["global_peak_latency"] = rtt
                            if loss is not None: metrics_state["packet_losses"].append(loss)
                            if jitter is not None: metrics_state["jitters"].append(jitter)
                            if bitrate is not None: metrics_state["bitrates"].append(bitrate)
                            
                            if turn_usage is True or str(turn_usage).lower() == 'true':
                                metrics_state["turn_count"] += 1
                            if cand_type == 'relay':
                                metrics_state["relay_count"] += 1
                            
                        elif etype == "error_logged":
                            # Transient socket/action errors are logged for console visibility;
                            # terminal bot failures are tracked via bot_failed events.
                            pass
                            
                        # Extract WebRTC parameters if logged
                        webrtc_data = event.get("summary", {}).get("webrtc_performance", {})
                        if webrtc_data:
                            for b_type, b_stats in webrtc_data.items():
                                if "avg_packet_loss" in b_stats:
                                    metrics_state["packet_losses"].append(b_stats["avg_packet_loss"])
                                if "avg_jitter" in b_stats:
                                    metrics_state["jitters"].append(b_stats["avg_jitter"])
                                if "avg_bitrate" in b_stats:
                                    metrics_state["bitrates"].append(b_stats["avg_bitrate"])
                                    
                    except Exception as e:
                        print(f"Error parsing log line: {e}")
                        
            # Always emit raw events batch if it has accumulated or if it's been more than 0.2s since last emit
            if buffered_raw_events and (len(buffered_raw_events) >= 50 or (time.time() - last_raw_emit_time > 0.2)):
                raw_payload = {
                    'session_id': session_id,
                    'events': buffered_raw_events
                }
                socketio.emit('session_raw_events_batch', raw_payload, room=f"session_{session_id}")
                socketio.emit('session_raw_events_batch', raw_payload)
                buffered_raw_events = []
                last_raw_emit_time = time.time()

            # Emit metrics periodically (every 1.0 second) to update UI live counters
            now = time.time()
            if now - last_metrics_emit_time >= 1.0:
                # Fetch host resource metrics
                try:
                    cpu = psutil.cpu_percent()
                    ram = psutil.virtual_memory().percent
                except Exception:
                    cpu, ram = 0.0, 0.0
                    
                # Calculate metric averages
                avg_lat = sum(metrics_state["latencies"]) / len(metrics_state["latencies"]) if metrics_state["latencies"] else 0.0
                avg_loss = sum(metrics_state["packet_losses"]) / len(metrics_state["packet_losses"]) if metrics_state["packet_losses"] else 0.0
                avg_jitter = sum(metrics_state["jitters"]) / len(metrics_state["jitters"]) if metrics_state["jitters"] else 0.0
                avg_bitrate = sum(metrics_state["bitrates"]) / len(metrics_state["bitrates"]) if metrics_state["bitrates"] else 0
                avg_rtt = avg_lat
                
                # Write to database (SessionMetric) and fetch current elapsed time
                elapsed_secs = 0
                with app.app_context():
                    session = TestSession.query.get(session_id)
                    if session and session.status == "running":
                        elapsed_secs = session.accumulated_duration
                        if session.last_resume_time:
                            elapsed_secs += int((datetime.utcnow() - session.last_resume_time).total_seconds())

                        metric_entry = SessionMetric(
                            session_id=session_id,
                            connected_bots=metrics_state["connected_bots"],
                            connecting_bots=metrics_state["connecting_bots"],
                            failed_bots=metrics_state["failed_bots"],
                            reconnecting_bots=metrics_state["reconnecting_bots"],
                            cpu_usage=cpu,
                            ram_usage=ram,
                            avg_latency=avg_lat,
                            packet_loss=avg_loss,
                            jitter=avg_jitter,
                            bitrate=int(avg_bitrate)
                        )
                        db.session.add(metric_entry)
                        db.session.commit()
                        
                        metrics_payload = metric_entry.to_dict()
                        metrics_payload["left_bots"] = metrics_state["left_bots"]
                        
                        # Emit metrics via Socket.IO
                        live_metrics_data = {
                            'session_id': session_id,
                            'metrics': metrics_payload,
                            'elapsed_seconds': elapsed_secs,
                            'lifecycle_summary': {
                                'status_counts': metrics_state["status_counts"],
                                'timeout_stages': metrics_state["timeout_stages"],
                                'unsupported_reasons': metrics_state["unsupported_reasons"],
                                'webrtc_advanced': {
                                    'rtt': avg_rtt,
                                    'loss': avg_loss,
                                    'jitter': avg_jitter,
                                    'bitrate': avg_bitrate,
                                    'turn_count': metrics_state["turn_count"],
                                    'relay_count': metrics_state["relay_count"],
                                    'peak_latency': metrics_state["global_peak_latency"]
                                }
                            }
                        }
                        socketio.emit('session_metrics', live_metrics_data, room=f"session_{session_id}")
                        socketio.emit('session_metrics', live_metrics_data)
                        
                        # Update RUNNING_SESSIONS with live batch metrics
                        with RUNNING_SESSIONS_LOCK:
                            sess = RUNNING_SESSIONS.get(session_id)
                            if sess:
                                sess["live_batches"] = {
                                    i: {
                                        "joined": len(joined_by_batch[i]),
                                        "failed": len(failed_by_batch[i])
                                    }
                                    for i in range(expected_workers)
                                }
                        
                # Clear moving averages to only calculate recent windows
                metrics_state["latencies"] = metrics_state["latencies"][-50:]
                metrics_state["packet_losses"] = metrics_state["packet_losses"][-50:]
                metrics_state["jitters"] = metrics_state["jitters"][-50:]
                metrics_state["bitrates"] = metrics_state["bitrates"][-50:]
                
                last_metrics_emit_time = now

            # Yield execution to yield CPU control back to greenlet/eventlet hub
            if any_new_lines:
                socketio.sleep(0.02)
            else:
                socketio.sleep(0.4)

        # ── Final Flush of Remaining Log Lines ──────────────────────────────────
        # Process any final lines written by the bots (like bot exits) right before the process exited.
        for chunk_id, f in open_files.items():
            try:
                while True:
                    line = f.readline()
                    if not line:
                        break
                    line_buffers[chunk_id] += line
                    if not line_buffers[chunk_id].endswith("\n"):
                        break
                    complete_line = line_buffers[chunk_id]
                    line_buffers[chunk_id] = ""
                    try:
                        event = json.loads(complete_line.strip())
                        etype = event.get("event")
                        buffered_raw_events.append(event)
                        bot_id = event.get("bot_id")
                        if etype == "bot_left" and bot_id:
                            left_ids.add(bot_id)
                            connecting_ids.discard(bot_id)
                            reconnecting_ids.discard(bot_id)
                            joined_ids.discard(bot_id)
                            sync_bot_counts()
                    except Exception:
                        pass
            except Exception:
                pass

        if buffered_raw_events:
            socketio.emit('session_raw_events_batch', {
                'session_id': session_id,
                'events': buffered_raw_events
            }, room=f"session_{session_id}")
            buffered_raw_events = []
    finally:
        for f in open_files.values():
            try:
                f.close()
            except Exception:
                pass

def compile_report_log(project_root, log_path, docx_path,
                       sla_success_rate=None, sla_latency=None,
                       sla_packet_loss=None, sla_jitter=None,
                       sla_join_latency=None, sla_min_fps=None,
                       sla_max_disconnects=None, sla_min_bitrate=None):
    """
    Force executes generate_report.py to compile report.
    """
    project_root = _normalize_project_root(project_root)
    generate_report_script = os.path.join(project_root, "generate_report.py")
    cmd = [get_python_executable(project_root), generate_report_script, log_path, "--output", docx_path]
    if sla_success_rate is not None:
        cmd.extend(["--sla-success-rate", str(sla_success_rate)])
    if sla_latency is not None:
        cmd.extend(["--sla-latency", str(sla_latency)])
    if sla_packet_loss is not None:
        cmd.extend(["--sla-packet-loss", str(sla_packet_loss)])
    if sla_jitter is not None:
        cmd.extend(["--sla-jitter", str(sla_jitter)])
    if sla_join_latency is not None:
        cmd.extend(["--sla-join-latency", str(sla_join_latency)])
    if sla_min_fps is not None:
        cmd.extend(["--sla-min-fps", str(sla_min_fps)])
    if sla_max_disconnects is not None:
        cmd.extend(["--sla-max-disconnects", str(sla_max_disconnects)])
    if sla_min_bitrate is not None:
        cmd.extend(["--sla-min-bitrate", str(sla_min_bitrate)])
    try:
        res = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            encoding="utf-8"
        )
        print(f"Successfully auto-compiled docx report: {docx_path}")
        print(f"Subprocess stdout: {res.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to auto-compile docx report: {e}")
        print(f"Subprocess stdout: {e.stdout}")
        print(f"Subprocess stderr: {e.stderr}")
    except Exception as e:
        print(f"Failed to auto-compile docx report: {e}")

def compile_report_log_async(project_root, session_id, socketio):
    """
    Spawns a background thread to compile the report asynchronously and stream
    status updates.
    """
    import glob
    import threading
    from app.models import TestSession, db
    
    project_root = _normalize_project_root(project_root)

    def worker():
        # Retrieve session from app context
        from app import create_app
        app = create_app()
        with app.app_context():
            session = TestSession.query.get(session_id)
            if not session:
                return
                
            try:
                socketio.emit('report_compile_status', {'session_id': session_id, 'status': 'merging', 'message': 'Merging worker chunks...'})
                
                # 1. Non-destructive self-healing merger: Combine any uploaded chunk files
                session_dir = get_session_dir(project_root, session_id)
                merged_log_path = os.path.join(session_dir, "report_log.jsonl")
                
                # Scan all chunks using glob (handles both worker_id 1..N and multi-process start_id 1, 201, 401...)
                def _chunk_sort_key(p):
                    base = os.path.basename(p).replace(".jsonl", "")
                    parts = base.split("_")
                    try:
                        return int(parts[-1])
                    except Exception:
                        return 0

                chunks = sorted(glob.glob(os.path.join(session_dir, "report_log_chunk_*.jsonl")), key=_chunk_sort_key)
                
                # IMPORTANT: Only write/append when chunk files actually exist; NEVER overwrite an existing report_log.jsonl with an empty list!
                if chunks:
                    has_existing_main = os.path.exists(merged_log_path) and os.path.getsize(merged_log_path) > 0
                    mode = 'a' if has_existing_main else 'w'
                    with open(merged_log_path, mode, encoding='utf-8') as outfile:
                        for c_idx, chunk_file in enumerate(chunks):
                            try:
                                if os.path.getsize(chunk_file) > 0:
                                    with open(chunk_file, 'r', encoding='utf-8') as infile:
                                        for l_idx, line in enumerate(infile):
                                            if (has_existing_main or c_idx > 0) and l_idx == 0 and "test_started" in line:
                                                continue
                                            outfile.write(line)
                                os.remove(chunk_file)
                            except Exception as e:
                                print(f"Error merging chunk {chunk_file}: {e}")
                                
                socketio.emit('report_compile_status', {'session_id': session_id, 'status': 'compiling', 'message': 'Compiling document report analytics...'})
                
                # 2. Compile DOCX report
                docx_path = os.path.join(session_dir, "report.docx")
                
                sla_overrides = {}
                if session.config:
                    sla_overrides['sla_success_rate'] = getattr(session.config, 'sla_success_rate', None)
                    sla_overrides['sla_latency'] = getattr(session.config, 'sla_latency', None)
                    sla_overrides['sla_packet_loss'] = getattr(session.config, 'sla_packet_loss', None)
                    sla_overrides['sla_jitter'] = getattr(session.config, 'sla_jitter', None)
                    sla_overrides['sla_join_latency'] = getattr(session.config, 'sla_join_latency', None)
                    sla_overrides['sla_min_fps'] = getattr(session.config, 'sla_min_fps', None)
                    sla_overrides['sla_max_disconnects'] = getattr(session.config, 'sla_max_disconnects', None)
                    sla_overrides['sla_min_bitrate'] = getattr(session.config, 'sla_min_bitrate', None)
                    
                compile_report_log(project_root, merged_log_path, docx_path, **sla_overrides)
                
                # Cache AI verdict and recommendations in DB
                session_json_path = os.path.join(session_dir, "session_report_data.json")
                if os.path.exists(session_json_path):
                    try:
                        with open(session_json_path, "r", encoding="utf-8") as tjf:
                            tdata = json.load(tjf)
                            session.ai_verdict = tdata.get("qa_verdict")
                            session.ai_engine_used = tdata.get("engine_attribution", {}).get("engine_name")
                            if tdata.get("ai_advisory"):
                                session.ai_recommendations_json = json.dumps(tdata["ai_advisory"])
                    except Exception as db_e:
                        print(f"Note: Could not parse AI report data for DB caching: {db_e}")

                pdf_path = convert_docx_to_pdf(docx_path, session_dir)
                if pdf_path:
                    session.report_pdf_path = pdf_path

                csv_candidate = os.path.join(session_dir, "session_action_lifecycle.csv")
                if os.path.exists(csv_candidate):
                    session.report_csv_path = csv_candidate

                session.report_log_path = merged_log_path
                session.report_docx_path = docx_path
                session.status = 'completed'
                db.session.commit()
                
                socketio.emit('report_compile_status', {'session_id': session_id, 'status': 'completed', 'message': 'Report compiled successfully!'})
                socketio.emit('session_status_changed', {
                    'session_id': session_id,
                    'status': 'completed'
                })
            except Exception as e:
                print(f"Async compilation failed for session {session_id}: {e}")
                session.status = 'failed'
                session.error_message = f"Compilation Error: {str(e)}"
                db.session.commit()
                socketio.emit('report_compile_status', {'session_id': session_id, 'status': 'failed', 'message': f'Compilation Failed: {str(e)}'})
                socketio.emit('session_status_changed', {
                    'session_id': session_id,
                    'status': 'failed'
                })
                
    threading.Thread(target=worker, daemon=True).start()

def find_libreoffice():
    """
    Checks the system PATH and common installation directories for LibreOffice.
    """
    import shutil
    # 1. Check system PATH
    path_res = shutil.which("soffice")
    if path_res:
        return path_res
        
    # 2. Check common Windows program paths
    if sys.platform == "win32":
        common_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for p in common_paths:
            if os.path.exists(p):
                return p
                
    # 3. Check common Linux paths
    common_linux = [
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/local/bin/soffice",
    ]
    for p in common_linux:
        if os.path.exists(p):
            return p
            
    return None

def convert_docx_to_pdf(docx_path, out_dir):
    """
    Converts compiled docx/markdown to pdf using LibreOffice with Playwright fallback.
    """
    try:
        from pdf_generator import convert_report_to_pdf
        return convert_report_to_pdf(docx_path, out_dir)
    except Exception as e:
        print(f"PDF conversion failed: {e}")
        return None

def start_session(app, socketio, session_id):
    """
    Triggers test execution runner thread.
    """
    # Use socketio start_background_task for compatibility with Eventlet greenlets
    socketio.start_background_task(run_test_process, app, socketio, session_id)
    return True

def pause_session(session_id):
    """
    Sets paused state in the control flag file.
    """
    with RUNNING_SESSIONS_LOCK:
        sess = RUNNING_SESSIONS.get(session_id)
        if not sess:
            return False
        
        control_file = sess["control_file"]
        try:
            with open(control_file, "w") as f:
                json.dump({"paused": True}, f)
            return True
        except Exception:
            return False

def resume_session(session_id):
    """
    Clears paused state in the control flag file.
    """
    with RUNNING_SESSIONS_LOCK:
        sess = RUNNING_SESSIONS.get(session_id)
        if not sess:
            return False
        
        control_file = sess["control_file"]
        try:
            with open(control_file, "w") as f:
                json.dump({"paused": False}, f)
            return True
        except Exception:
            return False

def stop_session(session_id):
    """
    Terminates the running processes gracefully:
    1. Writes {"stopped": True, "paused": False} to control.json so bots send leave_meeting.
    2. Sets internal stop_event.
    3. Waits a brief grace period (1.5s) for WebSocket leave packets to flush.
    4. Terminates the processes if still alive.
    """
    processes = []
    pid = None
    control_file = None
    stop_event = None
    
    with RUNNING_SESSIONS_LOCK:
        sess = RUNNING_SESSIONS.get(session_id)
        if sess:
            if "processes" in sess:
                processes = sess["processes"]
            elif "process" in sess and sess["process"]:
                processes = [sess["process"]]
            pid = sess.get("pid") or (processes[0].pid if processes else None)
            control_file = sess.get("control_file")
            stop_event = sess.get("stop_event")
            if stop_event:
                stop_event.set()
                
    session_dir = get_session_dir(session_id)
    if not control_file:
        control_file = os.path.join(session_dir, "control.json")

    # Step 1: Write stopped state to control.json
    try:
        if control_file and os.path.exists(os.path.dirname(control_file)):
            with open(control_file, "w") as f:
                json.dump({"stopped": True, "paused": False}, f)
    except Exception:
        pass

    # Step 2: Dedicated grace period for WebSocket leave_meeting signaling packets to flush
    import time
    time.sleep(2.5)

    if not pid:
        # Check DB
        try:
            session = TestSession.query.get(session_id)
            if session:
                pid = session.pid
        except Exception:
            pass

    if not pid and not processes:
        return False

    terminated = False
    if processes:
        for proc in processes:
            try:
                if proc.poll() is None:
                    # Send Ctrl+C signal or terminate
                    if sys.platform == "win32":
                        try:
                            proc.send_signal(signal.CTRL_C_EVENT)
                        except Exception:
                            proc.terminate()
                    else:
                        proc.send_signal(signal.SIGINT)
                terminated = True
            except Exception:
                try:
                    proc.terminate()
                    terminated = True
                except Exception:
                    pass
                
    if pid:
        try:
            import psutil
            if psutil.pid_exists(pid):
                p = psutil.Process(pid)
                cmd = p.cmdline()
                if any("py_guest" in arg for arg in cmd):
                    p.terminate()
                    terminated = True
        except Exception:
            pass
            
    return terminated

def adopt_running_sessions(app, socketio):
    """
    On startup, inspects active sessions in the database.
    If the bot process is still running on the OS, we re-adopt it by starting
    the log tailer. If it is not running, we mark it as stopped.
    """
    import psutil
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    with app.app_context():
        active_sessions = TestSession.query.filter(TestSession.status.in_(['running', 'paused'])).all()
        
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
                # Re-adopt session
                print(f"Adopting active session {session_id} (PID {pid})")
                session_dir = get_session_dir(session_id)
                control_file = os.path.join(session_dir, "control.json")
                report_log = os.path.join(session_dir, "report_log.jsonl")
                
                stop_event = threading.Event()
                
                with RUNNING_SESSIONS_LOCK:
                    RUNNING_SESSIONS[session_id] = {
                        "process": None,
                        "pid": pid,
                        "stop_event": stop_event,
                        "control_file": control_file
                    }
                
                socketio.start_background_task(
                    monitor_adopted_session, app, socketio, session_id, pid, report_log, stop_event
                )
            else:
                # Mark as stopped since the process is dead
                print(f"Cleaning up orphaned session {session_id} (PID {pid})")
                session.status = 'stopped'
                session.ended_at = datetime.utcnow()
                session.error_message = "Session terminated gracefully during server startup/restart."
                db.session.commit()

def monitor_adopted_session(app, socketio, session_id, pid, report_log, stop_event):
    """
    Monitors an adopted process by PID, streams metrics, and handles post-processing when it exits.
    """
    import psutil
    
    # Start log parsing and metric streaming thread
    socketio.start_background_task(
        stream_metrics_and_logs, app, socketio, session_id, report_log, stop_event, None
    )
    
    # Poll process exit
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
        socketio.sleep(1.0)
        
    # Process has exited
    stop_event.set()
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    session_dir = get_session_dir(session_id)
    report_docx = os.path.join(session_dir, "report.docx")
    
    final_status = "completed"
    with app.app_context():
        session = TestSession.query.get(session_id)
        if session:
            if session.status not in ("stopped", "failed"):
                session.status = "completed"
                
            session.ended_at = datetime.utcnow()
            
            # Post-Process: Compile report
            try:
                compile_report_log(project_root, report_log, report_docx)
            except Exception as cre:
                print(f"Error compiling report log: {cre}")
                
            # Convert DOCX to PDF
            try:
                pdf_path = convert_docx_to_pdf(report_docx, session_dir)
                if pdf_path:
                    session.report_pdf_path = pdf_path
            except Exception as cpe:
                print(f"Error converting docx to pdf: {cpe}")
                
            db.session.commit()
            final_status = session.status
            
    with RUNNING_SESSIONS_LOCK:
        if session_id in RUNNING_SESSIONS:
            del RUNNING_SESSIONS[session_id]
            
    socketio.emit('session_status_changed', {
        'session_id': session_id,
        'status': final_status
    })
