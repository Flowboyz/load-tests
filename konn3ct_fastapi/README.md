# Konn3ct Load Testing Framework (FastAPI Edition)

A modernized, asynchronous, next-generation version of the Konn3ct Load Testing Framework, built with **FastAPI**, **AsyncIO**, and **WebSockets** for high-concurrency bot orchestration and real-time performance monitoring.

---

## Architecture Overview

```text
konn3ct_fastapi/
│
├── app.py                  # Main entry point (FastAPI instance & Lifespan management)
├── database.py             # SQLite connection pooling & SessionLocal helper
├── models.py               # SQLAlchemy schemas for Users, configs, sessions, metrics
├── auth.py                 # JWT Cookie & API Key authorization dependency
│
├── routers/                # Routing layer
│   ├── dashboard.py        # Web UI pages (dashboard & login)
│   ├── api.py              # REST API & Top Level control endpoints
│   ├── websocket.py        # Real-time WebSocket room streaming (/ws)
│   └── reports.py          # Chunked report file downloads
│
├── services/               # Services layer
│   ├── bot_runner.py       # Async subprocess spawning & orphaned run re-adoption
│   ├── metrics.py          # Background log tailing & resource metrics gathering
│   └── reports.py          # DOCX compilation & LibreOffice PDF converter
│
├── static/                 # Static assets folder
│   ├── css/style.css       # Premium custom stylesheet
│   └── js/                 # Javascript files (dashboard.js, charts.js)
│
├── templates/              # Jinja2 template files (dashboard.html, login.html)
│
├── logs/                   # System runtime log files
├── requirements.txt        # Backend dependencies list
└── README.md               # Setup & deployment guide
```

---

## 1. Localhost Deployment (Quick Start)

Follow these steps to set up and run the application locally on your computer.

### Prerequisites
- Python 3.8+ installed.
- Node.js (v16+) installed (needed for Word `.docx` report layout compiler).
- **Optional**: LibreOffice installed (required if you want to export/download reports in **PDF** format).

### Step-by-Step Setup

1. **Clone/Navigate to the directory**:
   ```bash
   cd konn3ct_fastapi
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv .venv
   ```

3. **Activate the virtual environment**:
   - **Windows**:
     ```powershell
     .venv\Scripts\activate
     ```
   - **macOS/Linux**:
     ```bash
     source .venv/bin/activate
     ```

4. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Install Node.js report layout compiler dependencies**:
   ```bash
   npm install
   ```

6. **Seed the database**:
   This recreates database tables and inserts default users (`admin`, `operator`, `viewer`) and the 7 preconfigured test profiles.
   ```bash
   python -m scripts.seed_db
   ```

7. **Start the local server**:
   ```bash
   python app.py
   ```
   Or run directly with Uvicorn:
   ```bash
   uvicorn app:app --host 127.0.0.1 --port 8000 --reload
   ```

8. **Access the Dashboard**:
   Open [http://localhost:8000](http://localhost:8000) in your web browser.
   - **Username**: `admin`
   - **Password**: `adminpass`

---

## 2. Digital Server Deployment (Production Setup from Scratch)

This guide walks you through deploying the framework on a clean **Ubuntu 22.04 LTS** server (e.g. DigitalOcean, Linode, AWS EC2, or custom VPS).

### Step 1: System Package Prerequisites

Update server packages and install security utilities, Git, Python pip, Node.js, and LibreOffice.
```bash
sudo apt update && sudo apt upgrade -y

# Install Python development packages
sudo apt install -y python3-pip python3-venv python3-dev git curl build-essential

# Install Node.js & NPM
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Install headless LibreOffice for PDF generation
sudo apt install -y libreoffice-nogui
```

### Step 2: Code Deployment & Virtualenv Setup

1. **Clone the code to `/var/www/`**:
   ```bash
   sudo mkdir -p /var/www
   sudo chown -R $USER:$USER /var/www
   cd /var/www
   # Clone or move the folder here
   git clone <your-repo-url> konn3ct_fastapi
   cd konn3ct_fastapi
   ```

2. **Initialize Python and Node Environments**:
   ```bash
   # Create and activate virtualenv
   python3 -m venv .venv
   source .venv/bin/activate

   # Install pip packages
   pip install --upgrade pip
   pip install -r requirements.txt

   # Install Node packages
   npm install
   ```

3. **Initialize Database Seeding**:
   ```bash
   python -m scripts.seed_db
   ```

### Step 3: Configure systemd Service for FastAPI

Use systemd to manage the Uvicorn application server process and automatically restart it on failure or reboot.

1. **Create the systemd service file**:
   ```bash
   sudo nano /etc/systemd/system/konn3ct_fastapi.service
   ```

2. **Add the following configuration**:
   ```ini
   [Unit]
   Description=Konn3ct FastAPI Load Testing Dashboard
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/var/www/konn3ct_fastapi
   Environment="PATH=/var/www/konn3ct_fastapi/.venv/bin"
   Environment="DASHBOARD_SECRET_KEY=put-a-strong-custom-secret-here"
   ExecStart=/var/www/konn3ct_fastapi/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 4 --proxy-headers

   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   *(Note: Adjust the `User` field depending on your server user (e.g. `ubuntu`, `root`, or `debian`).)*

3. **Start and enable the service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl start konn3ct_fastapi
   sudo systemctl enable konn3ct_fastapi
   ```

4. **Verify running status**:
   ```bash
   sudo systemctl status konn3ct_fastapi
   ```

---

### Step 4: Configure Nginx as a Reverse Proxy with WebSocket Support

Configure Nginx to route traffic to the Uvicorn instance on port 8000, serve static files, and enable WebSocket connection upgrading.

1. **Install Nginx**:
   ```bash
   sudo apt install -y nginx
   ```

2. **Create a virtual host configuration**:
   ```bash
   sudo nano /etc/nginx/sites-available/konn3ct_fastapi
   ```

3. **Add the following server configuration**:
   ```nginx
   server {
       listen 80;
       server_name yourdomain.com; # Replace with your Domain or IP Address

       # Max request size limit (important for downloading large reports)
       client_max_body_size 50M;

       # Log paths
       access_log /var/log/nginx/konn3ct_access.log;
       error_log /var/log/nginx/konn3ct_error.log;

       # Route to FastAPI application
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       # Route for WebSockets connection upgrading
       location /ws {
           proxy_pass http://127.0.0.1:8000/ws;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "Upgrade";
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_read_timeout 86400; # 24 hour timeout
       }
   }
   ```

4. **Enable the configuration and restart Nginx**:
   ```bash
   sudo ln -s /etc/nginx/sites-available/konn3ct_fastapi /etc/nginx/sites-enabled/
   sudo rm /etc/nginx/sites-enabled/default # Remove fallback config if present
   sudo nginx -t # Test syntax
   sudo systemctl restart nginx
   ```

---

### Step 5: Secure the Server (SSL & Firewall)

1. **Install Let's Encrypt Certbot**:
   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   ```

2. **Obtain SSL Certificate**:
   ```bash
   sudo certbot --nginx -d yourdomain.com
   ```
   Follow the prompts to configure automatic SSL redirects. Certbot will rewrite your Nginx configuration to enforce HTTPs.

3. **Configure Firewall (ufw)**:
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow ssh
   sudo ufw allow 'Nginx Full' # Allows HTTP (80) & HTTPS (443)
   sudo ufw enable
   ```

4. **Verify Firewall Status**:
   ```bash
   sudo ufw status
   ```

---

## 3. Top-Level Control REST API Usage

You can control and monitor load tests remotely via script integrations or CURL commands.

**Start a new test session (returns JSON session object)**:
```bash
curl -X POST https://yourdomain.com/start \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"room": "loadtest-room", "bots": 20}'
```

**Pause the active session**:
```bash
curl -X POST https://yourdomain.com/pause -H "Authorization: Bearer <JWT_TOKEN>"
```

**Resume the paused session**:
```bash
curl -X POST https://yourdomain.com/resume -H "Authorization: Bearer <JWT_TOKEN>"
```

**Stop the active session**:
```bash
curl -X POST https://yourdomain.com/stop -H "Authorization: Bearer <JWT_TOKEN>"
```

**Fetch active/latest session status**:
```bash
curl -X GET https://yourdomain.com/status -H "Authorization: Bearer <JWT_TOKEN>"
```

**Fetch latest metrics**:
```bash
curl -X GET https://yourdomain.com/metrics -H "Authorization: Bearer <JWT_TOKEN>"
```

**Fetch / Save Configuration SLA Thresholds**:
```bash
# Get active SLA thresholds
curl -X GET https://yourdomain.com/api/configurations/1/sla -H "Authorization: Bearer <JWT_TOKEN>"

# Update SLA thresholds
curl -X PUT https://yourdomain.com/api/configurations/1/sla \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
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
  }'
```

**Fetch / Save Browser Launch Configurations**:
```bash
# Get launch options
curl -X GET https://yourdomain.com/api/configurations/1/browser-launch -H "Authorization: Bearer <JWT_TOKEN>"

# Update launch options
curl -X PUT https://yourdomain.com/api/configurations/1/browser-launch \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "use_fake_ui_for_media_stream": true,
    "use_fake_device_for_media_stream": true,
    "autoplay_policy": "no-user-gesture-required",
    "disable_notifications": true,
    "disable_popup_blocking": true,
    "disable_infobars": true,
    "disable_dev_shm_usage": true,
    "no_sandbox": true,
    "ignore_certificate_errors": true,
    "disable_web_security": true,
    "allow_running_insecure_content": true,
    "custom_flags": ""
  }'
```

**Load / Save Entire Profile Preset Templates**:
```bash
# Save active parameters to preset
curl -X POST https://yourdomain.com/api/configurations/1/save \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"room": "staging-smoke", "bots": 100}'

# Load preset details
curl -X POST https://yourdomain.com/api/configurations/1/load -H "Authorization: Bearer <JWT_TOKEN>"
```

---

## 4. Telemetry Database Migrations & Reporting Updates

### Automatic SQLite Schema Migrations
The FastAPI server automatically executes schema migrations upon boot (using raw `sqlite3` queries inside the lifespan context of `app.py`). When adding/deploying to a new server:
- The backend checks the `session_metrics` table schema and automatically runs DDL queries to alter and append the 8 new metrics columns (`ack_latency`, `peak_latency`, `join_rate`, `avg_join_time`, `mps`, `eps`, `net_throughput_kbps`, `active_bots`) if they do not exist.
- No manual migration commands or database wipes are required.

### Enterprise-Scale Report Generation Compiler
The report compiler has been upgraded to a memory-bounded streaming architecture in `generate_report.py`:
- **Node.js Dependencies**: Always run `npm install` in the project root directory during deployment. This installs the required Node `docx` libraries needed for compiling the final Word documents.
- **Low Memory Join Strategy**: Log event streams are processed sequentially and loaded into a temporary SQLite database. The cross-product joins of actions and observations are fully indexed and streamed directly to disk, keeping memory consumption low (<30MB) even for millions of logs.
- **Percentiles and Online Stats**: Average latencies and percentiles (P50, P95, P99) are computed dynamically using reservoir sampling.
- **High-Fidelity Word Layouts**: The document compiler `build_docx_report.js` renders tables for Browser comparative performance, Operating System stability, simulated Device profiles, categorized error telemetry, and a chronological session timeline of critical events.
