import os
import json
import asyncio
import time
import psutil
from datetime import datetime
from database import SessionLocal
from models import TestSession, SessionMetric

def safe_fromisoformat(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    # Clean Z suffix for Python < 3.11 compatibility
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    return datetime.fromisoformat(val)

def start_monitoring_task(session_id: int, log_path: str, stop_event: asyncio.Event, process=None):
    """Launches the metrics tracking loop as a non-blocking asyncio background task."""
    asyncio.create_task(stream_metrics_and_logs_async(session_id, log_path, stop_event, process))

async def stream_metrics_and_logs_async(session_id: int, log_path: str, stop_event: asyncio.Event, process=None):
    """
    Reads the JSONL log file as it grows, parses events, gathers CPU/RAM/network,
    and broadcasts updates to all active WebSocket connections.
    """
    # Wait for file creation (up to 10 seconds)
    target_path = log_path
    chunk_1_path = log_path.replace(".jsonl", "_chunk_1.jsonl")
    
    start_wait = time.time()
    while time.time() - start_wait < 60.0:
        if os.path.exists(chunk_1_path):
            target_path = chunk_1_path
            break
        if os.path.exists(log_path):
            target_path = log_path
            break
        if process and process.poll() is not None:
            break
        await asyncio.sleep(0.2)
        
    # Import websocket broadcaster
    from routers.websocket import broadcast_raw_events, broadcast_console_logs, broadcast_metrics
    
    # Fallback to reading process stdout directly if file creation fails
    if not os.path.exists(target_path):
        if not process:
            return
        print(f"Log file not created. Falling back to stdout monitoring for session {session_id}")
        console_buffer = []
        last_log_time = time.time()
        while not stop_event.is_set():
            line = await asyncio.to_thread(process.stdout.readline)
            if not line:
                break
            print(f"[SUBPROCESS] {line.strip()}", flush=True)
            console_buffer.append(line.strip())
            now_t = time.time()
            if now_t - last_log_time >= 0.5 or len(console_buffer) >= 100:
                last_log_time = now_t
                logs_to_send = console_buffer[:25]
                await broadcast_console_logs(session_id, logs_to_send)
                console_buffer.clear()
        return

    # Load configuration SLA thresholds on startup
    sla_thresholds = {
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
    
    db = SessionLocal()
    try:
        session = db.query(TestSession).get(session_id)
        if session and session.config:
            if session.config.sla_thresholds:
                try:
                    loaded = json.loads(session.config.sla_thresholds)
                    for k, v in loaded.items():
                        if v is not None:
                            sla_thresholds[k] = float(v)
                except Exception as ex:
                    print(f"Error loading SLA thresholds: {ex}")
    except Exception as ex:
        print(f"Error querying session config: {ex}")
    finally:
        db.close()

    # Running aggregation state
    metrics_state = {
        "connected_bots": 0,
        "connecting_bots": 0,
        "failed_bots": 0,
        "reconnecting_bots": 0,
        "ack_latencies": [],
        "propagation_latencies": [],
        "rtt_latencies": [],
        "peak_latency": 0.0,
        "packet_losses": [],
        "jitters": [],
        "bitrates": [],
        "status_counts": {
            "sent": 0, "acknowledged": 0, "broadcasted": 0,
            "observed": 0, "rendered": 0, "timed-out": 0,
            "failed": 0, "unsupported": 0
        },
        "timeout_stages": {
            "ack-timeout": 0, "broadcast-timeout": 0,
            "observer-timeout": 0, "ui-render-timeout": 0,
            "id-correlation-mismatch": 0
        },
        "unsupported_reasons": {},
        "turn_count": 0,
        "relay_count": 0,
        "join_timestamps": [],
        "chat_timestamps": [],
        "event_timestamps": [],
        "join_times": []
    }
    
    joined_ids = set()
    failed_ids = set()
    active_bot_ids = set()
    bot_start_times = {}
    bot_fingerprints = {}

    # Initialize error categories state
    error_definitions = {
        "WebSocket": ("High", "WebSocket connection to edge signaling server interrupted."),
        "WebRTC": ("Critical", "WebRTC peer connection establishment failed."),
        "ICE": ("High", "ICE candidate gathering or connection failed."),
        "DTLS": ("Critical", "DTLS handshake failed between emulator and media server."),
        "Authentication": ("Critical", "Authentication failed. Check JWT signing key."),
        "Signaling": ("High", "Signaling command failed or rejected by server."),
        "Media": ("Medium", "Media track creation or codec negotiation failed."),
        "Network": ("High", "General socket connection or packet loss error."),
        "Timeout": ("Medium", "Action acknowledgement or observation timed out."),
        "Unknown": ("Low", "Unclassified warning or event error.")
    }
    errors_state = {
        cat: { "count": 0, "last_occurrence": None, "severity": sev, "suggested_cause": cause }
        for cat, (sev, cause) in error_definitions.items()
    }

    def classify_error(err_msg: str, action: str = None) -> str:
        err_lower = err_msg.lower() if err_msg else ""
        act_lower = action.lower() if action else ""
        if "websocket" in err_lower or "ws" in err_lower:
            return "WebSocket"
        elif "ice" in err_lower or "stun" in err_lower or "turn" in err_lower:
            return "ICE"
        elif "dtls" in err_lower or "handshake" in err_lower or "cipher" in err_lower:
            return "DTLS"
        elif "webrtc" in err_lower or "peerconnection" in err_lower or "sdp" in err_lower:
            return "WebRTC"
        elif "auth" in err_lower or "jwt" in err_lower or "token" in err_lower:
            return "Authentication"
        elif "signaling" in err_lower or "signal" in err_lower:
            return "Signaling"
        elif "media" in err_lower or "track" in err_lower or "codec" in err_lower or "fps" in err_lower:
            return "Media"
        elif "network" in err_lower or "connect" in err_lower or "socket" in err_lower or "disconnect" in err_lower:
            return "Network"
        elif "timeout" in err_lower or "time out" in err_lower or "ack-timeout" in err_lower:
            return "Timeout"
        else:
            if "webrtc" in act_lower:
                return "WebRTC"
            elif "signaling" in act_lower:
                return "Signaling"
            return "Unknown"

    def record_classified_error(category: str, timestamp_str: str):
        if category in errors_state:
            errors_state[category]["count"] += 1
            errors_state[category]["last_occurrence"] = timestamp_str

    # Initialize host network throughput variables
    try:
        net_io = psutil.net_io_counters()
        last_net_bytes = net_io.bytes_sent + net_io.bytes_recv
    except Exception:
        last_net_bytes = 0
    last_net_time = time.time()
    
    last_system_metrics_time = time.time()
    last_broadcast_time = time.time()
    raw_events_buffer = []

    # Open log files for reading (both target_path and chunk log files)
    opened_files = {}
    try:
        # Tailing loop
        while not stop_event.is_set():
            candidate_paths = []
            if os.path.exists(target_path):
                candidate_paths.append(target_path)
            
            session_dir = os.path.dirname(target_path)
            if os.path.exists(session_dir):
                try:
                    for fname in os.listdir(session_dir):
                        if fname.startswith("report_log_chunk_") and fname.endswith(".jsonl"):
                            candidate_paths.append(os.path.join(session_dir, fname))
                except Exception:
                    pass
            
            # Open new candidate files
            for p in candidate_paths:
                if p not in opened_files:
                    try:
                        opened_files[p] = open(p, 'r', encoding='utf-8')
                    except Exception:
                        pass
            
            # Read from all opened files
            lines = []
            for p, f_obj in list(opened_files.items()):
                try:
                    if not os.path.exists(p):
                        f_obj.close()
                        opened_files.pop(p)
                        continue
                    
                    chunk_lines = await asyncio.to_thread(f_obj.readlines)
                    if chunk_lines:
                        lines.extend(chunk_lines)
                except Exception:
                    pass
            
            # Process any new lines
            if lines:
                for line in lines:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        event = json.loads(line_str)
                        etype = event.get("event")
                        ts_str = event.get("ts", datetime.utcnow().isoformat())
                        
                        # Track event timestamps for EPS calculation
                        metrics_state["event_timestamps"].append(time.time())
                        
                        # Add raw event to queue/buffer
                        raw_events_buffer.append(event)
                        
                        # Process metric tallies
                        bot_id = event.get("bot_id")
                        
                        if etype == "bot_connecting" and bot_id:
                            metrics_state["connecting_bots"] += 1
                            bot_start_times[bot_id] = safe_fromisoformat(ts_str)
                        elif etype == "bot_reconnecting" and bot_id:
                            metrics_state["reconnecting_bots"] += 1
                            bot_start_times[bot_id] = safe_fromisoformat(ts_str)
                        elif etype == "bot_joined" and bot_id:
                            joined_ids.add(bot_id)
                            metrics_state["connecting_bots"] = max(0, metrics_state["connecting_bots"] - 1)
                            metrics_state["connected_bots"] = len(joined_ids)
                            
                            # Track join rate timestamps
                            metrics_state["join_timestamps"].append(time.time())
                            
                            # Calculate bot join duration
                            if bot_id in bot_start_times:
                                t_start = bot_start_times[bot_id]
                                t_end = safe_fromisoformat(ts_str)
                                join_dur = (t_end - t_start).total_seconds() * 1000.0
                                metrics_state["join_times"].append(join_dur)
                                
                            # Save bot fingerprint
                            fp = event.get("fingerprint", {})
                            if fp:
                                bot_fingerprints[bot_id] = fp
                                
                        elif etype == "action_logged":
                            act_type = event.get("action_type")
                            status = event.get("status")
                            final_status = event.get("final_status")
                            lat = event.get("latency_ms")
                            
                            # Track chat messages for MPS
                            if act_type == "chat" and status == "sent":
                                metrics_state["chat_timestamps"].append(time.time())
                            
                            if act_type == "webrtc_connection":
                                if status == "confirmed":
                                    metrics_state["connected_bots"] = len(joined_ids)
                                    metrics_state["reconnecting_bots"] = max(0, metrics_state["reconnecting_bots"] - 1)
                                    active_bot_ids.add(bot_id)
                                elif status == "failed":
                                    failed_ids.add(bot_id)
                                    metrics_state["failed_bots"] = len(failed_ids)
                                    metrics_state["connected_bots"] = max(0, metrics_state["connected_bots"] - 1)
                                    active_bot_ids.discard(bot_id)
                                    category = classify_error("WebRTC connection failed", act_type)
                                    record_classified_error(category, ts_str)
                            
                            # Track separated latencies and update peak latency
                            resolved_status = final_status or status
                            if resolved_status in ("confirmed", "acknowledged"):
                                if lat is not None:
                                    metrics_state["ack_latencies"].append(lat)
                                    metrics_state["peak_latency"] = max(metrics_state["peak_latency"], lat)
                            elif resolved_status == "observed" or resolved_status == "rendered" or (resolved_status and resolved_status.startswith("observed:")):
                                if lat is not None:
                                    metrics_state["propagation_latencies"].append(lat)
                                    metrics_state["peak_latency"] = max(metrics_state["peak_latency"], lat)
                                    
                            # Update propagation lifecycle counts
                            if resolved_status == "confirmed":
                                resolved_status = "acknowledged"
                            elif resolved_status in ("timeout", "timed_out"):
                                resolved_status = "timed-out"
                            elif resolved_status and resolved_status.startswith("observed"):
                                resolved_status = "observed"
                                
                            if resolved_status in metrics_state["status_counts"]:
                                metrics_state["status_counts"][resolved_status] += 1
                                
                            # Handle failures and timeouts
                            if resolved_status == "timed-out":
                                t_stage = event.get("timeout_stage", "ack-timeout")
                                if t_stage in metrics_state["timeout_stages"]:
                                    metrics_state["timeout_stages"][t_stage] += 1
                                category = classify_error(f"Action timeout at stage: {t_stage}", act_type)
                                record_classified_error(category, ts_str)
                            elif resolved_status == "failed":
                                category = classify_error("Action failed", act_type)
                                record_classified_error(category, ts_str)
                            elif resolved_status == "unsupported":
                                reason = event.get("unsupported_reason", "unknown")
                                metrics_state["unsupported_reasons"][reason] = metrics_state["unsupported_reasons"].get(reason, 0) + 1
                                category = classify_error(f"Unsupported action: {reason}", act_type)
                                record_classified_error(category, ts_str)
                                
                        elif etype == "webrtc_stats_logged":
                            rtt = event.get("rtt")
                            loss = event.get("packet_loss")
                            jitter = event.get("jitter")
                            bitrate = event.get("bitrate")
                            turn_usage = event.get("turn_usage")
                            cand_type = event.get("candidate_pair_type")
                            
                            if rtt is not None:
                                metrics_state["rtt_latencies"].append(rtt)
                                metrics_state["peak_latency"] = max(metrics_state["peak_latency"], rtt)
                            if loss is not None:
                                metrics_state["packet_losses"].append(loss)
                            if jitter is not None:
                                metrics_state["jitters"].append(jitter)
                            if bitrate is not None:
                                metrics_state["bitrates"].append(bitrate)
                            
                            if turn_usage is True or str(turn_usage).lower() == 'true':
                                metrics_state["turn_count"] += 1
                            if cand_type == 'relay':
                                metrics_state["relay_count"] += 1
                            
                        elif etype == "error_logged":
                            metrics_state["failed_bots"] += 1
                            err_msg = event.get("error", "Unknown error")
                            act = event.get("action")
                            category = classify_error(err_msg, act)
                            record_classified_error(category, ts_str)
                            
                        # Extract WebRTC parameters if logged in summaries
                        webrtc_data = event.get("summary", {}).get("webrtc_performance", {})
                        if webrtc_data:
                            for b_type, b_stats in webrtc_data.items():
                                if "avg_packet_loss" in b_stats:
                                    metrics_state["packet_losses"].append(b_stats["avg_packet_loss"])
                                if "avg_jitter" in b_stats:
                                    metrics_state["jitters"].append(b_stats["avg_jitter"])
                                if "avg_bitrate" in b_stats:
                                    metrics_state["bitrates"].append(b_stats["avg_bitrate"])
                                    
                    except Exception as parse_err:
                        print(f"Error parsing log line for session {session_id}: {parse_err}")

            # Every 500ms, collect metrics, update DB, and broadcast updates
            now_t = time.time()
            if now_t - last_broadcast_time >= 0.5:
                last_broadcast_time = now_t
                
                # 1. Throttled WebSocket Broadcasts of raw events
                if raw_events_buffer:
                    # Cap/sample the events sent to the dashboard log view to 50 events per second
                    # (25 events per 500ms block)
                    events_to_send = raw_events_buffer[:25]
                    await broadcast_raw_events(session_id, events_to_send)
                    raw_events_buffer.clear()
                
                # 2. Update stats & save to DB (every 1 second)
                if now_t - last_system_metrics_time >= 1.0:
                    last_system_metrics_time = now_t
                    
                    # Retrieve host resource stats
                    try:
                        cpu = psutil.cpu_percent()
                        ram = psutil.virtual_memory().percent
                        
                        # Network throughput
                        net_io = psutil.net_io_counters()
                        net_bytes = net_io.bytes_sent + net_io.bytes_recv
                        dt = now_t - last_net_time
                        if dt > 0:
                            net_throughput_kbps = ((net_bytes - last_net_bytes) * 8.0) / (dt * 1024.0)
                        else:
                            net_throughput_kbps = 0.0
                        last_net_bytes = net_bytes
                        last_net_time = now_t
                    except Exception:
                        cpu, ram, net_throughput_kbps = 0.0, 0.0, 0.0
                        
                    # Calculate rates
                    metrics_state["join_timestamps"] = [t for t in metrics_state["join_timestamps"] if now_t - t <= 5.0]
                    metrics_state["chat_timestamps"] = [t for t in metrics_state["chat_timestamps"] if now_t - t <= 5.0]
                    metrics_state["event_timestamps"] = [t for t in metrics_state["event_timestamps"] if now_t - t <= 5.0]
                    
                    join_rate = len(metrics_state["join_timestamps"]) / 5.0
                    mps = len(metrics_state["chat_timestamps"]) / 5.0
                    eps = len(metrics_state["event_timestamps"]) / 5.0
                    
                    # Calculate averages
                    avg_ack = sum(metrics_state["ack_latencies"]) / len(metrics_state["ack_latencies"]) if metrics_state["ack_latencies"] else 0.0
                    avg_prop = sum(metrics_state["propagation_latencies"]) / len(metrics_state["propagation_latencies"]) if metrics_state["propagation_latencies"] else 0.0
                    avg_rtt = sum(metrics_state["rtt_latencies"]) / len(metrics_state["rtt_latencies"]) if metrics_state["rtt_latencies"] else 0.0
                    
                    avg_loss = sum(metrics_state["packet_losses"]) / len(metrics_state["packet_losses"]) if metrics_state["packet_losses"] else 0.0
                    avg_jitter = sum(metrics_state["jitters"]) / len(metrics_state["jitters"]) if metrics_state["jitters"] else 0.0
                    avg_bitrate = sum(metrics_state["bitrates"]) / len(metrics_state["bitrates"]) if metrics_state["bitrates"] else 0
                    avg_join_time = sum(metrics_state["join_times"]) / len(metrics_state["join_times"]) if metrics_state["join_times"] else 0.0
                    
                    # Distributions
                    browser_dist = {}
                    device_dist = {}
                    os_dist = {}
                    net_dist = {}
                    
                    for bid in joined_ids:
                        fp = bot_fingerprints.get(bid, {})
                        b = fp.get("browser_name", "Chrome")
                        d = fp.get("device_type", "desktop")
                        o = fp.get("os_type", "windows")
                        n = fp.get("network_profile", "wi-fi")
                        
                        browser_dist[b] = browser_dist.get(b, 0) + 1
                        device_dist[d] = device_dist.get(d, 0) + 1
                        os_dist[o] = os_dist.get(o, 0) + 1
                        net_dist[n] = net_dist.get(n, 0) + 1
                    
                    total_joined = len(joined_ids) or 1
                    dist_payload = {
                        "browser": {k: {"count": v, "pct": (v / total_joined) * 100.0} for k, v in browser_dist.items()},
                        "device": {k: {"count": v, "pct": (v / total_joined) * 100.0} for k, v in device_dist.items()},
                        "os": {k: {"count": v, "pct": (v / total_joined) * 100.0} for k, v in os_dist.items()},
                        "network": {k: {"count": v, "pct": (v / total_joined) * 100.0} for k, v in net_dist.items()}
                    }
                    
                    # Calculate active session duration
                    elapsed_ms = 0.0
                    paused = False
                    control_file = os.path.join(os.path.dirname(log_path), "control.json")
                    if os.path.exists(control_file):
                        try:
                            with open(control_file, "r") as ctrl_f:
                                cdata = json.load(ctrl_f)
                                paused = cdata.get("paused", False)
                                started_at_str = cdata.get("started_at")
                                total_paused_ms = cdata.get("total_paused_ms", 0.0)
                                last_paused_at_str = cdata.get("last_paused_at")
                                
                                if started_at_str:
                                    t_start = safe_fromisoformat(started_at_str)
                                    if paused and last_paused_at_str:
                                        t_pause = safe_fromisoformat(last_paused_at_str)
                                        elapsed_ms = (t_pause - t_start).total_seconds() * 1000.0 - total_paused_ms
                                    else:
                                        elapsed_ms = (datetime.utcnow() - t_start).total_seconds() * 1000.0 - total_paused_ms
                        except Exception:
                            pass
                    if elapsed_ms < 0.0:
                        elapsed_ms = 0.0

                    # Write to database (SessionMetric) in background thread
                    def save_metrics_to_db():
                        db = SessionLocal()
                        try:
                            session = db.query(TestSession).get(session_id)
                            if session and session.status in ("running", "paused"):
                                metric_entry = SessionMetric(
                                    session_id=session_id,
                                    connected_bots=metrics_state["connected_bots"],
                                    connecting_bots=metrics_state["connecting_bots"],
                                    failed_bots=metrics_state["failed_bots"],
                                    reconnecting_bots=metrics_state["reconnecting_bots"],
                                    active_bots=len(active_bot_ids),
                                    cpu_usage=cpu,
                                    ram_usage=ram,
                                    net_throughput_kbps=net_throughput_kbps,
                                    avg_latency=avg_prop,
                                    ack_latency=avg_ack,
                                    peak_latency=metrics_state["peak_latency"],
                                    packet_loss=avg_loss,
                                    jitter=avg_jitter,
                                    bitrate=int(avg_bitrate),
                                    join_rate=join_rate,
                                    avg_join_time=avg_join_time,
                                    mps=mps,
                                    eps=eps
                                )
                                db.add(metric_entry)
                                db.commit()
                        except Exception as db_err:
                            print(f"Error saving session metric to DB: {db_err}")
                        finally:
                            db.close()
                    
                    await asyncio.to_thread(save_metrics_to_db)
                    
                    # Evaluate SLA compliance
                    sla_status = {}
                    try:
                        sla_status["max_ack_latency"] = {
                            "pass": avg_ack <= sla_thresholds["max_ack_latency"],
                            "measured": avg_ack,
                            "limit": sla_thresholds["max_ack_latency"]
                        }
                        sla_status["max_join_time"] = {
                            "pass": avg_join_time <= sla_thresholds["max_join_time"],
                            "measured": avg_join_time,
                            "limit": sla_thresholds["max_join_time"]
                        }
                        sla_status["max_connection_time"] = {
                            "pass": avg_prop <= sla_thresholds["max_connection_time"],
                            "measured": avg_prop,
                            "limit": sla_thresholds["max_connection_time"]
                        }
                        sla_status["max_webrtc_setup_time"] = {
                            "pass": avg_rtt <= sla_thresholds["max_webrtc_setup_time"],
                            "measured": avg_rtt,
                            "limit": sla_thresholds["max_webrtc_setup_time"]
                        }
                        sla_status["max_ice_negotiation_time"] = {
                            "pass": True,
                            "measured": 0.0,
                            "limit": sla_thresholds["max_ice_negotiation_time"]
                        }
                        sla_status["max_dtls_handshake_time"] = {
                            "pass": True,
                            "measured": 0.0,
                            "limit": sla_thresholds["max_dtls_handshake_time"]
                        }
                        sla_status["max_packet_loss"] = {
                            "pass": (avg_loss * 100.0) <= sla_thresholds["max_packet_loss"],
                            "measured": avg_loss * 100.0,
                            "limit": sla_thresholds["max_packet_loss"]
                        }
                        sla_status["max_jitter"] = {
                            "pass": avg_jitter <= sla_thresholds["max_jitter"],
                            "measured": avg_jitter,
                            "limit": sla_thresholds["max_jitter"]
                        }
                        success_rate = 100.0
                        total_actions = metrics_state["status_counts"]["acknowledged"] + metrics_state["status_counts"]["timed-out"] + metrics_state["status_counts"]["failed"]
                        if total_actions > 0:
                            success_rate = (metrics_state["status_counts"]["acknowledged"] / total_actions) * 100.0
                        sla_status["min_success_rate"] = {
                            "pass": success_rate >= sla_thresholds["min_success_rate"],
                            "measured": success_rate,
                            "limit": sla_thresholds["min_success_rate"]
                        }
                        sla_status["max_cpu_usage"] = {
                            "pass": cpu <= sla_thresholds["max_cpu_usage"],
                            "measured": cpu,
                            "limit": sla_thresholds["max_cpu_usage"]
                        }
                        sla_status["max_memory_usage"] = {
                            "pass": ram <= sla_thresholds["max_memory_usage"],
                            "measured": ram,
                            "limit": sla_thresholds["max_memory_usage"]
                        }
                    except Exception as sla_ex:
                        print(f"SLA evaluation error: {sla_ex}")

                    metrics_payload = {
                        "session_id": session_id,
                        "connected_bots": metrics_state["connected_bots"],
                        "connecting_bots": metrics_state["connecting_bots"],
                        "failed_bots": metrics_state["failed_bots"],
                        "reconnecting_bots": metrics_state["reconnecting_bots"],
                        "active_bots": len(active_bot_ids),
                        "cpu_usage": cpu,
                        "ram_usage": ram,
                        "net_throughput_kbps": net_throughput_kbps,
                        "avg_latency": avg_prop,
                        "ack_latency": avg_ack,
                        "peak_latency": metrics_state["peak_latency"],
                        "packet_loss": avg_loss,
                        "jitter": avg_jitter,
                        "bitrate": int(avg_bitrate),
                        "join_rate": join_rate,
                        "avg_join_time": avg_join_time,
                        "mps": mps,
                        "eps": eps,
                        "elapsed_ms": elapsed_ms,
                        "paused": paused,
                        "sla_status": sla_status
                    }
                    
                    lifecycle_payload = {
                        'status_counts': metrics_state["status_counts"],
                        'timeout_stages': metrics_state["timeout_stages"],
                        'unsupported_reasons': metrics_state["unsupported_reasons"],
                        'webrtc_advanced': {
                            'rtt': avg_rtt,
                            'loss': avg_loss,
                            'jitter': avg_jitter,
                            'bitrate': avg_bitrate,
                            'turn_count': metrics_state["turn_count"],
                            'relay_count': metrics_state["relay_count"]
                        },
                        'distributions': dist_payload,
                        'errors': errors_state
                    }
                    await broadcast_metrics(session_id, metrics_payload, lifecycle_payload)

                    # Truncate lists to control memory
                    metrics_state["ack_latencies"] = metrics_state["ack_latencies"][-100:]
                    metrics_state["propagation_latencies"] = metrics_state["propagation_latencies"][-100:]
                    metrics_state["rtt_latencies"] = metrics_state["rtt_latencies"][-100:]
                    metrics_state["packet_losses"] = metrics_state["packet_losses"][-100:]
                    metrics_state["jitters"] = metrics_state["jitters"][-100:]
                    metrics_state["bitrates"] = metrics_state["bitrates"][-100:]

            # If no lines were read, wait a bit
            if not lines:
                await asyncio.sleep(0.1)
    finally:
        for p, f_obj in list(opened_files.items()):
            try:
                f_obj.close()
            except Exception:
                pass
        opened_files.clear()
