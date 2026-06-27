# Konn3ct Different — Advanced Load Testing Bot Framework & Dashboard

This directory contains the advanced load testing framework for the Konn3ct platform. It simulates hundreds of concurrent bots with highly realistic characteristics, including browser/device/OS fingerprints, actual WebRTC session establishment, synthetic media generation (audio/video), network condition profiles, and comprehensive action logging.

This update introduces a **modern web dashboard** that completely wraps command-line usage with an intuitive, Grafana-like web interface for real-time monitoring, template creation, and reports downloading.

---

## 📋 Directory Contents

- `run.py` — The entry point for starting the Flask web dashboard server. [NEW]
- `app/` — Flask Web application module (Auth blueprints, API controllers, Database models, and Frontend templates/static files). [NEW]
- `docker/` — Orchestration and reverse proxy settings (Dockerfile, docker-compose.yml, Nginx configurations). [NEW]
- `scripts/seed_db.py` — Seeds default users and configurations inside the database. [NEW]
- `py_guest.py` — The core CLI bot script, now supporting pause/resume flags.
- `webrtc_client.py` — Handles `aiortc` peer connection setup, ICE/DTLS handshakes, and media stream flows.
- `media_generator.py` — Synthesizes media tracks (moving color bars with text overlays for video, sine-wave bursts for audio).
- `device_manager.py` — Handles OS/Device/Hardware distribution profiles (Expanded).
- `browser_emulator.py` — Emulates user agents, resolutions, viewports, and WebRTC capabilities.
- `browser_fingerprints.py` — Capabilities database for Chrome, Safari, Firefox, Edge, Brave, Opera, and mobile browsers (Expanded).
- `network_simulator.py` — Applies network profiles (latency, jitter, packet loss) and handles degradation over time.
- `metrics_collector.py` — Collects and aggregates WebRTC connection times and action response latencies.
- `action_logger.py` — Outputs beautifully formatted console logs with browser context and saves events to JSONL.
- `generate_report.py` — Aggregates the JSONL log and exports a CSV action log.
- `build_docx_report.js` — JavaScript Node tool compiling the data into a `.docx` Word document.

---

## 🛠️ Local Web Dashboard Setup

### 1. Install System Prerequisites
The report engine generates Microsoft Word files. To convert them to PDF, you must have LibreOffice installed:
- **Ubuntu/Debian**: `sudo apt install -y libreoffice-writer`
- **Windows**: Download and install LibreOffice, and ensure `soffice` is added to your system `PATH`.

### 2. Install Dependencies
Ensure you have Python 3.8+ and Node.js 18+ installed, then run:
```bash
pip install -r requirements.txt
pip install flask-socketio eventlet PyJWT psutil
npm install
```

### 3. Initialize & Seed Database
Create the database tables and seed default users and configurations:
```bash
python scripts/seed_db.py
```

### 4. Start the Dashboard Web Server
Start the local Socket.IO development server:
```bash
python run.py
```
Open your browser and navigate to `http://localhost:8000`.

---

## 🐳 Docker Deployment (Ubuntu Production Server)

To deploy the dashboard on a production server with Let's Encrypt SSL certificates proxying on port 6000:
1. Ensure your domain points to your server and you have generated certificates under `/etc/letsencrypt/live/konn3ct/`.
2. Move into the `docker` directory and launch:
```bash
cd docker
docker-compose up --build -d
```
The application will be securely accessible at `https://<your-server-ip-or-domain>:6000`.

---

## 🔑 Authentication Credentials

The database is pre-seeded with three default user roles:

| Username | Password | Role | Description |
| :--- | :--- | :--- | :--- |
| `admin` | `adminpass` | **Admin** | Full access to form launchers, presets saving, user creation, and test control. |
| `operator` | `operatorpass` | **Operator** | Can configure, launch, pause, and stop tests. Cannot manage configurations/users. |
| `viewer` | `viewerpass` | **Viewer** | Read-only access. Can view live metrics and download historical reports. |

---

## 🌐 Navigating the Web Dashboard

### 1. Sign In
Navigate to the dashboard and log in with one of the pre-seeded credentials.

### 2. Configure a Load Test
- Switch to the **New Test** tab in the sidebar.
- Replace command-line execution arguments with the form fields:
  - **Basic Settings**: Room Slug, Total Bots, Batch sizes, and Stagger join delay.
  - **Media Settings**: Check "Enable WebRTC" and pick from High, Medium, or Low quality profiles.
  - **Library Distributions**: Modify text fields to alter percentages of Browsers (e.g. `chrome:50,safari:50`), Devices (`desktop:100`), or OS distribution.
- Click **Save Preset** at the bottom to store it as a template, or click **Launch Load Test** to run it immediately.

### 3. Live Monitoring & Controls
Once a test launches, the **Active Run Banner** appears at the top:
- **Pause/Resume**: Freezes bot action loops and staggers (useful to investigate server lockups).
- **Stop**: Ends execution gracefully and starts report compiling.
- **Real-Time Timelines**: Watch Connected vs Failed bots, Latency & Jitter timelines, and Host CPU/RAM resources update in real-time.
- **Action Lifecycle Propagation Widget**: Live pipeline counters tracking actions from sent → acknowledged → broadcasted → observed → rendered.
- **Advanced WebRTC Parameters Widget**: Real-time status tracker for signaling socket connection, ICE state, TURN/Relay count, average RTT, and average Jitter.
- **Timeout Stage Breakdown Widget**: Shows exact stages where timeouts occur (e.g. ack-timeout, ui-render-timeout).
- **Unsupported Actions Widget**: List of actions skipped due to capability mismatches (e.g., screen sharing on mobile browser).
- **Logs Console**: Search live terminal logs using the search filter input.

### 4. Downloading Reports
Navigate to the **Test History** tab to view previous sessions. You can:
- Click **Logs** to replay that session's timeline and graphs.
- Download reports instantly in **DOCX**, **PDF**, **CSV**, or raw **JSON** formats.
- Click **Clone** to load that run's configuration back into the launcher form.

---

## ⚙️ Command-Line Arguments (Original CLI Usage)

You can still bypass the web dashboard and run the bots directly via the CLI as before:

| Argument | Default | Description |
| :--- | :--- | :--- |
| `--room` | `testinggg` | Slug or room ID of the target meeting room. |
| `--bots` | `50` | Total number of concurrent bots to simulate. |
| `--leave` | `0` | Auto-leave after N minutes. |
| `--stagger` | `1.0` | Seconds between launch batches. |
| `--control-file` | `None` | JSON file check path to support Web Dashboard pause/resume controls. |
| `--webrtc-enabled` | *(Flag)* | If set, establishes real WebRTC streams. |

### CLI Example:
```bash
python py_guest.py --room testinggg --bots 10 --webrtc-enabled --test-scenarios camera_toggle,mic_toggle,chat
```

---

## 📈 Action-Lifecycle Validation Engine & Metrics

With the validation engine upgrade, every bot action goes through a strict state propagation lifecycle:
`sent → acknowledged → broadcasted → observed → rendered`

### 1. Propagation Stages
- **sent**: Action triggered by the sender bot.
- **acknowledged**: Server confirmed receipt back to the sender bot.
- **broadcasted**: Server broadcasted the action to the room.
- **observed**: Other bots received the broadcast.
- **rendered**: Other bots completed visual rendering in their virtual UI.

### 2. Timeout & Mismatch Stages
- **ack-timeout**: Sender sent action but received no backend acknowledgment.
- **broadcast-timeout**: Acknowledged by server, but never broadcasted to any receiver.
- **observer-timeout**: Broadcasted but a specific receiver failed to observe it.
- **ui-render-timeout**: Receiver observed the event but it failed to render in the UI.
- **id-correlation-mismatch**: Event details found, but client/server event IDs are missing or mismatched.

### 3. Error Code Standards
Instead of generic timeouts, specific errors are recorded:
- `CHAT_ACK_TIMEOUT`, `CAMERA_ACK_TIMEOUT`, `MIC_ACK_TIMEOUT`, `HAND_ACK_TIMEOUT`, `SCREEN_SHARE_ACK_TIMEOUT`
- `CHAT_BROADCAST_TIMEOUT`, `SCREEN_SHARE_BROADCAST_TIMEOUT`, etc.
- `CHAT_OBSERVER_TIMEOUT`, `CHAT_RENDER_TIMEOUT`, `CHAT_ID_CORRELATION_MISMATCH`
- `SCREEN_SHARE_UNSUPPORTED` (for mobile screen share triggers)
- `WEBRTC_ICE_FAILED`, `WEBSOCKET_DISCONNECTED`, `MEDIA_PERMISSION_DENIED`

---


## 📊 Report Outputs & Formats

The load testing engine generates comprehensive reports in DOCX, PDF, CSV, and JSON formats. Every test run compiles three distinct CSV files in the session directory:

1. **`session_action_lifecycle.csv`**: Contains a row for every sender action propagation to every receiver path, containing exactly 39 columns tracking fingerprints, latency timestamps, and WebRTC states.
2. **`session_summary_metrics.csv`**: Contains aggregated success rates, average, and percentile latencies by action type, browser, operating system, and device type.
3. **`session_webrtc_stats.csv`**: Contains per-bot granular WebRTC statistics (ICE, DTLS, codecs, bandwidth, loss, jitter, freezes).

### 1. Granular Action Lifecycle CSV Schema (39 Columns)
The `session_action_lifecycle.csv` report contains the following exact columns:
- **Action Type**: The type of action performed (e.g. `chat`, `camera`, `mic`, `hand_raise`, `screen_share`).
- **Sender Bot ID**: Numeric ID of the bot triggering the action.
- **Sender OS**: Operating system of the sender bot.
- **Sender Browser**: Browser client emulated by the sender.
- **Sender Device Type**: Device category (desktop, mobile, tablet) of the sender.
- **Receiver Bot ID**: Numeric ID of the receiver bot observing the action.
- **Receiver OS**: Operating system of the receiver bot.
- **Receiver Browser**: Browser client emulated by the receiver.
- **Receiver Device Type**: Device category of the receiver.
- **Client Event ID**: Globally unique event ID generated by the client before sending.
- **Server Event ID**: Unique event ID generated by the backend server after receipt.
- **Sent Timestamp**: ISO-8601 timestamp when the action was sent.
- **Ack Timestamp**: ISO-8601 timestamp when the sender received server acknowledgment.
- **Broadcast Timestamp**: ISO-8601 timestamp when the backend broadcasted the event.
- **Observed Timestamp**: ISO-8601 timestamp when the receiver bot observed the event.
- **Rendered Timestamp**: ISO-8601 timestamp when the receiver bot rendered the state changes.
- **Ack Latency ms**: Round-trip latency for server acknowledgment.
- **Broadcast Latency ms**: Latency between server receipt and broadcast event emission.
- **Observer Latency ms**: Propagation latency from broadcast emission to receiver observation.
- **UI Render Latency ms**: Visual rendering latency in the receiver's mock UI.
- **Final Status**: The strict action resolution status (`sent`, `acknowledged`, `broadcasted`, `observed`, `rendered`, `timed-out`, `failed`, `unsupported`).
- **Timeout Stage**: The specific stage where the timeout occurred (`ack-timeout`, `broadcast-timeout`, `observer-timeout`, `ui-render-timeout`, `id-correlation-mismatch`).
- **Error Code**: Diagnostic error code (e.g., `CHAT_ACK_TIMEOUT`, `WEBRTC_ICE_FAILED`).
- **Unsupported Reason**: Description of why an action was skipped (e.g., `IOS_SAFARI_SCREEN_SHARE_UNSUPPORTED`).
- **Room ID**: The meeting room slug.
- **Test Session ID**: Unique database identifier for the test session.
- **Bot Name**: Display name of the sender bot.
- **Browser Version**: Exact browser version string of the sender bot.
- **Resolution**: Viewport/screen resolution of the sender bot.
- **WebRTC ICE State**: ICE connection status of the bot.
- **WebSocket State**: Signaling socket state of the bot.
- **Media Track State**: Active media tracks (audio, video, screen share) for the bot.
- **Producer ID**: WebRTC SFU media producer identifier.
- **Consumer ID**: WebRTC SFU media consumer identifier.
- **Codec**: Audio/video codec used for negotiation (e.g., `H264`, `VP8`, `AV1`).
- **Bitrate**: Media sending or receiving bitrate in kbps.
- **RTT**: Round-trip time (RTT) in milliseconds measured by the peer connection.
- **Packet Loss**: Fraction of packets lost (0.0 - 1.0).
- **Jitter**: Network jitter in milliseconds.

### 2. Compiled Word Document Structure (21 Sections)
The DOCX report compiler (`build_docx_report.js`) formats the test results into exactly 21 required evaluation sections:
1. **Executive Summary Dashboard**: High-level test summary cards (Peak concurrent, duration, total bots).
2. **Test Configuration**: Detailed input configurations and arguments.
3. **Bot and Host Distribution**: Distinct count and layout of emulated cohorts and host clients.
4. **Browser Coverage Matrix**: Table detailing simulated browsers and their success metrics.
5. **OS Coverage Matrix**: Table detailing operating systems and success metrics.
6. **Device Coverage Matrix**: Table detailing device profiles (desktop, mobile, tablet).
7. **WebRTC Performance Summary**: Comprehensive WebRTC metrics tables.
8. **Action Lifecycle Summary**: Global propagation counts, latencies, and success percentages.
9. **Chat Deep-Dive**: Performance analysis for the chat message lifecycle.
10. **Screen-Share Deep-Dive**: Screen share lifecycle success rates and frame render delay statistics.
11. **Camera/Mic/Hand Raise Deep-Dive**: Deep dive metrics for toggle actions.
12. **Timeout Stage Analysis**: Distribution of timeouts across propagation stages.
13. **Unsupported Action Analysis**: Breakdown of unsupported actions by browser/OS.
14. **Error Code Analysis**: Breakdown of system errors and failure codes.
15. **Per-Browser Recommendations**: Ranks browsers by latency and recommends optimal platforms.
16. **Per-OS Recommendations**: Operating system-specific compatibility recommendations.
17. **Per-Device Recommendations**: Performance advice for desktop/mobile/tablet form factors.
18. **Sprint 1 Pass/Fail Assessment**: Automated check against the Sprint 1 Quality Gates.
19. **QA Verdict**: Overall verdict of the load test (Pass, Fail, Warn).
20. **Developer Recommendations**: Actionable technical remediation advice.
21. **Appendix: Full Action Log Reference**: Path and metadata reference to CSV output files.

---

## 🚀 Preconfigured Test Profiles

The system includes preconfigured profiles, accessible via the web dashboard presets:

1. **Sprint 1 Diagnostic Test** (10 bots)
   - Focus: End-to-end action-lifecycle validation, chat success, and screen-share unsupported classification.
2. **50-Bot Regression Test** (50 bots + 1 host)
   - Focus: Regression testing against baseline performance across full browser/OS/device cohorts.
3. **100-Bot Load Test** (100 bots + 1 host)
   - Focus: WebSocket fan-out stability and UI rendering delays.
4. **250-Bot Load Test** (250 bots)
   - Focus: Backend broadcast reliability and WebRTC media subscriptions.
5. **500-Bot Stress Test** (500 bots)
   - Focus: Server CPU/Memory stress, WebSocket concurrent connection handling.
6. **Soak Test** (50-100 bots, 30-60 mins)
   - Focus: Long-duration stability, memory leaks, connection drops, and media quality degradation.
7. **Browser Compatibility Test** (20 bots)
   - Focus: Fixed allocation across all emulated browsers (Chrome, Safari, Firefox, Edge, Brave, Opera, mobile browsers, Samsung Internet) and OS platforms.
