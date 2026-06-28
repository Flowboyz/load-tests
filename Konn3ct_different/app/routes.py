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
        db.session.commit()
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
        db.session.commit()
        return jsonify({'message': 'Test session resumed.'})
    return jsonify({'message': 'Failed to resume test session.'}), 500

@api_bp.route('/sessions/<int:session_id>/stop', methods=['POST'])
@token_required
@roles_accepted('Admin', 'Operator')
def stop_test(session_id):
    session = TestSession.query.get_or_404(session_id)
    if session.status not in ("running", "paused"):
        return jsonify({'message': 'Session is not active!'}), 400
        
    success = stop_session(session_id)
    
    session.status = "stopped"
    session.ended_at = datetime.utcnow()
    db.session.commit()
    
    from flask import current_app
    socketio = current_app.extensions.get('socketio')
    if socketio:
        socketio.emit('session_status_changed', {
            'session_id': session_id,
            'status': 'stopped'
        })
        
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
    pdf_path = os.path.join(session_dir, "report.pdf")
    csv_path = os.path.join(session_dir, "session_action_lifecycle.csv")
    
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
            from app.runner import compile_report_log
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            compile_report_log(project_root, log_path, docx_path)
            
        if not os.path.exists(csv_path):
            fallback = os.path.join(session_dir, "session_action_lifecycle.csv")
            if os.path.exists(fallback):
                csv_path = fallback
            else:
                return jsonify({'message': 'CSV report file not found!'}), 404
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
            from app.runner import compile_report_log
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            compile_report_log(project_root, log_path, docx_path)
            
        if not os.path.exists(docx_path):
            return jsonify({'message': 'DOCX report file not found!'}), 404
        return Response(
            stream_file_in_chunks(docx_path),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_report.docx",
                "Content-Length": os.path.getsize(docx_path)
            }
        )
        
    elif fmt == 'pdf':
        if not os.path.exists(docx_path):
            from app.runner import compile_report_log
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            compile_report_log(project_root, log_path, docx_path)
            
        if not os.path.exists(pdf_path):
            from app.runner import convert_docx_to_pdf
            pdf = convert_docx_to_pdf(docx_path, session_dir)
            if pdf and os.path.exists(pdf):
                pdf_path = pdf
                session.report_pdf_path = pdf
                db.session.commit()
                return Response(
                    stream_file_in_chunks(pdf),
                    mimetype='application/pdf',
                    headers={
                        "Content-Disposition": f"attachment; filename=session_{session_id}_report.pdf",
                        "Content-Length": os.path.getsize(pdf)
                    }
                )
            return jsonify({
                'message': (
                    'PDF conversion failed. This feature requires LibreOffice to be installed on the server. '
                    'To enable PDF downloads: on Linux run "sudo apt install libreoffice-nogui", or on Windows '
                    'install LibreOffice (soffice) and ensure it is added to your system PATH or installed in the default location.'
                )
            }), 404
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
