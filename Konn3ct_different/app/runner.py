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

def get_session_dir(session_id):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    session_dir = os.path.join(project_root, "sessions", f"session_{session_id}")
    os.makedirs(session_dir, exist_ok=True)
    return session_dir

def get_python_executable(project_root):
    """
    Resolves the python interpreter path. Prefers the virtual environment's python
    to guarantee all dependencies (docx, aiortc, etc.) are available.
    """
    if sys.platform == "win32":
        venv_python = os.path.join(project_root, ".venv", "Scripts", "python.exe")
    else:
        venv_python = os.path.join(project_root, ".venv", "bin", "python")
        
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable

def run_test_process(app, socketio, session_id):
    """
    Background worker that runs the subprocess, tails logs, aggregates metrics, 
    and converts the final docx report to pdf.
    """
    import traceback
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
                "--degradation-interval", str(config.degradation_interval),
                "--sla-success-rate", str(getattr(config, 'sla_success_rate', 95.0)),
                "--sla-latency", str(getattr(config, 'sla_latency', 500.0)),
                "--sla-packet-loss", str(getattr(config, 'sla_packet_loss', 2.0)),
                "--sla-jitter", str(getattr(config, 'sla_jitter', 30.0)),
                "--cross-confirm-limit", str(getattr(config, 'cross_confirm_limit', 10)),
                "--camera-publishers", getattr(config, 'camera_publishers', "1,2,3,4,5"),
                "--screen-share-publishers", getattr(config, 'screen_share_publishers', "2"),
                "--mic-publishers", getattr(config, 'mic_publishers', "1,2,3,4,5"),
                "--viewer-bots", getattr(config, 'viewer_bots', "6-10000"),
                "--viewer-mode", getattr(config, 'viewer_mode', "receive_only")
            ]
            
            # Add flags
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
            if config.jwt_secret:
                cmd.extend(["--jwt-secret", config.jwt_secret])
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
                    
                for start_id, chunk_bots in chunks:
                    chunk_cmd = list(cmd)
                    try:
                        bots_idx = chunk_cmd.index("--bots")
                        chunk_cmd[bots_idx + 1] = str(chunk_bots)
                    except ValueError:
                        chunk_cmd.extend(["--bots", str(chunk_bots)])
                    chunk_cmd.extend(["--start-id", str(start_id)])
                    
                    # Use separate report log file for each process chunk to prevent concurrent write collisions and file truncation
                    chunk_report_log = f"{report_log.replace('.jsonl', '')}_chunk_{start_id}.jsonl"
                    try:
                        log_idx = chunk_cmd.index("--report-log")
                        chunk_cmd[log_idx + 1] = chunk_report_log
                    except ValueError:
                        chunk_cmd.extend(["--report-log", chunk_report_log])
                    
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
                
                # Wait for all processes to complete
                for proc in processes:
                    proc.communicate()
                success = all(proc.returncode == 0 for proc in processes)
                
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
                            
                        # Post-Process: Compile report if it doesn't exist
                        try:
                            compile_report_log(project_root, report_log, report_docx)
                        except Exception as cre:
                            print(f"Error compiling report log: {cre}")
                            
                        # Convert DOCX to PDF using LibreOffice
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
    
    # Wait for the first chunk log file to be created (up to 10 seconds)
    chunk_1_log = os.path.join(session_dir, f"{base_prefix}_chunk_1.jsonl")
    start_wait = time.time()
    while not os.path.exists(chunk_1_log) and time.time() - start_wait < 10.0:
        if process and process.poll() is not None:
            break
        socketio.sleep(0.2)
        
    if not os.path.exists(chunk_1_log):
        return

    # Running aggregation state
    metrics_state = {
        "connected_bots": 0,
        "connecting_bots": 0,
        "failed_bots": 0,
        "reconnecting_bots": 0,
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
    
    joined_ids = set()
    failed_ids = set()

    # Batching variables for raw events
    buffered_raw_events = []
    last_raw_emit_time = time.time()
    
    open_files = {} # chunk_id -> file_object
    
    try:
        while not stop_event.is_set():
            # 1. Discover all active chunk files
            pattern = os.path.join(session_dir, f"{base_prefix}_chunk_*.jsonl")
            chunk_files = glob.glob(pattern)
            
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
                        
                f = open_files[chunk_id]
                while True:
                    line = f.readline()
                    if not line:
                        break
                    any_new_lines = True
                    
                    try:
                        event = json.loads(line.strip())
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
                            metrics_state["connecting_bots"] = metrics_state["connecting_bots"] + 1
                        elif etype == "bot_reconnecting" and bot_id:
                            metrics_state["reconnecting_bots"] = metrics_state["reconnecting_bots"] + 1
                        elif etype == "bot_joined" and bot_id:
                            joined_ids.add(bot_id)
                            metrics_state["connecting_bots"] = max(0, metrics_state["connecting_bots"] - 1)
                            metrics_state["connected_bots"] = len(joined_ids)
                        elif etype == "action_logged":
                            act_type = event.get("action_type")
                            status = event.get("status")
                            final_status = event.get("final_status")
                            lat = event.get("latency_ms")
                            
                            if act_type == "webrtc_connection":
                                if status == "confirmed":
                                    metrics_state["connected_bots"] = len(joined_ids)
                                    metrics_state["reconnecting_bots"] = max(0, metrics_state["reconnecting_bots"] - 1)
                                elif status == "failed":
                                    failed_ids.add(bot_id)
                                    metrics_state["failed_bots"] = len(failed_ids)
                                    metrics_state["connected_bots"] = max(0, metrics_state["connected_bots"] - 1)
                            
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
                            metrics_state["failed_bots"] = metrics_state["failed_bots"] + 1
                            
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
                        
            # If no new lines were read, sleep and emit metrics
            if not any_new_lines:
                if buffered_raw_events:
                    socketio.emit('session_raw_events_batch', {
                        'session_id': session_id,
                        'events': buffered_raw_events
                    }, room=f"session_{session_id}")
                    buffered_raw_events = []
                    last_raw_emit_time = time.time()
                    
                socketio.sleep(0.5)
                
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
                        
                        # Emit metrics via Socket.IO
                        socketio.emit('session_metrics', {
                            'session_id': session_id,
                            'metrics': metric_entry.to_dict(),
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
                        }, room=f"session_{session_id}")
                        
                # Clear moving averages to only calculate recent windows
                metrics_state["latencies"] = metrics_state["latencies"][-50:]
                metrics_state["packet_losses"] = metrics_state["packet_losses"][-50:]
                metrics_state["jitters"] = metrics_state["jitters"][-50:]
                metrics_state["bitrates"] = metrics_state["bitrates"][-50:]
    finally:
        for f in open_files.values():
            try:
                f.close()
            except Exception:
                pass

def compile_report_log(project_root, log_path, docx_path):
    """
    Force executes generate_report.py to compile report if not completed.
    """
    if os.path.exists(docx_path):
        return
        
    generate_report_script = os.path.join(project_root, "generate_report.py")
    try:
        subprocess.run(
            [get_python_executable(project_root), generate_report_script, log_path, "--output", docx_path],
            check=True,
            capture_output=True
        )
        print(f"Successfully auto-compiled docx report: {docx_path}")
    except Exception as e:
        print(f"Failed to auto-compile docx report: {e}")

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
    Converts compiled docx to pdf using LibreOffice headless command line.
    """
    if not os.path.exists(docx_path):
        return None
        
    soffice_bin = find_libreoffice()
    if not soffice_bin:
        print("LibreOffice soffice binary not found. Skipping PDF conversion.")
        return None
        
    try:
        cmd = [soffice_bin, "--headless", "--convert-to", "pdf", "--outdir", out_dir, docx_path]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        pdf_path = docx_path.replace(".docx", ".pdf")
        if os.path.exists(pdf_path):
            print(f"Successfully converted report to PDF: {pdf_path}")
            return pdf_path
    except Exception as e:
        print(f"LibreOffice PDF conversion failed: {e}")
        
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
    Terminates the running processes using graceful signals.
    """
    processes = []
    pid = None
    with RUNNING_SESSIONS_LOCK:
        sess = RUNNING_SESSIONS.get(session_id)
        if sess:
            if "processes" in sess:
                processes = sess["processes"]
            elif "process" in sess and sess["process"]:
                processes = [sess["process"]]
            pid = sess.get("pid") or (processes[0].pid if processes else None)
            
    if not pid:
        # Check DB
        try:
            session = TestSession.query.get(session_id)
            if session:
                pid = session.pid
        except Exception:
            pass

    if not pid:
        return False

    terminated = False
    if processes:
        for proc in processes:
            try:
                # Send Ctrl+C signal to allow graceful exit and report compilation
                if sys.platform == "win32":
                    proc.send_signal(signal.CTRL_C_EVENT)
                else:
                    proc.send_signal(signal.SIGINT)
                terminated = True
            except Exception:
                # Fallback hard kill if signal fail
                try:
                    proc.terminate()
                    terminated = True
                except Exception:
                    pass
                
    if not terminated and pid:
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
