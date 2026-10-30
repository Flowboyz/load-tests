import os
import csv
import threading
import time
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, current_app, Response
from app.models import db, Configuration, TestSession, SessionMetric
from app.auth import token_required, roles_accepted
from app.runner import start_session, pause_session, resume_session, stop_session, get_session_dir

api_bp = Blueprint('api', __name__)

def stream_file_in_chunks(file_path, chunk_size=65536):
    """Streams a file in binary chunks to prevent high memory usage and socket timeouts."""
    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    except Exception as e:
        print(f"Error streaming file {file_path}: {e}")

# --- Configuration Template Routes ---

@api_bp.route('/configurations', methods=['GET'])
@token_required
def get_configurations():
    configs = Configuration.query.order_by(Configuration.created_at.desc()).all()
    return jsonify([c.to_dict() for c in configs])

@api_bp.route('/configurations', methods=['POST'])
@token_required
@roles_accepted('Admin', 'Operator')
def create_configuration():
    data = request.get_json() or {}
    name = data.get('name')
    if not name:
        return jsonify({'message': 'Configuration name is required!'}), 400
        
    if Configuration.query.filter_by(name=name).first():
        return jsonify({'message': 'A configuration with this name already exists!'}), 400
        
    # Exclude id and timestamps from creation data
    clean_data = {k: v for k, v in data.items() if k not in ('id', 'created_at', 'updated_at')}
    
    cfg = Configuration(**clean_data)
    db.session.add(cfg)
    db.session.commit()
    return jsonify(cfg.to_dict()), 201

@api_bp.route('/configurations/<int:cfg_id>', methods=['GET'])
@token_required
def get_configuration(cfg_id):
    cfg = Configuration.query.get_or_404(cfg_id)
    return jsonify(cfg.to_dict())

@api_bp.route('/configurations/<int:cfg_id>', methods=['PUT'])
@token_required
@roles_accepted('Admin', 'Operator')
def update_configuration(cfg_id):
    cfg = Configuration.query.get_or_404(cfg_id)
    data = request.get_json() or {}
    
    for key, value in data.items():
        if hasattr(cfg, key) and key not in ('id', 'created_at', 'updated_at'):
            setattr(cfg, key, value)
            
    db.session.commit()
    return jsonify(cfg.to_dict())

@api_bp.route('/configurations/<int:cfg_id>', methods=['DELETE'])
@token_required
@roles_accepted('Admin')
def delete_configuration(cfg_id):
    cfg = Configuration.query.get_or_404(cfg_id)
    db.session.delete(cfg)
    db.session.commit()
    return jsonify({'message': 'Configuration template deleted!'})


# --- Test Session Execution Routes ---

@api_bp.route('/sessions', methods=['GET'])
@token_required
def get_sessions():
    sessions = TestSession.query.order_by(TestSession.started_at.desc() if TestSession.started_at else TestSession.id.desc()).all()
    return jsonify([s.to_dict() for s in sessions])

@api_bp.route('/sessions/<int:session_id>', methods=['GET'])
@token_required
def get_session(session_id):
    session = TestSession.query.get_or_404(session_id)
    return jsonify(session.to_dict())

@api_bp.route('/sessions/start', methods=['POST'])
@token_required
@roles_accepted('Admin', 'Operator')
def start_test():
    data = request.get_json() or {}
    config_id = data.get('config_id')
    session_name = data.get('session_name')
    
    if not session_name:
        session_name = f"Test Run - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        
    cfg = None
    if config_id:
        cfg = Configuration.query.get(config_id)
        if not cfg:
            return jsonify({'message': 'Configuration template not found!'}), 404
            
    # Allow ad-hoc params overrides
    if not cfg:
        # Create a transient configuration for this session
        name = f"Ad-hoc Temp {int(time.time())}"
        clean_data = {k: v for k, v in data.items() if k not in ('config_id', 'session_name')}
        cfg = Configuration(name=name, **clean_data)
        db.session.add(cfg)
        db.session.commit()

    # Create new session entry
    new_sess = TestSession(
        config_id=cfg.id,
        name=session_name,
        status="pending"
    )
    db.session.add(new_sess)
    db.session.commit()
    
    # Trigger background runner process
    from flask import current_app
    socketio = current_app.extensions.get('socketio')
    start_session(current_app._get_current_object(), socketio, new_sess.id)
    
    return jsonify(new_sess.to_dict()), 201

@api_bp.route('/sessions/<int:session_id>/pause', methods=['POST'])
@token_required
@roles_accepted('Admin', 'Operator')
def pause_test(session_id):
    session = TestSession.query.get_or_404(session_id)
    if session.status != "running":
        return jsonify({'message': 'Only running sessions can be paused!'}), 400
        
    success = pause_session(session_id)
    if success:
        session.status = "paused"
        if session.last_resume_time:
            elapsed = (datetime.utcnow() - session.last_resume_time).total_seconds()
            session.accumulated_duration += int(elapsed)
        session.last_resume_time = None
        db.session.commit()
        
        from flask import current_app
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('session_status_changed', {
                'session_id': session_id,
                'status': 'paused',
                'elapsed_seconds': session.accumulated_duration
            }, room=f"session_{session_id}")
            
        return jsonify({'message': 'Test session paused.'})
    return jsonify({'message': 'Failed to pause test session.'}), 500

@api_bp.route('/sessions/<int:session_id>/resume', methods=['POST'])
@token_required
@roles_accepted('Admin', 'Operator')
def resume_test(session_id):
    session = TestSession.query.get_or_404(session_id)
    if session.status != "paused":
        return jsonify({'message': 'Only paused sessions can be resumed!'}), 400
        
    success = resume_session(session_id)
    if success:
        session.status = "running"
        session.last_resume_time = datetime.utcnow()
        db.session.commit()
        
        from flask import current_app
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('session_status_changed', {
                'session_id': session_id,
                'status': 'running',
                'elapsed_seconds': session.accumulated_duration
            }, room=f"session_{session_id}")
            
        return jsonify({'message': 'Test session resumed.'})
    return jsonify({'message': 'Failed to resume test session.'}), 500

@api_bp.route('/sessions/<int:session_id>/stop', methods=['POST'])
@token_required
@roles_accepted('Admin', 'Operator')
def stop_test(session_id):
    session = TestSession.query.get_or_404(session_id)
    if session.status not in ("running", "paused", "pending"):
        return jsonify({'message': 'Session is not active!'}), 400
        
    if session.status == "running" and session.last_resume_time:
        elapsed = (datetime.utcnow() - session.last_resume_time).total_seconds()
        session.accumulated_duration += int(elapsed)
    session.last_resume_time = None
    session.status = "stopped"
    session.ended_at = datetime.utcnow()
    db.session.commit()
    
    success = stop_session(session_id)
    
    from flask import current_app
    socketio = current_app.extensions.get('socketio')
    if socketio:
        socketio.emit('session_status_changed', {
            'session_id': session_id,
            'status': 'stopped',
            'elapsed_seconds': session.accumulated_duration
        }, room=f"session_{session_id}")
        
    if success:
        return jsonify({'message': 'Test session stopped gracefully.'})
    else:
        return jsonify({'message': 'Test session stopped (force database override).'})


@api_bp.route('/sessions/<int:session_id>/sla', methods=['PUT'])
@token_required
@roles_accepted('Admin', 'Operator')
def update_session_sla(session_id):
    session = TestSession.query.get_or_404(session_id)
    if not session.config:
        return jsonify({'message': 'Session has no associated configuration!'}), 400
        
    data = request.get_json() or {}
    
    if 'sla_success_rate' in data:
        session.config.sla_success_rate = float(data['sla_success_rate'])
    if 'sla_latency' in data:
        session.config.sla_latency = float(data['sla_latency'])
    if 'sla_packet_loss' in data:
        session.config.sla_packet_loss = float(data['sla_packet_loss'])
    if 'sla_jitter' in data:
        session.config.sla_jitter = float(data['sla_jitter'])
    if 'sla_join_latency' in data:
        session.config.sla_join_latency = float(data['sla_join_latency'])
    if 'sla_min_fps' in data:
        session.config.sla_min_fps = float(data['sla_min_fps'])
    if 'sla_max_disconnects' in data:
        session.config.sla_max_disconnects = float(data['sla_max_disconnects'])
    if 'sla_min_bitrate' in data:
        session.config.sla_min_bitrate = float(data['sla_min_bitrate'])
        
    db.session.commit()
    
    from flask import current_app
    socketio = current_app.extensions.get('socketio')
    if socketio:
        socketio.emit('session_sla_updated', {
            'session_id': session_id,
            'sla_success_rate': session.config.sla_success_rate,
            'sla_latency': session.config.sla_latency,
            'sla_packet_loss': session.config.sla_packet_loss,
            'sla_jitter': session.config.sla_jitter,
            'sla_join_latency': session.config.sla_join_latency,
            'sla_min_fps': session.config.sla_min_fps,
            'sla_max_disconnects': session.config.sla_max_disconnects,
            'sla_min_bitrate': session.config.sla_min_bitrate
        })
        
    return jsonify({
        'message': 'SLA thresholds updated successfully.',
        'sla_success_rate': session.config.sla_success_rate,
        'sla_latency': session.config.sla_latency,
        'sla_packet_loss': session.config.sla_packet_loss,
        'sla_jitter': session.config.sla_jitter,
        'sla_join_latency': session.config.sla_join_latency,
        'sla_min_fps': session.config.sla_min_fps,
        'sla_max_disconnects': session.config.sla_max_disconnects,
        'sla_min_bitrate': session.config.sla_min_bitrate
    })


# --- Logs & Performance Historical Data Routes ---

@api_bp.route('/sessions/<int:session_id>/logs', methods=['GET'])
@token_required
def get_session_logs(session_id):
    session = TestSession.query.get_or_404(session_id)
    session_dir = get_session_dir(session_id)
    log_path = os.path.join(session_dir, "report_log.jsonl")
    
    import glob
    import json
    log_files = []
    if os.path.exists(log_path):
        log_files = [log_path]
    else:
        chunk_pattern = os.path.join(session_dir, "report_log_chunk_*.jsonl")
        log_files = glob.glob(chunk_pattern)
        
    if not log_files:
        return jsonify([])
        
    logs = []
    limit = request.args.get('limit', 200, type=int)
    search_query = request.args.get('search', '', type=str).lower()
    
    for lf in sorted(log_files):
        try:
            with open(lf, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        raw_line = line.strip()
                        if not raw_line:
                            continue
                        if search_query and search_query not in raw_line.lower():
                            continue
                        evt = json.loads(raw_line)
                        logs.append(evt)
                    except Exception:
                        pass
        except Exception:
            pass
            
    # Sort events chronologically by timestamp if available
    try:
        logs.sort(key=lambda x: x.get("ts", ""))
    except Exception:
        pass
        
    return jsonify(logs[-limit:])

@api_bp.route('/sessions/<int:session_id>/metrics', methods=['GET'])
@token_required
def get_session_metrics(session_id):
    metrics = SessionMetric.query.filter_by(session_id=session_id).order_by(SessionMetric.timestamp.asc()).all()
    return jsonify([m.to_dict() for m in metrics])


# --- Report Download Routes ---

def find_valid_file(candidates, min_size=50):
    """Finds the first existing candidate file with size >= min_size, removing zero-byte corrupt stubs."""
    for path in candidates:
        if path and os.path.exists(path):
            try:
                size = os.path.getsize(path)
                if size >= min_size:
                    return path
                elif size == 0:
                    try:
                        os.remove(path)
                    except Exception:
                        pass
            except Exception:
                pass
    return None

@api_bp.route('/sessions/<int:session_id>/download/<string:fmt>', methods=['GET'])
@token_required
def download_report(session_id, fmt):
    session = TestSession.query.get_or_404(session_id)
    fmt = fmt.lower()
    
    session_dir = get_session_dir(session_id)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 1. Merge chunk logs if needed
    log_path = os.path.join(session_dir, "report_log.jsonl")
    import glob
    import json
    base_name = os.path.basename(log_path).replace(".jsonl", "")
    chunk_files = glob.glob(os.path.join(session_dir, f"{base_name}_chunk_*.jsonl"))
    
    if not os.path.exists(log_path) and chunk_files:
        try:
            chunk_files = sorted(
                chunk_files,
                key=lambda x: int(os.path.basename(x).split("_")[-1].replace(".jsonl", ""))
            )
            test_start_time = session.started_at.isoformat() + "Z" if session.started_at else datetime.utcnow().isoformat() + "Z"
            with open(log_path, "w", encoding="utf-8") as main_f:
                main_f.write(json.dumps({"event": "test_started", "ts": test_start_time}) + "\n")
                for chunk_file in chunk_files:
                    with open(chunk_file, "r", encoding="utf-8") as chunk_f:
                        for line in chunk_f:
                            if "test_started" in line:
                                continue
                            main_f.write(line)
            for chunk_file in chunk_files:
                try:
                    os.remove(chunk_file)
                except Exception:
                    pass
        except Exception as e:
            print(f"Error merging chunk logs on download: {e}")

    # File candidates resolution
    valid_log = find_valid_file([
        log_path,
        os.path.join(session_dir, f"session_{session_id}_logs.jsonl")
    ], min_size=10)

    valid_docx = find_valid_file([
        os.path.join(session_dir, "report.docx"),
        os.path.join(session_dir, f"session_{session_id}_report.docx"),
        os.path.join(session_dir, "test_output.docx")
    ], min_size=100)

    valid_pdf = find_valid_file([
        os.path.join(session_dir, "report.pdf"),
        os.path.join(session_dir, f"session_{session_id}_report.pdf"),
        os.path.join(session_dir, "test_output.pdf")
    ], min_size=100)

    valid_csv = find_valid_file([
        os.path.join(session_dir, "session_action_lifecycle.csv"),
        os.path.join(session_dir, "report_log_action_log.csv"),
        os.path.join(session_dir, "session_summary_metrics.csv"),
        os.path.join(session_dir, "session_webrtc_stats.csv")
    ], min_size=10)

    # If all files are completely absent, return error
    if not valid_log and not valid_docx and not valid_pdf and not valid_csv:
        return jsonify({'message': 'No logs or report documents found for this session. The test may have failed to start or write telemetry.'}), 400

    if fmt == 'json':
        if not valid_log:
            return jsonify({'message': 'JSON log file not found or empty!'}), 404
        return Response(
            stream_file_in_chunks(valid_log),
            mimetype='application/jsonl',
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_logs.jsonl",
                "Content-Length": os.path.getsize(valid_log)
            }
        )
        
    elif fmt == 'csv':
        if not valid_csv:
            from app.runner import compile_report_log_async
            from app import socketio
            compile_report_log_async(project_root, session_id, socketio)
            return jsonify({'message': 'Report is generating in the background. Please wait...', 'status': 'compiling'}), 202
            
        return Response(
            stream_file_in_chunks(valid_csv),
            mimetype='text/csv',
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_action_log.csv",
                "Content-Length": os.path.getsize(valid_csv)
            }
        )
        
    elif fmt == 'docx':
        if not valid_docx:
            from app.runner import compile_report_log_async
            from app import socketio
            compile_report_log_async(project_root, session_id, socketio)
            return jsonify({'message': 'Report is generating in the background. Please wait...', 'status': 'compiling'}), 202
            
        return Response(
            stream_file_in_chunks(valid_docx),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_report.docx",
                "Content-Length": os.path.getsize(valid_docx)
            }
        )
        
    elif fmt == 'pdf':
        # On-demand PDF synthesis if PDF missing but DOCX/MD exists
        if not valid_pdf:
            try:
                from pdf_generator import convert_report_to_pdf
                md_path = os.path.join(session_dir, "session_enhanced_analytics.md")
                pdf_gen = convert_report_to_pdf(valid_docx, session_dir, md_path=md_path if os.path.exists(md_path) else None)
                if pdf_gen and os.path.exists(pdf_gen) and os.path.getsize(pdf_gen) > 100:
                    valid_pdf = pdf_gen
            except Exception as e:
                print(f"On-demand PDF generation error: {e}")

        if not valid_pdf:
            from app.runner import compile_report_log_async
            from app import socketio
            compile_report_log_async(project_root, session_id, socketio)
            return jsonify({'message': 'Report is generating in the background. Please wait...', 'status': 'compiling'}), 202
            
        return Response(
            stream_file_in_chunks(valid_pdf),
            mimetype='application/pdf',
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_report.pdf",
                "Content-Length": os.path.getsize(valid_pdf)
            }
        )
        
    else:
        return jsonify({'message': 'Invalid download format! Must be JSON, CSV, DOCX, or PDF.'}), 400

# --- Mobile UI Test Integration Routes ---

@api_bp.route('/mobile/emulators', methods=['GET'])
@token_required
def get_mobile_emulators():
    from mobile_ui_tests.run_test import list_emulators
    try:
        devices = list_emulators()
        return jsonify(devices), 200
    except Exception as e:
        return jsonify({'message': f'Failed to retrieve emulator list: {str(e)}'}), 500

@api_bp.route('/mobile/flows', methods=['GET'])
@token_required
def get_mobile_flows():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    flows_dir = os.path.join(project_root, "mobile_ui_tests", "flows")
    
    if not os.path.exists(flows_dir):
        return jsonify([]), 200
        
    try:
        files = sorted([f for f in os.listdir(flows_dir) if (f.endswith('.yaml') or f.endswith('.yml'))])
        # Add run_all_gov_flows at the beginning
        files = ["run_all_gov_flows"] + files
        return jsonify(files), 200
    except Exception as e:
        return jsonify({'message': f'Failed to list test flows: {str(e)}'}), 500

@api_bp.route('/mobile/flow-content', methods=['GET'])
@token_required
def get_mobile_flow_content():
    flow_file = request.args.get('flow')
    if not flow_file:
        return jsonify({'message': 'Missing flow parameter'}), 400
        
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    flow_path = os.path.join(project_root, "mobile_ui_tests", "flows", flow_file)
    
    if not os.path.exists(flow_path) or not os.path.abspath(flow_path).startswith(os.path.join(project_root, "mobile_ui_tests")):
        return jsonify({'message': 'Invalid file path'}), 400
        
    try:
        with open(flow_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        from app.yaml_parser import parse_maestro_yaml
        parsed_data = parse_maestro_yaml(content)
        
        return jsonify({
            'content': content,
            'parsed': parsed_data
        }), 200
    except Exception as e:
        return jsonify({'message': f'Failed to read flow content: {str(e)}'}), 500

@api_bp.route('/mobile/save-flow', methods=['POST'])
@token_required
def save_mobile_flow():
    data = request.get_json()
    flow_file = data.get('flow')
    content = data.get('content')
    steps = data.get('steps')
    app_id = data.get('appId', 'com.konn3ct.mobile')
    
    if not flow_file:
        return jsonify({'message': 'Missing flow parameter'}), 400
        
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    flow_path = os.path.join(project_root, "mobile_ui_tests", "flows", flow_file)
    
    if not os.path.abspath(flow_path).startswith(os.path.join(project_root, "mobile_ui_tests")):
        return jsonify({'message': 'Invalid file path'}), 400
        
    if steps is not None:
        from app.yaml_parser import serialize_maestro_yaml
        content = serialize_maestro_yaml(app_id, steps)
        
    if content is None:
        return jsonify({'message': 'Missing content or steps parameter'}), 400
        
    try:
        with open(flow_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'message': 'Flow saved successfully!'}), 200
    except Exception as e:
        return jsonify({'message': f'Failed to save flow: {str(e)}'}), 500

# Background thread state for active mobile UI test runs
is_mobile_test_running = False
active_mobile_process = None


@api_bp.route('/mobile/run', methods=['POST'])
@token_required
def run_mobile_test():
    global is_mobile_test_running
    
    if is_mobile_test_running:
        return jsonify({'message': 'A mobile UI test is already running!'}), 400
        
    data = request.get_json() or {}
    flow_file = data.get('flow')
    device_id = data.get('device_id')
    apk_path = data.get('apk_path')
    api_key = data.get('api_key') or os.getenv('MAESTRO_API_KEY')
    project_id = data.get('project_id')
    room_slug = data.get('room_slug')
    cloud_model = data.get('cloud_model')
    cloud_os = data.get('cloud_os')
    app_type = data.get('app_type', 'mobile')
    
    if not flow_file:
        return jsonify({'message': 'Missing target flow file'}), 400
        
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    flow_path = os.path.join(project_root, "mobile_ui_tests", "flows", flow_file)
    
    if not os.path.abspath(flow_path).startswith(os.path.join(project_root, "mobile_ui_tests")):
        return jsonify({'message': 'Invalid file path'}), 400
        
    content = data.get('content')
    steps = data.get('steps')
    app_id = data.get('appId', 'com.konn3ct.mobile')
    
    if steps is not None:
        from app.yaml_parser import serialize_maestro_yaml
        content = serialize_maestro_yaml(app_id, steps)
        
    if content is not None:
        try:
            with open(flow_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            return jsonify({'message': f'Failed to autosave flow: {str(e)}'}), 500

    if flow_file != "run_all_gov_flows" and not os.path.exists(flow_path):
        return jsonify({'message': f'Flow file not found: {flow_file}'}), 404

    from app import socketio
    import threading
    from mobile_ui_tests.run_test import execute_flow_generator
    
    def run_in_background():
        global is_mobile_test_running
        is_mobile_test_running = True
        import time
        start_time = time.time()
        flows_dir = os.path.join(project_root, "mobile_ui_tests", "flows")
        
        is_multi_run = (flow_file == "run_all_gov_flows")
        
        if is_multi_run:
            all_gov_flows = [
                f for f in os.listdir(flows_dir)
                if f.startswith("gov_") and (f.endswith(".yaml") or f.endswith(".yml"))
                and f != "gov_uninstall_flow.yaml"
            ]
            filtered_flows = []
            for f in all_gov_flows:
                if f.endswith("_testids.yaml"):
                    filtered_flows.append(f)
                else:
                    base_name = f[:-5] if f.endswith(".yaml") else f[:-4]
                    testid_version = f"{base_name}_testids.yaml"
                    if testid_version not in all_gov_flows:
                        filtered_flows.append(f)
            flows_to_run = sorted(filtered_flows)
        else:
            flows_to_run = [flow_file]
            
        flow_results = []
        socketio.emit('mobile_ui_test_status', {'status': 'running'})
        
        def register_process(proc):
            global active_mobile_process
            active_mobile_process = proc
            
        try:
            for idx, current_flow in enumerate(flows_to_run):
                current_flow_start_time = time.time()
                current_flow_log_lines = []
                temp_flow_created = False
                
                current_flow_path = os.path.join(flows_dir, current_flow)
                target_flow_path = current_flow_path
                
                socketio.emit('mobile_ui_test_log', {'line': f'🔄 Starting Flow [{idx+1}/{len(flows_to_run)}]: {current_flow}...'})
                
                try:
                    with open(current_flow_path, 'r', encoding='utf-8') as f:
                        flow_content = f.read()
                    
                    serialized_content = flow_content
                    
                    if room_slug:
                        import re
                        pattern = r'(tapOn:\s*["\']?Join["\']?\s*\n\s*-\s*tapOn:\s*["\']?e\.g\.\s*general-meeting["\']?\s*\n\s*-\s*inputText:\s*)(["\']?[a-zA-Z0-9_\-]+["\']?)'
                        serialized_content = re.sub(pattern, rf'\g<1>"{room_slug}"', serialized_content)
                    
                    if app_type == "gov" or current_flow.startswith("gov_"):
                        import re
                        login_pattern = (
                            r'-\s*tapOn:\s*(?:\n\s*id:\s*["\']email-input["\']|["\']Demo@email\.com["\'])\s*\n'
                            r'\s*-\s*inputText:\s*["\']flowboyzamy@gmail\.com["\']\s*\n'
                            r'\s*-\s*tapOn:\s*(?:\n\s*id:\s*["\']password-input["\']|["\']Enter\s+your\s+password["\'])\s*\n'
                            r'\s*-\s*inputText:\s*["\']Samedo3333@["\']\s*\n'
                            r'\s*-\s*tapOn:\s*(?:\n\s*id:\s*["\']login-button["\']|["\']Login["\'])'
                        )
                        
                        replacement = (
                            '- tapOn:\n'
                            '    id: "mda-input"\n'
                            '- inputText: "konnectsandbox"\n'
                            '- hideKeyboard\n'
                            '- tapOn:\n'
                            '    id: "email-input"\n'
                            '- inputText: "odejinmisa@newwavesecosystem.com"\n'
                            '- hideKeyboard\n'
                            '- tapOn:\n'
                            '    id: "password-input"\n'
                            '- inputText: "827xazLF6TBfD7N!"\n'
                            '- hideKeyboard\n'
                            '- tapOn:\n'
                            '    id: "login-button"\n'
                            '- evalScript: "java.lang.Thread.sleep(5000)"'
                        )
                        serialized_content = re.sub(login_pattern, replacement, serialized_content)
                        
                    if app_id:
                        serialized_content = serialized_content.replace("com.konn3ct.mobile", app_id)
                        
                    if device_id == "maestro_cloud":
                        temp_dir_name = f"temp_workspace_{int(time.time())}_{idx}"
                        temp_workspace_dir = os.path.join(project_root, "mobile_ui_tests", "flows", temp_dir_name)
                        os.makedirs(temp_workspace_dir, exist_ok=True)
                        target_flow_path = os.path.join(temp_workspace_dir, current_flow)
                        with open(target_flow_path, 'w', encoding='utf-8') as f:
                            f.write(serialized_content)
                        temp_flow_created = True
                    elif serialized_content != flow_content:
                        temp_flow_file = f"temp_{int(time.time())}_{idx}_{current_flow}"
                        target_flow_path = os.path.join(project_root, "mobile_ui_tests", "flows", temp_flow_file)
                        with open(target_flow_path, 'w', encoding='utf-8') as f:
                            f.write(serialized_content)
                        temp_flow_created = True
                except Exception as e:
                    socketio.emit('mobile_ui_test_log', {'line': f'⚠️ Warning: Failed to preprocess {current_flow} ({str(e)}). Running original...'})
                
                try:
                    for log_line in execute_flow_generator(target_flow_path, device_id, apk_path, api_key, cloud_model, cloud_os, project_id=project_id, on_process_spawned=register_process):
                        current_flow_log_lines.append(log_line)
                        if log_line.startswith("🔗 LINK: "):
                            socketio.emit('mobile_ui_test_log', {'line': log_line})
                        else:
                            socketio.emit('mobile_ui_test_log', {'line': f'[{current_flow}] {log_line}'})
                except Exception as fe:
                    current_flow_log_lines.append(f"❌ Execution Error: {str(fe)}")
                    socketio.emit('mobile_ui_test_log', {'line': f'❌ Execution Error on {current_flow}: {str(fe)}'})
                finally:
                    if temp_flow_created and os.path.exists(target_flow_path):
                        try:
                            os.remove(target_flow_path)
                            temp_dir = os.path.dirname(target_flow_path)
                            if os.path.basename(temp_dir).startswith("temp_workspace_"):
                                os.rmdir(temp_dir)
                        except Exception:
                            pass
                            
                current_duration = time.time() - current_flow_start_time
                flow_results.append({
                    "flow_name": current_flow,
                    "flow_path": current_flow_path,
                    "log_lines": current_flow_log_lines,
                    "duration_sec": current_duration
                })
                
            total_duration_sec = time.time() - start_time
            socketio.emit('mobile_ui_test_log', {'line': '📊 Compiling final functional test report...'})
            
            try:
                from mobile_ui_tests.report_compiler import generate_aggregated_mobile_reports, generate_mobile_reports
                if is_multi_run:
                    report_files = generate_aggregated_mobile_reports(flow_results, device_id, total_duration_sec)
                else:
                    res = flow_results[0]
                    report_files = generate_mobile_reports(res["flow_path"], device_id, res["log_lines"], res["duration_sec"])
                socketio.emit('mobile_ui_test_log', {'line': f'🎉 Report compiled: {report_files["docx_name"]}'})
                socketio.emit('mobile_ui_test_log', {'line': f'📂 Saved to: mobile_reports/'})
            except Exception as re:
                socketio.emit('mobile_ui_test_log', {'line': f'⚠️ Report Compilation Error: {str(re)}'})
                
        except Exception as e:
            socketio.emit('mobile_ui_test_log', {'line': f'❌ Background Execution Error: {str(e)}'})
        finally:
            global active_mobile_process
            active_mobile_process = None
            is_mobile_test_running = False
            socketio.emit('mobile_ui_test_status', {'status': 'idle'})
            
    threading.Thread(target=run_in_background, daemon=True).start()
    return jsonify({'message': 'Mobile UI test started successfully!'}), 200

@api_bp.route('/mobile/stop', methods=['POST'])
@token_required
@roles_accepted('Admin', 'Operator')
def stop_mobile_test():
    global active_mobile_process, is_mobile_test_running
    
    if not is_mobile_test_running and not active_mobile_process:
        return jsonify({'message': 'No mobile UI test is running!'}), 400
        
    try:
        if active_mobile_process:
            import sys
            import subprocess as subp
            if sys.platform == "win32":
                subp.run(["taskkill", "/F", "/T", "/PID", str(active_mobile_process.pid)], capture_output=True)
            else:
                active_mobile_process.terminate()
            
            from app import socketio
            socketio.emit('mobile_ui_test_log', {'line': '⏹️ Test manually stopped by operator.'})
            
        active_mobile_process = None
        is_mobile_test_running = False
        
        from app import socketio
        socketio.emit('mobile_ui_test_status', {'status': 'idle'})
        
        return jsonify({'message': 'Mobile UI test stopped successfully.'})
    except Exception as e:
        return jsonify({'message': f'Failed to stop mobile UI test: {str(e)}'}), 500

# --- Mobile UI Test Reports API Routes ---

@api_bp.route('/mobile/reports', methods=['GET'])
@token_required
def list_mobile_reports():
    import datetime
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(project_root, "mobile_reports")
    if not os.path.exists(reports_dir):
        return jsonify({'reports': []}), 200
        
    try:
        files = []
        for f in os.listdir(reports_dir):
            if f.endswith('.docx') or f.endswith('.md'):
                filepath = os.path.join(reports_dir, f)
                stat = os.stat(filepath)
                created_time = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                files.append({
                    'filename': f,
                    'size': f"{stat.st_size / 1024:.1f} KB",
                    'created_at': created_time
                })
        # Sort by creation date descending
        files.sort(key=lambda x: x['created_at'], reverse=True)
        return jsonify({'reports': files}), 200
    except Exception as e:
        return jsonify({'message': f'Failed to list reports: {str(e)}'}), 500

@api_bp.route('/mobile/reports/download/<filename>', methods=['GET'])
@token_required
def download_mobile_report(filename):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(project_root, "mobile_reports")
    filepath = os.path.join(reports_dir, filename)
    
    if not os.path.abspath(filepath).startswith(os.path.abspath(reports_dir)):
        return jsonify({'message': 'Access denied'}), 403
        
    if not os.path.exists(filepath):
        return jsonify({'message': 'Report file not found'}), 404
        
    from flask import send_file
    return send_file(filepath, as_attachment=True)


# --- Web UI E2E Test Suite Routes ---

is_web_test_running = False
active_web_process = None

@api_bp.route('/web/run', methods=['POST'])
@token_required
def run_web_test():
    global is_web_test_running, active_web_process
    
    if is_web_test_running:
        return jsonify({'message': 'A web UI test is already running!'}), 400
        
    data = request.get_json() or {}
    url = data.get('url', 'http://localhost:3000')
    email = data.get('email', '')
    password = data.get('password', '')
    room = data.get('room', 'playwright-test-room')
    features = data.get('features', 'signup,login,dashboard,join,mic,cam,chat,handraise,panels,leave')
    headed = data.get('headed', False)
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Create web_reports directory
    reports_dir = os.path.join(project_root, "web_reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    report_json_path = os.path.join(reports_dir, "temp_report.json")
    
    from app.runner import get_python_executable
    py_exec = get_python_executable(project_root)
    bot_script = os.path.join(project_root, "app", "web_ui_test_bot.py")
    
    cmd = [
        py_exec, bot_script,
        "--url", url,
        "--email", email,
        "--password", password,
        "--room", room,
        "--features", features,
        "--report-json", report_json_path
    ]
    if headed:
        cmd.append("--headed")
        
    from app import socketio
    
    def run_in_background():
        global is_web_test_running, active_web_process
        is_web_test_running = True
        
        socketio.emit('web_ui_test_status', {'status': 'running'})
        socketio.emit('web_ui_test_log', {'line': '🚀 Spawning Playwright E2E Web UI test runner...'})
        
        import subprocess as subp
        import threading
        
        try:
            # Run in a process group to allow termination
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subp.CREATE_NEW_PROCESS_GROUP
                
            active_web_process = subp.Popen(
                cmd,
                stdout=subp.PIPE,
                stderr=subp.PIPE,
                text=True,
                bufsize=1,
                creationflags=creation_flags
            )
            
            log_lines = []
            
            # Helper to read stdout in a thread to prevent blocking
            def read_stdout(proc):
                for line in proc.stdout:
                    line_str = line.strip()
                    if line_str.startswith("[LOG] "):
                        log_msg = line_str[6:]
                        log_lines.append(log_msg)
                        socketio.emit('web_ui_test_log', {'line': log_msg})
                    elif line_str.startswith("[FRAME] "):
                        frame_data = line_str[8:]
                        socketio.emit('web_ui_test_frame', {'image': frame_data})
                        
            # Helper to read stderr in a thread
            def read_stderr(proc):
                for line in proc.stderr:
                    line_str = line.strip()
                    socketio.emit('web_ui_test_log', {'line': f"[STDERR] {line_str}"})
                    log_lines.append(f"[STDERR] {line_str}")
                    
            t1 = threading.Thread(target=read_stdout, args=(active_web_process,), daemon=True)
            t2 = threading.Thread(target=read_stderr, args=(active_web_process,), daemon=True)
            t1.start()
            t2.start()
            
            # Wait for execution to finish
            active_web_process.wait()
            
            t1.join(timeout=2.0)
            t2.join(timeout=2.0)
            
            if active_web_process.returncode == 0:
                socketio.emit('web_ui_test_log', {'line': '🎉 Playwright bot completed E2E flow successfully.'})
            else:
                socketio.emit('web_ui_test_log', {'line': f'❌ Playwright bot exited with code {active_web_process.returncode}.'})
                
            # Compile report HTML
            socketio.emit('web_ui_test_log', {'line': '📊 Generating E2E test report...'})
            from app.web_report_compiler import generate_web_report
            report_name = generate_web_report(report_json_path, log_lines, reports_dir)
            
            # Cleanup temp JSON file
            if os.path.exists(report_json_path):
                try:
                    os.remove(report_json_path)
                except Exception:
                    pass
                    
            socketio.emit('web_ui_test_log', {'line': f'🎉 Compiled HTML Report: {report_name}'})
            
        except Exception as e:
            socketio.emit('web_ui_test_log', {'line': f'❌ Web UI test failed to execute: {str(e)}'})
        finally:
            active_web_process = None
            is_web_test_running = False
            socketio.emit('web_ui_test_status', {'status': 'idle'})
            
    threading.Thread(target=run_in_background, daemon=True).start()
    return jsonify({'message': 'Web UI E2E test started successfully!'}), 200

@api_bp.route('/web/stop', methods=['POST'])
@token_required
@roles_accepted('Admin', 'Operator')
def stop_web_test():
    global active_web_process, is_web_test_running
    
    if not is_web_test_running and not active_web_process:
        return jsonify({'message': 'No web UI test is running!'}), 400
        
    try:
        if active_web_process:
            import sys
            import subprocess as subp
            if sys.platform == "win32":
                subp.run(["taskkill", "/F", "/T", "/PID", str(active_web_process.pid)], capture_output=True)
            else:
                active_web_process.terminate()
                
            from app import socketio
            socketio.emit('web_ui_test_log', {'line': '⏹️ Test manually stopped by operator.'})
            
        active_web_process = None
        is_web_test_running = False
        
        from app import socketio
        socketio.emit('web_ui_test_status', {'status': 'idle'})
        return jsonify({'message': 'Web UI test stopped successfully.'})
    except Exception as e:
        return jsonify({'message': f'Failed to stop web UI test: {str(e)}'}), 500

@api_bp.route('/web/reports', methods=['GET'])
@token_required
def list_web_reports():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(project_root, "web_reports")
    if not os.path.exists(reports_dir):
        return jsonify({'reports': []}), 200
        
    try:
        files = []
        for f in os.listdir(reports_dir):
            if f.endswith('.html'):
                filepath = os.path.join(reports_dir, f)
                stat = os.stat(filepath)
                created_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                
                # Check if matching video file exists
                timestamp_str = f.replace("web_e2e_report_", "").replace(".html", "")
                video_filename = f"web_video_{timestamp_str}.webm"
                video_path = os.path.join(reports_dir, "videos", video_filename)
                has_video = os.path.exists(video_path)
                
                files.append({
                    'filename': f,
                    'size': f"{stat.st_size / 1024:.1f} KB",
                    'created_at': created_time,
                    'video_file': video_filename if has_video else None
                })
        # Sort by creation date descending
        files.sort(key=lambda x: x['created_at'], reverse=True)
        return jsonify({'reports': files}), 200
    except Exception as e:
        return jsonify({'message': f'Failed to list reports: {str(e)}'}), 500

@api_bp.route('/web/reports/download/<filename>', methods=['GET'])
@token_required
def download_web_report(filename):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(project_root, "web_reports")
    filepath = os.path.join(reports_dir, filename)
    
    if not os.path.abspath(filepath).startswith(os.path.abspath(reports_dir)):
        return jsonify({'message': 'Access denied'}), 403
        
    if not os.path.exists(filepath):
        return jsonify({'message': 'Report file not found'}), 404
        
    from flask import send_file
    return send_file(filepath, as_attachment=True)

@api_bp.route('/web/videos/<filename>', methods=['GET'])
def stream_web_video(filename):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    videos_dir = os.path.join(project_root, "web_reports", "videos")
    filepath = os.path.join(videos_dir, filename)
    
    if not os.path.abspath(filepath).startswith(os.path.abspath(videos_dir)):
        return jsonify({'message': 'Access denied'}), 403
        
    if not os.path.exists(filepath):
        return jsonify({'message': 'Video file not found'}), 404
        
    from flask import send_file
    return send_file(filepath, mimetype='video/webm')



# --- Cluster Scaling & Telemetry API Routes ---

@api_bp.route('/cluster/register', methods=['POST'])
def register_worker_node():
    data = request.get_json() or {}
    ip = data.get('ip_address')
    status = data.get('status', 'idle')
    
    if not ip:
        return jsonify({'message': 'Missing ip_address'}), 400
        
    from app.models import WorkerNode
    node = WorkerNode.query.filter_by(ip_address=ip).first()
    if not node:
        node = WorkerNode(ip_address=ip)
        db.session.add(node)
        
    node.status = status
    node.last_seen = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'message': 'Worker node registered successfully', 'node': node.to_dict()}), 200

@api_bp.route('/sessions/<int:session_id>/upload_chunk', methods=['POST'])
def upload_session_log_chunk(session_id):
    session = TestSession.query.get_or_404(session_id)
    
    # 1. Save uploaded jsonl chunk file
    if 'file' not in request.files:
        return jsonify({'message': 'No file part in the request'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'message': 'No selected file'}), 400
        
    session_dir = get_session_dir(current_app.root_path, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    chunk_filename = f"report_log_chunk_{session.uploaded_workers_count + 1}.jsonl"
    chunk_path = os.path.join(session_dir, chunk_filename)
    file.save(chunk_path)
    
    # 2. Save uploaded summary json if present
    summary_file = request.files.get('summary')
    if summary_file:
        summary_filename = f"summary_chunk_{session.uploaded_workers_count + 1}.json"
        summary_path = os.path.join(session_dir, summary_filename)
        summary_file.save(summary_path)
        
    # Increment counts
    session.uploaded_workers_count += 1
    db.session.commit()
    # Check if all expected chunks have uploaded
    expected = session.total_expected_workers or 1
    all_uploaded = session.uploaded_workers_count >= expected
    
    from app import socketio
    socketio.emit('cluster_status_changed', {
        'session_id': session_id,
        'uploaded_workers_count': session.uploaded_workers_count,
        'total_expected_workers': expected,
        'all_uploaded': all_uploaded
    })
    
    # If all uploaded, trigger background compile/merger asynchronously
    if all_uploaded and session.status in ['completed', 'stopped']:
        from app.runner import compile_report_log_async
        compile_report_log_async(current_app.root_path, session_id, socketio)
        
    return jsonify({
        'message': f'Chunk {session.uploaded_workers_count} uploaded successfully',
        'all_uploaded': all_uploaded
    }), 200

@api_bp.route('/sessions/<int:session_id>/cluster_batches', methods=['GET'])
def get_session_cluster_batches(session_id):
    import json
    session = TestSession.query.get_or_404(session_id)
    config = session.config
    
    if not config:
        return jsonify([]), 200
        
    total_bots = config.bots
    batch_size = 500
    expected_workers = session.total_expected_workers
    if expected_workers <= 1:
        expected_workers = max(1, (total_bots + batch_size - 1) // batch_size)
    
    batches = []
    for i in range(expected_workers):
        start_id = config.start_id + (i * batch_size)
        end_id = min(start_id + batch_size - 1, config.start_id + total_bots - 1)
        
        session_dir = get_session_dir(current_app.root_path, session_id)
        summary_path = os.path.join(session_dir, f"summary_chunk_{i + 1}.json")
        has_summary = os.path.exists(summary_path)
        
        joined_count = 0
        failed_count = 0
        status = "pending"
        
        if has_summary:
            try:
                with open(summary_path, 'r') as f:
                    summary = json.load(f)
                joined_count = summary.get('success_joins', batch_size)
                failed_count = summary.get('failures_count', 0)
                status = "completed"
            except Exception:
                status = "completed"
        elif session.status == 'running':
            status = "running"
            from app.runner import RUNNING_SESSIONS, RUNNING_SESSIONS_LOCK
            with RUNNING_SESSIONS_LOCK:
                sess_info = RUNNING_SESSIONS.get(session_id)
                if sess_info and "live_batches" in sess_info and i in sess_info["live_batches"]:
                    joined_count = sess_info["live_batches"][i]["joined"]
                    failed_count = sess_info["live_batches"][i]["failed"]
                else:
                    joined_count = 0
                    failed_count = 0
            
        batches.append({
            "batch_id": f"Batch-{i+1:02d}",
            "worker_ip": f"192.168.1.{100 + i}",
            "bot_range": f"{start_id} - {end_id}",
            "joined": joined_count,
            "failed": failed_count,
            "uploaded": "Yes" if has_summary else "No",
            "status": status
        })
        
    return jsonify(batches), 200


# Global target server stats cache
latest_server_telemetry = {
    'cpu_usage': 0.0,
    'ram_usage': 0.0,
    'timestamp': None
}

@api_bp.route('/server/telemetry', methods=['POST'])
def receive_server_telemetry():
    global latest_server_telemetry
    data = request.get_json() or {}
    
    cpu = float(data.get('cpu_usage', 0.0))
    ram = float(data.get('ram_usage', 0.0))
    
    latest_server_telemetry = {
        'cpu_usage': cpu,
        'ram_usage': ram,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    from app import socketio
    socketio.emit('server_telemetry', latest_server_telemetry)
    
    return jsonify({'message': 'Server telemetry received successfully'}), 200


# =====================================================================
# AI Developer Advisory & Release Governance Routes (Volume 7)
# =====================================================================

@api_bp.route('/settings/ai', methods=['GET'])
@token_required
def get_ai_settings():
    from ai_advisor import load_ai_settings
    settings = load_ai_settings()
    
    def mask_key(k):
        if not k or len(k) < 10:
            return ""
        return k[:7] + "..." + k[-4:]
        
    return jsonify({
        "gemini_api_key_masked": mask_key(settings.get("gemini_api_key", "")),
        "openai_api_key_masked": mask_key(settings.get("openai_api_key", "")),
        "has_gemini_key": bool(settings.get("gemini_api_key")),
        "has_openai_key": bool(settings.get("openai_api_key")),
        "primary_model": settings.get("primary_model", "openai"),
        "gemini_model_name": settings.get("gemini_model_name", "gemini-2.5-flash"),
        "openai_model_name": settings.get("openai_model_name", "gpt-4o-mini"),
        "enable_ai_analysis": settings.get("enable_ai_analysis", True)
    })


@api_bp.route('/settings/ai', methods=['POST'])
@token_required
@roles_accepted('Admin', 'Operator')
def update_ai_settings():
    from ai_advisor import load_ai_settings, save_ai_settings
    data = request.get_json() or {}
    current = load_ai_settings()
    
    # Update keys only if provided non-empty
    if data.get("gemini_api_key"):
        current["gemini_api_key"] = data["gemini_api_key"].strip()
    if data.get("openai_api_key"):
        current["openai_api_key"] = data["openai_api_key"].strip()
    if "primary_model" in data:
        current["primary_model"] = data["primary_model"].lower()
    if "gemini_model_name" in data:
        current["gemini_model_name"] = data["gemini_model_name"].strip()
    if "openai_model_name" in data:
        current["openai_model_name"] = data["openai_model_name"].strip()
    if "enable_ai_analysis" in data:
        current["enable_ai_analysis"] = bool(data["enable_ai_analysis"])
        
    success = save_ai_settings(current)
    if success:
        return jsonify({"message": "AI configuration updated successfully!"}), 200
    return jsonify({"message": "Failed to save AI configuration."}), 500


@api_bp.route('/settings/ai/test', methods=['POST'])
@token_required
def test_ai_connection():
    from ai_advisor import analyze_session
    import time
    t0 = time.time()
    # Run a lightweight mock telemetry test
    mock_dataset = {
        "session_id": "test-ping",
        "name": "Connectivity Diagnostics Check",
        "total_bots": 5,
        "duration_str": "1m 00s",
        "config": {"room": "diagnostics", "webrtc_enabled": True},
        "global_latencies": {"avg_ack": 120.0, "p95_ack": 180.0},
        "webrtc_performance": {"packet_loss": 0.05, "avg_jitter": 10.0},
        "websocket_disconnects": 0,
        "reconnection_count": 0
    }
    result = analyze_session(mock_dataset)
    latency_ms = int((time.time() - t0) * 1000)
    attribution = result.get("attribution", {})
    return jsonify({
        "status": "success",
        "model_used": attribution.get("model_used", "Unknown"),
        "latency_ms": latency_ms,
        "verdict": result.get("go_no_go_verdict", "PASS"),
        "summary": result.get("executive_summary", "")[:200]
    }), 200


@api_bp.route('/sessions/compare', methods=['POST'])
@token_required
def compare_sessions():
    """
    Compares two test sessions using the AI Comparison & Progression Engine.
    Evaluates deltas in latency, WebRTC loss, throughput, regressions, and improvements.
    """
    from ai_advisor import compare_sessions_ai
    import json
    
    data = request.get_json() or {}
    session_id_1 = data.get("session_id_1") or data.get("session_a_id")
    session_id_2 = data.get("session_id_2") or data.get("session_b_id")
    
    if not session_id_1 or not session_id_2:
        return jsonify({"message": "Both session_id_1 and session_id_2 are required for comparison."}), 400
        
    s1 = TestSession.query.get_or_404(session_id_1)
    s2 = TestSession.query.get_or_404(session_id_2)
    
    def extract_session_dataset(session):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        session_dir = get_session_dir(session.id)
        
        # Check if full aggregated report json exists
        report_json_path = os.path.join(session_dir, "session_report_data.json")
        if not os.path.exists(report_json_path):
            report_json_path = os.path.join(project_root, "_report_data.json")
            
        data_dict = {}
        if os.path.exists(report_json_path):
            try:
                with open(report_json_path, "r", encoding="utf-8") as f:
                    data_dict = json.load(f)
            except Exception:
                pass
                
        # Fill in database defaults and live metrics if missing
        cfg = session.config.to_dict() if session.config else {}
        if not data_dict:
            dur = session.accumulated_duration or 0
            
            # Query real aggregate telemetry from SessionMetric table
            from app.models import SessionMetric
            avg_lat = db.session.query(db.func.avg(SessionMetric.avg_latency)).filter(SessionMetric.session_id == session.id, SessionMetric.avg_latency > 0).scalar() or 0.0
            avg_loss = db.session.query(db.func.avg(SessionMetric.packet_loss)).filter(SessionMetric.session_id == session.id, SessionMetric.packet_loss > 0).scalar() or 0.0
            avg_jitter = db.session.query(db.func.avg(SessionMetric.jitter)).filter(SessionMetric.session_id == session.id, SessionMetric.jitter > 0).scalar() or 0.0
            max_bots = db.session.query(db.func.max(SessionMetric.connected_bots)).filter(SessionMetric.session_id == session.id).scalar() or cfg.get("bots", 0)
            failed_bots = db.session.query(db.func.max(SessionMetric.failed_bots)).filter(SessionMetric.session_id == session.id).scalar() or 0
            
            data_dict = {
                "session_id": session.id,
                "name": session.name,
                "total_bots": max_bots or cfg.get("bots", 50),
                "duration_str": f"{dur // 60}m {dur % 60}s" if dur > 0 else "N/A",
                "config": cfg,
                "global_latencies": {"avg_ack": round(float(avg_lat), 1), "p95_ack": round(float(avg_lat * 1.35), 1)},
                "webrtc_performance": {
                    "aggregate": {
                        "avg_rtt": round(float(avg_lat), 1),
                        "avg_jitter": round(float(avg_jitter), 1),
                        "avg_loss_pct": round(float(avg_loss), 2),
                        "avg_packet_loss": round(float(avg_loss), 2),
                        "avg_bitrate": 0.0
                    }
                },
                "websocket_disconnects": failed_bots,
                "reconnection_count": 0
            }
        else:
            data_dict["session_id"] = session.id
            data_dict["name"] = session.name
            
        return data_dict

    session_a_data = extract_session_dataset(s1)
    session_b_data = extract_session_dataset(s2)
    
    comparison_result = compare_sessions_ai(session_a_data, session_b_data)
    comparison_result["session_a_id"] = s1.id
    comparison_result["session_b_id"] = s2.id
    comparison_result["session_a_name"] = s1.name
    comparison_result["session_b_name"] = s2.name
    comparison_result["session_a_duration"] = session_a_data.get("duration_str", "N/A")
    comparison_result["session_b_duration"] = session_b_data.get("duration_str", "N/A")
    
    # Map frontend convenience fields
    comparison_result["progression_summary"] = (
        comparison_result.get("summary_headline") or 
        comparison_result.get("ai_narrative") or 
        f"Trajectory Verdict: {comparison_result.get('trajectory_verdict')}"
    )
    comparison_result["improvements"] = comparison_result.get("fixed_issues", [])
    comparison_result["regressions"] = comparison_result.get("new_regressions", [])
    guidance = comparison_result.get("next_sprint_guidance")
    comparison_result["recommendations"] = [guidance] if isinstance(guidance, str) else (guidance or [])
    
    mc = comparison_result.get("metrics_comparison", {})
    comparison_result["metrics_delta"] = {
        "success_rate_delta_pct": float(mc.get("success_rate", {}).get("delta", 0.0) if "success_rate" in mc else 0.0),
        "avg_latency_delta_ms": float(mc.get("avg_ack_latency_ms", {}).get("delta_ms", 0.0)),
        "packet_loss_delta_pct": float(mc.get("webrtc_packet_loss_pct", {}).get("delta", 0.0)),
        "jitter_delta_ms": float(mc.get("jitter", {}).get("delta", 0.0) if "jitter" in mc else 0.0),
        "websocket_drops_delta": int(mc.get("websocket_drops", {}).get("delta", 0))
    }
    comparison_result["attribution"] = {
        "model_used": comparison_result.get("engine_attribution", "Dual-Model AI Engine")
    }
    
    return jsonify(comparison_result), 200


