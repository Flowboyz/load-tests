# Konn3ct Different — Advanced WebSocket & WebRTC Load Testing Bot Framework

This directory contains the advanced load testing framework for the Konn3ct platform. It simulates hundreds of concurrent bots with highly realistic characteristics, including browser/device/OS fingerprints, actual WebRTC session establishment, synthetic media generation (audio/video), network condition profiles, and comprehensive action logging.

---

## 📋 Directory Contents

- `py_guest.py` — The main entry point orchestrating the bots, connections, actions, and scenario stress tests.
- `webrtc_client.py` — Handles `aiortc` peer connection setup, ICE/DTLS handshakes, and media stream flows.
- `media_generator.py` — Synthesizes media tracks (moving color bars with text overlays for video, sine-wave bursts for audio).
- `device_manager.py` — Handles OS/Device distribution profiles and valid combinations.
- `browser_emulator.py` — Emulates user agents, resolutions, viewports, and WebRTC capabilities.
- `browser_fingerprints.py` — Capabilities database for Chrome, Safari, Firefox, Edge, Brave, Opera, and mobile browsers.
- `network_simulator.py` — Applies network profiles (latency, jitter, packet loss) and handles degradation over time.
- `metrics_collector.py` — Collects and aggregates WebRTC connection times and action response latencies.
- `action_logger.py` — Outputs beautifully formatted console logs with browser context and saves events to JSONL.
- `generate_report.py` — Aggregates the JSONL log and exports a CSV action log.
- `build_docx_report.js` — JavaScript Node tool compiling the data into a `.docx` Word document.
- `requirements.txt` — Python dependencies.
- `package.json` — Node.js dependencies.

---

## 🛠️ Setup & Installation

### 1. Install Python Dependencies
Ensure you have Python 3.8+ and install the packages:
```bash
pip install -r requirements.txt
```

### 2. Install Node.js Dependencies
Install dependencies needed to generate the Word report:
```bash
npm install
```

---

## ⚙️ Command-Line Arguments

The framework supports the following command-line flags:

| Argument | Default | Description |
| :--- | :--- | :--- |
| `--room` | `testinggg` | Slug or room ID of the target meeting room. |
| `--bots` | `50` | Total number of concurrent bots to simulate. |
| `--leave` | `0` | Auto-leave after N minutes (0 = run indefinitely until interrupted). |
| `--stagger` | `1.0` | Seconds to wait between launching each staggered batch of bots. |
| `--batch` | `3` | Number of bots launched in each staggered batch. |
| `--concurrency` | `100` | Maximum active bots simultaneously connecting. |
| `--browser-distribution`| `chrome:30,safari:20,firefox:15,edge:10,brave:5...` | Ratios for emulated browsers (Chrome, Safari, Firefox, Edge, Brave, Opera, Chrome Mobile, Safari Mobile, Samsung Browser). |
| `--device-distribution` | `desktop:70,mobile:20,tablet:10` | Percentage breakdown of device types. |
| `--os-distribution` | `windows:40,macos:30,linux:10,ios:12,android:8` | Percentage breakdown of operating systems. |
| `--webrtc-enabled` | *(Flag)* | If set, establishes real WebRTC PeerConnections and transmits synthetic media. |
| `--media-quality` | `medium` | Quality profile choice for media tracks (`low`, `medium`, `high`, `full`). |
| `--network-conditions` | `ethernet:20,wi-fi:50,4g:20,3g:10` | Profile weights to simulate network environments. |
| `--network-degradation` | *(Flag)* | Progressively degrades network profiles as the test proceeds. |
| `--degradation-interval`| `300` | Degradation steps interval in seconds. |
| `--test-scenarios` | `camera_toggle,mic_toggle...` | Scenarios to execute (`simultaneous_camera_toggle`, `breakout_rooms`, `presenter_switch`, `screen_share_storm`, `note_update`). |
| `--action-interval` | `30` | Seconds between random client actions (camera, mic, hand). |
| `--chat-interval` | `60` | Seconds between chat messages sent per bot. |
| `--confirm-timeout` | `5` | Time to wait for server confirmation before flagging warning. |
| `--max-retries` | `5` | Max reconnect attempts per bot. |
| `--report-log` | `report_log.jsonl` | File path to output JSON event log. |
| `--report-output` | `load_test_report.docx` | Output file path of the final Word report. |
| `--jwt-secret` | `fallback-secret-key` | Secret key used to sign JWTs locally for bot authentication, bypassing pre-join API overhead. |
| `--max-subscriptions` | `2` | Cap on the number of WebRTC downstream video feeds each bot subscribes to (prevents CPU starvation). |
| `--decode-downlink` | *(Flag)* | If enabled, decrypts and decodes incoming video packets in software. Leave off to reduce CPU load. |
| `--host-bot-id` | `1` | The bot ID assigned the `host` role (can perform moderation commands). |
| `--presenter-bot-id` | `2` | The bot ID assigned the `presenter` role. |
| `--frontend` | `https://edge.konn3ct.net` | Target web server URL. |
| `--signal` | `konn3ctedge.konn3ct.net` | Target signaling/WebSocket server domain. |

---

## 🚀 Complete Usage Examples

### Example 1: WebRTC-enabled Test with Network Simulation
Simulates 50 bots utilizing `aiortc` WebRTC connections with simulated network profiles (4G, 3G, Wi-Fi, Ethernet) and media quality.
```bash
python py_guest.py --room testinggg --bots 50 --webrtc-enabled --network-conditions 4g:30,3g:10,wi-fi:50,ethernet:10 --media-quality full --test-scenarios camera_toggle,mic_toggle,hand_raise,chat
```

### Example 2: Host Moderation, Breakout Rooms & Whiteboard Note Sync Scenario
Run a test where Bot 1 acts as host (managing waiting-room admissions and moderator force-mutes), while other bots migrate to breakout rooms and broadcast notes.
```bash
python py_guest.py --room testinggg --bots 10 --webrtc-enabled --jwt-secret "my-server-secret" --host-bot-id 1 --test-scenarios "breakout_rooms,note_update" --report-output moderation_report.docx
```

---

## 🌐 Production/Staging Server Deployment Configurations

When running load tests against a production or staging server:
1. **JWT Secret Bypass**:
   Generating JWTs locally via `--jwt-secret` prevents HTTP bottlenecks/rate-limits on your pre-join APIs when launching hundreds of bots. Ensure you provide the same JWT signing secret used by your Konn3ct server.
2. **CPU Scale Constraints**:
   Simulating downstream media subscription uses substantial CPU. By default, bots connect and register receiving transports but do not decode the packets. Use `--max-subscriptions 2` (default) to keep machine CPU usage clean. Avoid passing `--decode-downlink` unless you are testing a small subset of bots and need to measure complete media rendering performance.
3. **Signal and Frontend Alignment**:
   Always point `--frontend` to your main Konn3ct instance web root and `--signal` to the corresponding websocket signaling gateway.

---

## 📊 Generating the Word Report

The framework **automatically generates the report at the end of every run**, regardless of whether the script completes naturally or is interrupted using `Ctrl+C`. 

If you need to manually re-run or regenerate the report from a saved `.jsonl` log file, execute:
```bash
python generate_report.py report_log.jsonl --output custom_report.docx
```

This compiles:
1. `custom_report.docx` — Microsoft Word report containing joining times, WebRTC performance, and action matrices.
2. `report_log_action_log.csv` — Granular CSV export of all bot actions, latencies, and statuses.

---

## 🔧 Troubleshooting Guide

- **Error: `ModuleNotFoundError: No module named 'av'`**:
  Make sure you have installed `aiortc` correctly. It depends on `av` (PyAV), which uses compiled C extensions. On Windows, you can install precompiled wheels using `pip install av`.
- **High CPU usage during WebRTC test**:
  Synthetic media generation utilizes CPU for color bar drawing. Reduce `--concurrency` or use `--media-quality low` to minimize CPU bottlenecks. Make sure `--decode-downlink` is disabled when launching more than 5-10 bots.
