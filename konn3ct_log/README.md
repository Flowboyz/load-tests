# Konn3ct Log — Advanced WebSocket Load Testing Bot

This tool is designed to simulate hundreds of concurrent users joining a Konn3ct meeting room via WebSocket connections. Unlike browser automation tools (like Playwright/Selenium) which require ~300MB+ memory per user, this WebSocket client uses lightweight connections (~5KB per bot), allowing you to run 100+ bots comfortably on a single machine.

It features **Persona-based behaviour** (Lurkers, Actives, Presenters, Churners, Hostiles) and **End-to-End Confirmed Action Tracking** to expose silent server failures under load.

---

## 📋 Directory Contents

- `py_guest.py` — The core Python script that manages the WebSocket clients and logs events.
- `generate_report.py` — Aggregates the resulting `.jsonl` log file and generates a summary.
- `build_docx_report.js` — A Node.js helper that formats the aggregated data into a polished Word report (`.docx`).
- `requirements.txt` — Python dependencies (`faker`, `aiohttp`, `websockets`).
- `package.json` — Node.js dependencies (`docx`).

---

## 🛠️ Setup

Before running the tests, make sure you install the Python and Node.js dependencies.

### 1. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 2. Install Node.js Dependencies (for report generation)
```bash
npm install
```

---

## 🚀 Running the Load Test

### 1. If Given a Custom Server to Run Against
If you have a local server or a staging server, use the `--frontend` and `--signal` arguments to direct the bots:

```bash
# Example: Local development server
python py_guest.py --frontend http://localhost:3000 --signal localhost:5000 --room testinggg --bots 50

# Example: Custom staging server
python py_guest.py --frontend https://staging.konn3ct.net --signal staging-signal.konn3ct.net --room demo-room --bots 100
```

*   `--frontend`: The HTTP URL of the frontend (used to retrieve auth tokens).
*   `--signal`: The domain (without `wss://` protocol) of the WebSocket signal server.

### 2. Running Against Production (Default)
By default, the script connects to the production endpoints:
```bash
python py_guest.py --room testinggg --bots 50
```

---

## 🌐 How to Witness the Bots in Your Own Browser

Because the bots run headless in your terminal via lightweight WebSockets, they don't open browser tabs. However, they join the exact same server-side rooms as real users. 

To watch them interact:
1. Open your browser and go to your room URL, e.g., `https://edge.konn3ct.net/room/testinggg` (or your local equivalent).
2. Open your terminal and run the bot script pointing to the same room:
   ```bash
   python py_guest.py --room testinggg --bots 20 --chat-interval 15 --action-interval 10
   ```
3. Watch your browser screen! You will see:
   * **Simulated attendees** joining the participant list in real-time.
   * **Chat messages** appearing in the sidebar chat list.
   * **Hand raises** toggling on participants.
   * **Emoji reactions** popping up.
   * **Camera and microphone indicators** toggling on and off.

---

## 📊 Generating the Word Report

When you run `py_guest.py`, it continuously outputs events into a `.jsonl` log file (defaults to `report_log.jsonl`). After stopping the test (using `Ctrl+C` or letting `--leave` finish), you can compile a detailed `.docx` report.

```bash
# 1. Run the test and output to a custom log file name
python py_guest.py --room testinggg --bots 50 --report-log my_run.jsonl --leave 5

# 2. Compile the Word report from the log file
python generate_report.py my_run.jsonl --output my_load_test_report.docx
```

This will call the underlying Node.js script `build_docx_report.js` to create `my_load_test_report.docx`, featuring:
*   **Response Latency Percentiles** (Avg, 95th) for cameras, mics, hands, chat.
*   **Desynchronisation occurrences** and action timeout counts.
*   **Detailed charts/tables** showing peak concurrent users, fail rates, and reconnect logs.

---

## ⚙️ Configuration Options

You can customize the simulation using command-line arguments:

| Option | Default | Description |
| :--- | :--- | :--- |
| `--room` | `testinggg` | The slug/ID of the target meeting room. |
| `--bots` | `50` | Number of concurrent simulated users. |
| `--leave` | `0` | Automatically leave after N minutes (`0` means wait for Ctrl+C). |
| `--stagger` | `1.0` | Seconds to wait between launching each batch of bots. |
| `--batch` | `3` | Number of bots launched in each staggered batch. |
| `--concurrency`| `100` | Max active bots simultaneously connecting. |
| `--chat-interval`| `60` | Seconds between chat messages per bot. |
| `--action-interval`| `30` | Seconds between random actions (camera, mic, etc.) per bot. |
| `--confirm-timeout`| `5` | Time to wait for server confirmation before flagging a timeout. |
| `--max-retries` | `5` | Reconnection attempts per bot on network disconnects. |
| `--no-chat` | `False` | Disable sending chat messages. |
| `--no-camera` | `False` | Disable camera toggles. |
| `--no-mic` | `False` | Disable microphone toggles. |
| `--no-handraise`| `False` | Disable hand raises. |
| `--lurkers-ratio`| `0.75` | Proportion of bots that just listen. |
| `--active-ratio` | `0.15` | Proportion of bots that toggle status and chat. |
| `--presenters-ratio`| `0.05` | Proportion of bots that stream video/audio. |
| `--churners-ratio`| `0.05` | Proportion of bots that repeatedly join and leave. |
| `--hostiles-ratio`| `0.00` | Proportion of bots that send spam or invalid data. |
| `--abnormal-ratio`| `0.00` | Proportion of bots that attempt unauthorized actions. |
| `--report-log` | `report_log.jsonl` | File path where JSON events are recorded. |
| `--frontend` | `https://edge.konn3ct.net` | Frontend base URL. |
| `--signal` | `konn3ctedge.konn3ct.net` | Signal server domain. |

---

## 🤖 Simulated Actions & How They Work

Simulated bots perform realistic user behaviors in real-time, testing both frontend state propagation and backend request processing:

### 1. Available Bot Actions
*   **Camera Toggle (`camera_state`)**: Bots toggle their camera feed on and off.
*   **Microphone Toggle (`mute_state`)**: Bots mute and unmute their microphone streams.
*   **Hand Raise (`hand_raise`)**: Bots raise or lower their hands to ask questions.
*   **Chat Messages (`chat`)**: Bots select from a list of realistic comments (e.g. *"Can everyone hear me?"*, *"Platform is really smooth!"*) and post them to the public room chat.
*   **Emoji Reactions (`reaction`)**: Bots send reaction emojis (e.g. `👍`, `❤️`, `🎉`, `😂`) that appear as overlay notifications.
*   **Poll Creation (`poll_create`)**: Bots with the *Presenter* role create multi-option polls (e.g. *"How is the connection?"*).
*   **Poll Voting (`poll_vote`)**: Non-presenter bots detect the new poll, wait a random delay of 2–6 seconds, and submit their votes.
*   **Shared Notes Update (`note_update`)**: *Presenter* bots update the collaborative meeting notes text block.

---

## 📡 Confirmed Action Tracking (CAT) & Consistency Checks

Under heavy traffic, servers often experience **silent failures** (requests are accepted, but never actually processed or broadcast to other room participants). To catch these issues, the bots use a verification feedback loop:

### 1. The Confirmation Lifecycle
1.  **Sending the Action**: The bot sends a state change request (e.g., `isCameraOn: True`) over the WebSocket connection.
2.  **Tracking Entry**: The action is registered in the bot's `PendingActions` queue with a high-resolution timestamp.
3.  **Broadcast Feedback**: The signal server processes the action and broadcasts the updated state back to the entire room.
4.  **Propagation Latency Calculation**: When the sending bot receives the broadcast echo, it removes the action from its queue, increments successful action stats, and logs the round-trip propagation time in milliseconds:
    $$\text{Propagation Latency} = T_{\text{received}} - T_{\text{sent}}$$
5.  **Timeout Warnings**: If the broadcast echo is not received within the `--confirm-timeout` limit (default: 5 seconds), the action is removed, flagged as **Unconfirmed**, and logged as a warning.

### 2. Cross-Confirmation
Other bots in the room listen for the same broadcast. Upon receipt, they resolve the user's name via a shared registry and log a cross-confirmation line (e.g. `Bot-0012 observed: John Doe turned camera ON`). This ensures that the state changes are visible to other attendees.

### 3. Participant List Consistency Checks
Whenever the server broadcasts a `participants_list` update, the receiving bot compares the length of this list to the actual number of active bots currently running in the local process.
If the list count is less than the active process count, the bot logs a **Desync Detected Warning** and registers a desync event, indicating the server failed to keep participant views in sync.

---

## 🛡️ Behavioural & Security Validation Testing

This tool includes a special **`abnormal`** persona. Bots assigned to this persona will periodically attempt to perform unauthorized tasks on the signal server, such as:
1. **Unauthorized Poll Creation**: Attempting to create a poll without having Presenter/Host permissions.
2. **Unauthorized Note Update**: Attempting to update meeting shared notes without Presenter/Host permissions.
3. **Invalid Poll Voting**: Attempting to vote on non-existent poll IDs.
4. **Malformed Payloads**: Sending chat messages with missing body text, or camera updates with invalid datatypes, to test input validation.
5. **Chat Rate-Limit Spam**: Sending 5 rapid chat messages in a single burst to test rate-limiting / flood protection.
6. **Unauthorized Premium Features**: Attempting to toggle premium capabilities (such as AI Noise Suppression) without subscription permissions.
7. **Host Mute Bypass**: Attempting to unmute the microphone immediately after the host triggers a forced mute, testing administrative override controls.

### 1. How it works
* When an abnormal bot sends these requests, it waits for server confirmation.
* If the server **correctly blocks** the action (by ignoring it or rejecting it), the client confirmation times out. It logs:
  `🛡️ Bot-0003 (John Doe) — tried to poll_create and it didn't work`
* If the server **incorrectly allows** the action (by broadcasting it back to the room), the client detects a security violation. It logs:
  `❌ Bot-0003 (John Doe) — tried to poll_create and it WORKED (incorrectly allowed!)`

These validation events are recorded and aggregated in the Word report under the **"Behavioural & Security Testing"** section.

### 2. How to run
Use the `--abnormal-ratio` flag to specify what fraction of your bots should behave abnormally (e.g. `0.2` for 20%):
```bash
python py_guest.py --room testinggg --bots 20 --abnormal-ratio 0.2 --action-interval 10
```

