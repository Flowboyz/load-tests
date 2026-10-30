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

    # Attempt 1: Playwright Python SDK
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
        print(f"Playwright PDF generation unavailable ({e}), trying system browser / pure-Python fallback...")

    # Attempt 2: System Chromium / Chrome / Edge CLI (--headless --print-to-pdf)
    browser_candidates = [
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("msedge"),
        shutil.which("chrome"),
    ]
    if sys.platform == "win32":
        browser_candidates.extend([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ])
    elif sys.platform.startswith("linux"):
        browser_candidates.extend([
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ])

    browser_bin = next((b for b in browser_candidates if b and os.path.exists(b)), None)
    if browser_bin:
        temp_html = os.path.join(out_dir, "_temp_report_render.html")
        try:
            with open(temp_html, "w", encoding="utf-8") as hf:
                hf.write(styled_html)
            cmd = [
                browser_bin,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                "--no-pdf-header-footer",
                f"--print-to-pdf={os.path.abspath(pdf_path)}",
                os.path.abspath(temp_html)
            ]
            subprocess.run(cmd, capture_output=True, timeout=30)
            if os.path.exists(temp_html):
                os.remove(temp_html)
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
                return True
        except Exception as e:
            if os.path.exists(temp_html):
                try:
                    os.remove(temp_html)
                except Exception:
                    pass
            print(f"System browser PDF generation failed: {e}")

    # Attempt 3: Zero-dependency pure-Python PDF 1.4 generator
    try:
        if _render_pure_python_pdf(content, pdf_path):
            return True
    except Exception as e:
        print(f"Pure-Python PDF fallback failed: {e}")
        
    return False


def _render_pure_python_pdf(markdown_text: str, pdf_path: str) -> bool:
    """
    Zero-dependency pure-Python PDF 1.4 writer using built-in Type1 Helvetica fonts.
    Guarantees a valid, readable multi-page PDF on headless servers without LibreOffice or Chromium.
    """
    import re
    import textwrap

    def clean_pdf_text(s: str) -> str:
        # Replace non-latin1 characters with readable ASCII equivalents
        replacements = {
            "—": "-", "–": "-", "•": "*", "⚡": "[AI]", "📋": "[GATE]", "💡": "[INFO]",
            "🚨": "[ALERT]", "❌": "[X]", "⚠️": "[!]", "✅": "[OK]", "≥": ">=", "≤": "<="
        }
        for k, v in replacements.items():
            s = s.replace(k, v)
        s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
        s = re.sub(r"\*(.*?)\*", r"\1", s)
        s = re.sub(r"`(.*?)`", r"\1", s)
        s = s.encode("latin-1", "replace").decode("latin-1")
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    lines_out = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            lines_out.append(("spacer", ""))
            continue
        if line.startswith("# "):
            lines_out.append(("h1", line[2:].strip()))
        elif line.startswith("## "):
            lines_out.append(("h2", line[3:].strip()))
        elif line.startswith("### ") or line.startswith("#### "):
            lines_out.append(("h3", line.lstrip("#").strip()))
        elif line.startswith("|") and ("---" in line or ":---" in line):
            continue
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            row_txt = " | ".join(cells)
            for wrapped in textwrap.wrap(row_txt, width=92) or [""]:
                lines_out.append(("table", wrapped))
        elif line == "---":
            lines_out.append(("rule", "-" * 85))
        else:
            for wrapped in textwrap.wrap(line, width=90) or [""]:
                lines_out.append(("body", wrapped))

    # Paginate into A4 pages (595 x 842 pt)
    pages = []
    curr_ops = []
    y = 790
    for style, txt in lines_out:
        if y < 60:
            pages.append("\n".join(curr_ops))
            curr_ops = []
            y = 790
        if style == "spacer":
            y -= 8
            continue
        elif style == "h1":
            y -= 6
            curr_ops.append(f"BT /F2 15 Tf 45 {y} Td ({clean_pdf_text(txt)}) Tj ET")
            y -= 20
        elif style == "h2":
            y -= 6
            curr_ops.append(f"BT /F2 12 Tf 45 {y} Td ({clean_pdf_text(txt)}) Tj ET")
            y -= 16
        elif style == "h3":
            y -= 4
            curr_ops.append(f"BT /F2 10.5 Tf 45 {y} Td ({clean_pdf_text(txt)}) Tj ET")
            y -= 14
        elif style == "table":
            curr_ops.append(f"BT /F1 8.5 Tf 45 {y} Td ({clean_pdf_text(txt)}) Tj ET")
            y -= 12
        else:
            curr_ops.append(f"BT /F1 9.5 Tf 45 {y} Td ({clean_pdf_text(txt)}) Tj ET")
            y -= 13

    if curr_ops or not pages:
        pages.append("\n".join(curr_ops))

    objects = []
    # 1: Catalog, 2: Pages, 3: Font Regular, 4: Font Bold
    page_obj_ids = []
    next_id = 5
    page_entries = []
    for p_content in pages:
        p_id = next_id
        c_id = next_id + 1
        next_id += 2
        page_obj_ids.append(p_id)
        page_entries.append((p_id, c_id, p_content.encode("latin-1")))

    kids_str = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    objects.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    objects.append((2, f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_obj_ids)} >>".encode("latin-1")))
    objects.append((3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"))
    objects.append((4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"))

    for p_id, c_id, stream_bytes in page_entries:
        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {c_id} 0 R >>"
        ).encode("latin-1")
        content_dict = f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1") + stream_bytes + b"\nendstream"
        objects.append((p_id, page_dict))
        objects.append((c_id, content_dict))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for obj_id, body in objects:
        offsets[obj_id] = len(out)
        out.extend(f"{obj_id} 0 obj\n".encode("latin-1"))
        out.extend(body)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    total_objs = len(objects) + 1
    out.extend(f"xref\n0 {total_objs}\n0000000000 65535 f \n".encode("latin-1"))
    for i in range(1, total_objs):
        out.extend(f"{offsets[i]:010d} 00000 n \n".encode("latin-1"))
    out.extend(
        f"trailer\n<< /Size {total_objs} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("latin-1")
    )

    with open(pdf_path, "wb") as pf:
        pf.write(out)

    return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100


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
