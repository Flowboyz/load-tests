"""
pdf_generator.py — High-Fidelity PDF Report Generator for Konn3ct QA & Load Testing
Supports:
  1. Headless LibreOffice soffice conversion (Primary for DOCX)
  2. Playwright Headless Chromium HTML/Markdown rendering (Universal zero-dependency fallback)
"""

import os
import sys
import shutil
import subprocess

def find_libreoffice():
    """Locates LibreOffice soffice binary across PATH and standard OS locations."""
    soffice = shutil.which("soffice")
    if soffice:
        return soffice
        
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\LibreOffice\program\soffice.exe")
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    elif sys.platform.startswith("linux"):
        for c in ["/usr/bin/soffice", "/usr/bin/libreoffice", "/usr/local/bin/soffice"]:
            if os.path.exists(c):
                return c
    elif sys.platform == "darwin":
        mac_path = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if os.path.exists(mac_path):
            return mac_path
            
    return None


def render_markdown_to_pdf(md_path: str, pdf_path: str) -> bool:
    """
    Renders an enhanced analytics Markdown report into a professional,
    styled PDF document using Playwright Headless Chromium.
    """
    if not os.path.exists(md_path) or os.path.getsize(md_path) == 0:
        return False
        
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Failed to read markdown file {md_path}: {e}")
        return False

    html_body = []
    in_table = False
    
    for line in content.split("\n"):
        line_str = line.strip()
        if not line_str and not in_table:
            continue
            
        if line_str.startswith("# "):
            html_body.append(f"<h1 class='report-title'>{line_str[2:]}</h1>")
        elif line_str.startswith("## "):
            html_body.append(f"<h2 class='section-title'>{line_str[3:]}</h2>")
        elif line_str.startswith("### "):
            html_body.append(f"<h3 class='sub-section-title'>{line_str[4:]}</h3>")
        elif line_str.startswith("#### "):
            html_body.append(f"<h4 class='component-title'>{line_str[5:]}</h4>")
        elif line_str.startswith("> "):
            html_body.append(f"<div class='callout'>{line_str[2:]}</div>")
        elif line_str.startswith("|") and line_str.endswith("|"):
            cells = [c.strip() for c in line_str.split("|")[1:-1]]
            if len(cells) > 0 and ("---" in cells[0] or ":---" in cells[0]):
                continue
            if not in_table:
                html_body.append("<div class='table-container'><table><thead><tr>")
                for c in cells:
                    html_body.append(f"<th>{c}</th>")
                html_body.append("</tr></thead><tbody>")
                in_table = True
            else:
                html_body.append("<tr>")
                for c in cells:
                    html_body.append(f"<td>{c}</td>")
                html_body.append("</tr>")
        else:
            if in_table:
                html_body.append("</tbody></table></div>")
                in_table = False
            if line_str.startswith("- "):
                html_body.append(f"<ul class='bullet-list'><li>{line_str[2:]}</li></ul>")
            elif line_str == "---":
                html_body.append("<hr class='divider'/>")
            elif line_str:
                html_body.append(f"<p class='paragraph'>{line_str}</p>")
                
    if in_table:
        html_body.append("</tbody></table></div>")

    styled_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Konn3ct QA & Release Governance Report</title>
<style>
    @page {{
        size: A4 portrait;
        margin: 18mm 15mm;
        @bottom-right {{
            content: "Page " counter(page) " of " counter(pages);
            font-size: 9px;
            color: #64748b;
        }}
    }}
    * {{
        box-sizing: border-box;
    }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        line-height: 1.55;
        color: #0f172a;
        background: #ffffff;
        font-size: 11.5px;
        padding: 0;
        margin: 0;
    }}
    .header-bar {{
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        color: #ffffff;
        padding: 16px 20px;
        border-radius: 8px;
        margin-bottom: 20px;
    }}
    .header-bar h1 {{
        font-size: 18px;
        margin: 0 0 4px 0;
        color: #38bdf8;
        letter-spacing: -0.3px;
    }}
    .header-bar .subtitle {{
        font-size: 11px;
        color: #94a3b8;
        margin: 0;
    }}
    h1.report-title {{
        display: none;
    }}
    h2.section-title {{
        color: #0f172a;
        font-size: 14px;
        font-weight: 700;
        border-bottom: 1.5px solid #e2e8f0;
        padding-bottom: 5px;
        margin-top: 22px;
        margin-bottom: 10px;
        page-break-after: avoid;
    }}
    h3.sub-section-title {{
        color: #334155;
        font-size: 12.5px;
        font-weight: 600;
        margin-top: 14px;
        margin-bottom: 6px;
        page-break-after: avoid;
    }}
    h4.component-title {{
        color: #475569;
        font-size: 11.5px;
        font-weight: 600;
        margin-top: 10px;
        margin-bottom: 4px;
        page-break-after: avoid;
    }}
    .callout {{
        background: #f8fafc;
        border-left: 4px solid #0284c7;
        padding: 10px 14px;
        margin: 12px 0;
        border-radius: 0 6px 6px 0;
        font-size: 11.5px;
        color: #1e293b;
    }}
    .callout strong {{
        color: #0369a1;
    }}
    .table-container {{
        width: 100%;
        margin: 12px 0;
        page-break-inside: avoid;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 10.5px;
    }}
    th {{
        background: #f1f5f9;
        color: #334155;
        font-weight: 600;
        text-align: left;
        padding: 6px 10px;
        border: 1px solid #cbd5e1;
    }}
    td {{
        padding: 5px 10px;
        border: 1px solid #e2e8f0;
        color: #1e293b;
    }}
    tr:nth-child(even) {{
        background: #f8fafc;
    }}
    .bullet-list {{
        margin: 4px 0;
        padding-left: 18px;
    }}
    .bullet-list li {{
        margin-bottom: 3px;
    }}
    .paragraph {{
        margin: 6px 0;
    }}
    .divider {{
        border: none;
        border-top: 1px solid #e2e8f0;
        margin: 16px 0;
    }}
    code {{
        background: #f1f5f9;
        color: #0f172a;
        padding: 1px 4px;
        border-radius: 3px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 10.5px;
    }}
    .footer-note {{
        margin-top: 30px;
        text-align: center;
        font-size: 9px;
        color: #94a3b8;
        border-top: 1px solid #f1f5f9;
        padding-top: 10px;
    }}
</style>
</head>
<body>
    <div class="header-bar">
        <h1>Konn3ct QA & Release Governance Report</h1>
        <p class="subtitle">Blueprint Volume 7 Platform Certification, AI Developer Advisory & Multi-Device SLA Telemetry</p>
    </div>
    {"".join(html_body)}
    <div class="footer-note">
        Generated automatically by Konn3ct Load Testing Platform • Confidential & Proprietary
    </div>
</body>
</html>
"""

    out_dir = os.path.dirname(os.path.abspath(pdf_path))
    os.makedirs(out_dir, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(styled_html, wait_until="networkidle")
            page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"}
            )
            browser.close()
            
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
            return True
    except Exception as e:
        print(f"Playwright PDF generation failed: {e}")
        
    return False


def convert_report_to_pdf(docx_path: str, out_dir: str, md_path: str = None) -> str:
    """
    Dual-method PDF generator:
    1. Tries headless LibreOffice on the DOCX file.
    2. Seamlessly falls back to Playwright rendering the enhanced Markdown report.
    Returns the absolute path of the generated PDF, or None if failed.
    """
    if not docx_path and not md_path:
        return None
        
    os.makedirs(out_dir, exist_ok=True)
    
    # Target PDF path
    if docx_path:
        pdf_path = os.path.join(out_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
    else:
        pdf_path = os.path.join(out_dir, "report.pdf")

    # 1. Try LibreOffice if docx exists
    if docx_path and os.path.exists(docx_path) and os.path.getsize(docx_path) > 100:
        soffice = find_libreoffice()
        if soffice:
            try:
                cmd = [soffice, "--headless", "--convert-to", "pdf", "--outdir", out_dir, docx_path]
                res = subprocess.run(cmd, check=True, capture_output=True, timeout=30)
                if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
                    return pdf_path
            except Exception as e:
                print(f"LibreOffice PDF conversion failed, trying Playwright fallback: {e}")

    # 2. Fallback to Playwright from Markdown
    if not md_path and docx_path:
        md_candidate = os.path.join(out_dir, "session_enhanced_analytics.md")
        if os.path.exists(md_candidate):
            md_path = md_candidate
            
    if md_path and os.path.exists(md_path) and os.path.getsize(md_path) > 0:
        if render_markdown_to_pdf(md_path, pdf_path):
            return pdf_path

    return None
