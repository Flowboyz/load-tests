import os
import csv
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


# --- Logs & Performance Historical Data Routes ---

@api_bp.route('/sessions/<int:session_id>/logs', methods=['GET'])
@token_required
def get_session_logs(session_id):
    session = TestSession.query.get_or_404(session_id)
    session_dir = get_session_dir(session_id)
    log_path = os.path.join(session_dir, "report_log.jsonl")
    
    if not os.path.exists(log_path):
        return jsonify([])
        
    logs = []
    limit = request.args.get('limit', 200, type=int)
    search_query = request.args.get('search', '', type=str).lower()
    
    import json
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                evt = json.loads(line.strip())
                # Format a friendly text representation for human reading
                ts = evt.get("ts", "")
                etype = evt.get("event", "")
                bot_id = evt.get("bot_id")
                name = evt.get("name")
                
                # Basic string filtering
                raw_str = line.lower()
                if search_query and search_query not in raw_str:
                    continue
                    
                logs.append(evt)
            except Exception:
                pass
                
    return jsonify(logs[-limit:])

@api_bp.route('/sessions/<int:session_id>/metrics', methods=['GET'])
@token_required
def get_session_metrics(session_id):
    metrics = SessionMetric.query.filter_by(session_id=session_id).order_by(SessionMetric.timestamp.asc()).all()
    return jsonify([m.to_dict() for m in metrics])


# --- Report Download Routes ---

@api_bp.route('/sessions/<int:session_id>/download/<string:fmt>', methods=['GET'])
@token_required
def download_report(session_id, fmt):
    session = TestSession.query.get_or_404(session_id)
    fmt = fmt.lower()
    
    session_dir = get_session_dir(session_id)
    log_path = os.path.join(session_dir, "report_log.jsonl")
    
    docx_path = os.path.join(session_dir, "report.docx")
    if not os.path.exists(docx_path):
        alt_docx = os.path.join(session_dir, f"session_{session_id}_report.docx")
        if os.path.exists(alt_docx):
            docx_path = alt_docx
            
    pdf_path = os.path.join(session_dir, "report.pdf")
    if not os.path.exists(pdf_path):
        alt_pdf = os.path.join(session_dir, f"session_{session_id}_report.pdf")
        if os.path.exists(alt_pdf):
            pdf_path = alt_pdf
            
    csv_path = os.path.join(session_dir, "session_action_lifecycle.csv")
    
    # Check for chunk log files if main log file doesn't exist
    import glob
    import json
    base_name = os.path.basename(log_path).replace(".jsonl", "")
    chunk_files = glob.glob(os.path.join(session_dir, f"{base_name}_chunk_*.jsonl"))
    
    if not os.path.exists(log_path) and chunk_files:
        try:
            # Sort chunk files sequentially
            chunk_files = sorted(
                chunk_files,
                key=lambda x: int(os.path.basename(x).split("_")[-1].replace(".jsonl", ""))
            )
            
            test_start_time = session.started_at.isoformat() + "Z" if session.started_at else datetime.utcnow().isoformat() + "Z"
            
            with open(log_path, "w", encoding="utf-8") as main_f:
                # Write standard test_started header
                main_f.write(json.dumps({
                    "event": "test_started",
                    "ts": test_start_time
                }) + "\n")
                
                # Stream chunk contents sequentially into main file
                for chunk_file in chunk_files:
                    with open(chunk_file, "r", encoding="utf-8") as chunk_f:
                        for line in chunk_f:
                            if "test_started" in line:
                                continue
                            main_f.write(line)
            
            # Clean up chunks after successful merge to conserve space
            for chunk_file in chunk_files:
                try:
                    os.remove(chunk_file)
                except Exception:
                    pass
        except Exception as e:
            print(f"Error merging chunk logs on download: {e}")

    if not os.path.exists(log_path) and not os.path.exists(docx_path) and not os.path.exists(pdf_path) and not os.path.exists(csv_path):
        return jsonify({'message': 'No logs or report documents found for this session. The test may have failed to start or write telemetry.'}), 400

    if fmt == 'json':
        if not os.path.exists(log_path):
            return jsonify({'message': 'JSON log file not found!'}), 404
        return Response(
            stream_file_in_chunks(log_path),
            mimetype='application/jsonl',
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_logs.jsonl",
                "Content-Length": os.path.getsize(log_path)
            }
        )
        
    elif fmt == 'csv':
        if not os.path.exists(csv_path):
            from app.runner import compile_report_log_async
            from app import socketio
            compile_report_log_async(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), session_id, socketio)
            return jsonify({'message': 'Report is generating in the background. Please wait...', 'status': 'compiling'}), 202
            
        return Response(
            stream_file_in_chunks(csv_path),
            mimetype='text/csv',
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_action_log.csv",
                "Content-Length": os.path.getsize(csv_path)
            }
        )
        
    elif fmt == 'docx':
        if not os.path.exists(docx_path):
            from app.runner import compile_report_log_async
            from app import socketio
            compile_report_log_async(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), session_id, socketio)
            return jsonify({'message': 'Report is generating in the background. Please wait...', 'status': 'compiling'}), 202
            
        return Response(
            stream_file_in_chunks(docx_path),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_report.docx",
                "Content-Length": os.path.getsize(docx_path)
            }
        )
        
    elif fmt == 'pdf':
        if not os.path.exists(pdf_path):
            from app.runner import compile_report_log_async
            from app import socketio
            compile_report_log_async(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), session_id, socketio)
            return jsonify({'message': 'Report is generating in the background. Please wait...', 'status': 'compiling'}), 202
            
        return Response(
            stream_file_in_chunks(pdf_path),
            mimetype='application/pdf',
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_report.pdf",
                "Content-Length": os.path.getsize(pdf_path)
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
        files = [f for f in os.listdir(flows_dir) if f.endswith('.yaml') or f.endswith('.yml')]
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
    room_slug = data.get('room_slug')
    cloud_model = data.get('cloud_model')
    cloud_os = data.get('cloud_os')
    
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

    if not os.path.exists(flow_path):
        return jsonify({'message': f'Flow file not found: {flow_file}'}), 404

    from app import socketio
    import threading
    from mobile_ui_tests.run_test import execute_flow_generator
    
    def run_in_background():
        global is_mobile_test_running
        is_mobile_test_running = True
        import time
        start_time = time.time()
        log_lines = []
        
        target_flow_path = flow_path
        temp_flow_created = False
        
        if room_slug or app_id:
            try:
                with open(flow_path, 'r', encoding='utf-8') as f:
                    flow_content = f.read()
                
                serialized_content = flow_content
                
                if room_slug:
                    # Regex replace room slug specifically following the 'Join' and 'general-meeting' taps
                    import re
                    pattern = r'(tapOn:\s*["\']?Join["\']?\s*\n\s*-\s*tapOn:\s*["\']?e\.g\.\s*general-meeting["\']?\s*\n\s*-\s*inputText:\s*)(["\']?[a-zA-Z0-9_\-]+["\']?)'
                    serialized_content = re.sub(pattern, rf'\g<1>"{room_slug}"', serialized_content)
                
                if app_id:
                    # Regex replace the appId key at the top of the YAML file
                    import re
                    serialized_content = re.sub(r'^appId:\s*.*', f'appId: {app_id}', serialized_content, flags=re.MULTILINE)
                
                if serialized_content != flow_content:
                    temp_flow_file = f"temp_{int(time.time())}_{flow_file}"
                    target_flow_path = os.path.join(project_root, "mobile_ui_tests", "flows", temp_flow_file)
                    with open(target_flow_path, 'w', encoding='utf-8') as f:
                        f.write(serialized_content)
                    temp_flow_created = True
            except Exception as e:
                socketio.emit('mobile_ui_test_log', {'line': f'⚠️ Warning: Failed to preprocess flow ({str(e)}). Running original flow...'})
                
        try:
            socketio.emit('mobile_ui_test_status', {'status': 'running'})
            for log_line in execute_flow_generator(target_flow_path, device_id, apk_path, api_key, cloud_model, cloud_os):
                log_lines.append(log_line)
                socketio.emit('mobile_ui_test_log', {'line': log_line})
                
            duration_sec = time.time() - start_time
            socketio.emit('mobile_ui_test_log', {'line': '📊 Compiling final functional test report...'})
            
            try:
                from mobile_ui_tests.report_compiler import generate_mobile_reports
                report_files = generate_mobile_reports(flow_path, device_id, log_lines, duration_sec)
                socketio.emit('mobile_ui_test_log', {'line': f'🎉 Report compiled: {report_files["docx_name"]}'})
                socketio.emit('mobile_ui_test_log', {'line': f'📂 Saved to: mobile_reports/'})
            except Exception as re:
                socketio.emit('mobile_ui_test_log', {'line': f'⚠️ Report Compilation Error: {str(re)}'})
                
        except Exception as e:
            socketio.emit('mobile_ui_test_log', {'line': f'❌ Background Execution Error: {str(e)}'})
        finally:
            if temp_flow_created and os.path.exists(target_flow_path):
                try:
                    os.remove(target_flow_path)
                except:
                    pass
            is_mobile_test_running = False
            socketio.emit('mobile_ui_test_status', {'status': 'idle'})
            
    threading.Thread(target=run_in_background, daemon=True).start()
    return jsonify({'message': 'Mobile UI test started successfully!'}), 200

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
    
    # Secure file access path validation
    if not os.path.abspath(filepath).startswith(os.path.abspath(reports_dir)):
        return jsonify({'message': 'Access denied'}), 403
        
    if not os.path.exists(filepath):
        return jsonify({'message': 'Report file not found'}), 404
        
    from flask import send_file
    return send_file(filepath, as_attachment=True)

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

