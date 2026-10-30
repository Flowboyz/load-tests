import os
import json
from datetime import datetime

def generate_web_report(report_json_path, log_lines, output_dir):
    """
    Compiles a beautiful self-contained HTML report from the Playwright test run.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Load JSON report data
    try:
        with open(report_json_path, 'r', encoding='utf-8') as f:
            report_data = json.load(f)
    except Exception as e:
        report_data = {
            "target_url": "Unknown",
            "started_at": datetime.utcnow().isoformat() + "Z",
            "completed_at": datetime.utcnow().isoformat() + "Z",
            "steps": [],
            "status": "failed",
            "duration_total_sec": 0,
            "error": f"Failed to parse test report JSON: {str(e)}"
        }

    # Format dates
    started_str = report_data.get("started_at", "")
    completed_str = report_data.get("completed_at", "")
    
    # Calculate overall success
    total_steps = len(report_data.get("steps", []))
    passed_steps = sum(1 for s in report_data.get("steps", []) if s["status"] == "passed")
    failed_steps = sum(1 for s in report_data.get("steps", []) if s["status"] == "failed")
    
    status_class = "status-pass" if report_data["status"] == "passed" else "status-fail"
    status_label = "PASSED" if report_data["status"] == "passed" else "FAILED"
    
    # Create HTML rows for steps
    step_rows_html = ""
    for step in report_data.get("steps", []):
        icon = '<i class="fa-solid fa-circle-check text-green"></i>' if step["status"] == "passed" else '<i class="fa-solid fa-circle-xmark text-red"></i>'
        status_badge = f'<span class="badge badge-{"success" if step["status"] == "passed" else "danger"}">{step["status"].upper()}</span>'
        error_msg = f'<div class="step-error">{step["error"]}</div>' if step["error"] else ''
        
        # Calculate visual width percentage for duration bar (max scale out of 10 seconds per step for rendering)
        dur = step["duration_sec"]
        bar_width = min(100, max(5, int((dur / 10.0) * 100)))
        
        step_rows_html += f"""
        <tr class="step-row">
            <td>{icon} <strong>{step["name"]}</strong></td>
            <td>{status_badge}</td>
            <td>
                <div class="duration-container">
                    <span class="duration-text">{dur}s</span>
                    <div class="duration-bar-bg">
                        <div class="duration-bar-fill" style="width: {bar_width}%;"></div>
                    </div>
                </div>
                {error_msg}
            </td>
        </tr>
        """

    # Escape log lines for safety
    console_logs_html = ""
    for line in log_lines:
        line_clean = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if "[ERROR]" in line or "❌" in line:
            console_logs_html += f'<div class="log-line text-red">{line_clean}</div>'
        elif "[SUCCESS]" in line or "✅" in line:
            console_logs_html += f'<div class="log-line text-green">{line_clean}</div>'
        else:
            console_logs_html += f'<div class="log-line">{line_clean}</div>'

    # Build full HTML template
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Konn3ct Web E2E Test Report</title>
    <!-- Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <!-- FontAwesome Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: #151d30;
            --border-color: #232e48;
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --text-muted: #6b7280;
            --primary: #2563eb;
            --success: #10b981;
            --error: #ef4444;
            --warning: #f59e0b;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Inter', sans-serif;
        }}
        
        body {{
            background-color: var(--bg-color);
            color: var(--text-primary);
            padding: 40px 20px;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        
        h1, h2, h3, h4 {{
            font-family: 'Outfit', sans-serif;
            font-weight: 700;
            margin-bottom: 10px;
        }}
        
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 24px;
            margin-bottom: 30px;
        }}
        
        .header-title h1 {{
            font-size: 28px;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #60a5fa, #2563eb);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .header-title p {{
            color: var(--text-secondary);
            font-size: 14px;
        }}
        
        .status-badge {{
            padding: 10px 20px;
            border-radius: 30px;
            font-family: 'Outfit', sans-serif;
            font-size: 16px;
            font-weight: 800;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .status-pass {{
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--success);
            border: 1.5px solid var(--success);
        }}
        
        .status-fail {{
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--error);
            border: 1.5px solid var(--error);
        }}
        
        /* Stats Cards */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        
        .stat-card .label {{
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
            font-weight: 600;
        }}
        
        .stat-card .value {{
            font-family: 'Outfit', sans-serif;
            font-size: 24px;
            font-weight: 700;
        }}
        
        .stat-card .unit {{
            font-size: 14px;
            color: var(--text-secondary);
            font-weight: 500;
        }}
        
        /* Step Table */
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 30px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
        }}
        
        .card h2 {{
            font-size: 20px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 12px;
        }}
        
        .table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        
        .table th {{
            padding: 12px;
            color: var(--text-secondary);
            font-weight: 600;
            border-bottom: 1.5px solid var(--border-color);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .table td {{
            padding: 16px 12px;
            border-bottom: 1px solid var(--border-color);
            font-size: 14px;
            vertical-align: top;
        }}
        
        .step-row:last-child td {{
            border-bottom: none;
        }}
        
        .text-green {{
            color: var(--success);
        }}
        
        .text-red {{
            color: var(--error);
        }}
        
        .badge {{
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
        }}
        
        .badge-success {{
            background-color: rgba(16, 185, 129, 0.2);
            color: var(--success);
        }}
        
        .badge-danger {{
            background-color: rgba(239, 68, 68, 0.2);
            color: var(--error);
        }}
        
        /* Timings visualizer */
        .duration-container {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        
        .duration-text {{
            font-weight: 600;
            width: 45px;
            font-size: 13px;
        }}
        
        .duration-bar-bg {{
            flex-grow: 1;
            height: 8px;
            background-color: var(--border-color);
            border-radius: 4px;
            overflow: hidden;
            max-width: 250px;
        }}
        
        .duration-bar-fill {{
            height: 100%;
            background: linear-gradient(90deg, #3b82f6, #60a5fa);
            border-radius: 4px;
        }}
        
        .step-error {{
            color: var(--error);
            font-family: monospace;
            background-color: rgba(239, 68, 68, 0.08);
            border-left: 3.5px solid var(--error);
            padding: 10px;
            border-radius: 4px;
            margin-top: 10px;
            font-size: 12px;
            line-height: 1.4;
            max-width: 500px;
            white-space: pre-wrap;
        }}
        
        /* Live console output */
        .console {{
            background-color: #080b11;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
            max-height: 400px;
            overflow-y: auto;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 12px;
            color: #d4d4d4;
            line-height: 1.5;
        }}
        
        .log-line {{
            margin-bottom: 4px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.02);
            padding-bottom: 2px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Top header -->
        <header class="header">
            <div class="header-title">
                <h1>Web UI Functional E2E Test Report</h1>
                <p>Target App URL: <a href="{report_data["target_url"]}" target="_blank" style="color: #60a5fa; text-decoration: none;">{report_data["target_url"]}</a></p>
            </div>
            <div class="status-badge {status_class}">
                { '<i class="fa-solid fa-circle-check"></i>' if report_data["status"] == "passed" else '<i class="fa-solid fa-circle-exclamation"></i>' }
                {status_label}
            </div>
        </header>
        
        <!-- Summary Cards -->
        <section class="stats-grid">
            <div class="stat-card">
                <span class="label">Total Duration</span>
                <span class="value">{report_data["duration_total_sec"]} <span class="unit">seconds</span></span>
            </div>
            <div class="stat-card">
                <span class="label">Executed Steps</span>
                <span class="value">{total_steps}</span>
            </div>
            <div class="stat-card">
                <span class="label">Passed Steps</span>
                <span class="value" style="color: var(--success);">{passed_steps}</span>
            </div>
            <div class="stat-card">
                <span class="label">Failed Steps</span>
                <span class="value" style="color: var(--error);">{failed_steps}</span>
            </div>
        </section>
        
        <!-- Steps Breakdown -->
        <div class="card">
            <h2><i class="fa-solid fa-network-wired" style="color: #60a5fa;"></i> E2E Steps Execution Lifecycle</h2>
            <table class="table">
                <thead>
                    <tr>
                        <th style="width: 40%;">Step / Action Name</th>
                        <th style="width: 20%;">Execution Status</th>
                        <th style="width: 40%;">Performance Metric</th>
                    </tr>
                </thead>
                <tbody>
                    {step_rows_html}
                </tbody>
            </table>
        </div>
        
        <!-- Log Outputs -->
        <div class="card">
            <h2><i class="fa-solid fa-terminal" style="color: var(--success);"></i> Live Terminal Logs</h2>
            <div class="console">
                {console_logs_html}
            </div>
        </div>
    </div>
</body>
</html>
"""

    # Generate file names based on timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_filename = f"web_e2e_report_{timestamp}.html"
    filepath = os.path.join(output_dir, report_filename)
    
    with open(filepath, 'w', encoding='utf-8') as hf:
        hf.write(html_content)
        
    return report_filename
