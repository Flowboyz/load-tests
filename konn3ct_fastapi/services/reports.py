import os
import sys
import shutil
import subprocess

def find_libreoffice() -> str:
    """Checks the system PATH and common installation directories for LibreOffice (soffice)."""
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

def compile_docx_report(log_path: str, docx_path: str):
    """Executes the generate_report.py script to compile report from the JSONL logs."""
    if os.path.exists(docx_path):
        return
        
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    generate_report_script = os.path.join(project_root, "generate_report.py")
    
    python_bin = sys.executable
    if sys.platform == "win32":
        venv_python = os.path.join(project_root, ".venv", "Scripts", "python.exe")
        if os.path.exists(venv_python):
            python_bin = venv_python
    else:
        venv_python = os.path.join(project_root, ".venv", "bin", "python")
        if os.path.exists(venv_python):
            python_bin = venv_python
            
    try:
        subprocess.run(
            [python_bin, generate_report_script, log_path, "--output", docx_path],
            check=True,
            capture_output=True,
            cwd=project_root
        )
        print(f"Successfully auto-compiled docx report: {docx_path}")
    except Exception as e:
        print(f"Failed to auto-compile docx report: {e}")

def convert_docx_to_pdf(docx_path: str, out_dir: str) -> str:
    """Converts a compiled docx file to pdf using LibreOffice headless command line."""
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
