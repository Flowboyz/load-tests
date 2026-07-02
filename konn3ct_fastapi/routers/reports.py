import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User, TestSession
from auth import get_current_user
from services.bot_runner import get_session_dir

router = APIRouter()

def chunk_generator(file_path: str, chunk_size: int = 65536):
    """Streams a file in binary chunks to prevent high memory usage."""
    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    except Exception as e:
        print(f"Error streaming file {file_path}: {e}")

@router.get("/reports")
async def get_reports_list(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Returns a list of completed test sessions containing compiled report assets."""
    sessions = db.query(TestSession).filter(
        TestSession.status.in_(["completed", "stopped", "failed"])
    ).order_by(TestSession.ended_at.desc()).all()
    
    reports = []
    for sess in sessions:
        reports.append({
            "session_id": sess.id,
            "name": sess.name,
            "status": sess.status,
            "started_at": sess.started_at.isoformat() if sess.started_at else None,
            "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
            "downloads": {
                "json": f"/api/sessions/{sess.id}/download/json",
                "csv": f"/api/sessions/{sess.id}/download/csv",
                "docx": f"/api/sessions/{sess.id}/download/docx",
                "pdf": f"/api/sessions/{sess.id}/download/pdf" if sess.report_pdf_path else None
            }
        })
    return reports

@router.get("/api/sessions/{session_id}/download/{fmt}")
async def download_session_report(
    session_id: int,
    fmt: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    session = db.query(TestSession).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found!")
        
    fmt = fmt.lower()
    session_dir = get_session_dir(session_id)
    
    log_path = os.path.join(session_dir, "report_log.jsonl")
    docx_path = os.path.join(session_dir, "report.docx")
    pdf_path = os.path.join(session_dir, "report.pdf")
    csv_path = os.path.join(session_dir, "session_action_lifecycle.csv")
    
    # Compile DOCX & CSV if they don't exist
    if fmt in ("docx", "pdf", "csv"):
        if not os.path.exists(docx_path) or not os.path.exists(csv_path):
            from services.reports import compile_docx_report
            compile_docx_report(log_path, docx_path)
            
    if fmt == 'json':
        if not os.path.exists(log_path):
            raise HTTPException(status_code=404, detail="JSON log file not found!")
        headers = {
            "Content-Disposition": f"attachment; filename=session_{session_id}_logs.jsonl",
            "Content-Length": str(os.path.getsize(log_path))
        }
        return StreamingResponse(chunk_generator(log_path), media_type="application/jsonl", headers=headers)
        
    elif fmt == 'csv':
        if not os.path.exists(csv_path):
            # Fallback path check
            fallback = os.path.join(session_dir, "session_action_lifecycle.csv")
            if os.path.exists(fallback):
                csv_path = fallback
            else:
                raise HTTPException(status_code=404, detail="CSV report file not found!")
        headers = {
            "Content-Disposition": f"attachment; filename=session_{session_id}_action_log.csv",
            "Content-Length": str(os.path.getsize(csv_path))
        }
        return StreamingResponse(chunk_generator(csv_path), media_type="text/csv", headers=headers)
        
    elif fmt == 'docx':
        if not os.path.exists(docx_path):
            raise HTTPException(status_code=404, detail="DOCX report file not found!")
        headers = {
            "Content-Disposition": f"attachment; filename=session_{session_id}_report.docx",
            "Content-Length": str(os.path.getsize(docx_path))
        }
        return StreamingResponse(
            chunk_generator(docx_path),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers
        )
        
    elif fmt == 'pdf':
        if not os.path.exists(pdf_path):
            from services.reports import convert_docx_to_pdf
            pdf = convert_docx_to_pdf(docx_path, session_dir)
            if pdf and os.path.exists(pdf):
                pdf_path = pdf
                session.report_pdf_path = pdf
                db.commit()
            else:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "PDF conversion failed. This feature requires LibreOffice to be installed on the server. "
                        "To enable PDF downloads: on Linux run 'sudo apt install libreoffice-nogui', or on Windows "
                        "install LibreOffice (soffice) and ensure it is in your system PATH."
                    )
                )
        headers = {
            "Content-Disposition": f"attachment; filename=session_{session_id}_report.pdf",
            "Content-Length": str(os.path.getsize(pdf_path))
        }
        return StreamingResponse(chunk_generator(pdf_path), media_type="application/pdf", headers=headers)
        
    else:
        raise HTTPException(status_code=400, detail="Invalid download format! Must be JSON, CSV, DOCX, or PDF.")
