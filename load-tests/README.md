# Konn3ct Load Test — 500+ User Room Simulation

## What This Does

Simulates hundreds of concurrent users joining a Konn3ct meeting room via WebSocket. Each simulated user sends realistic meeting actions — chat messages, emoji reactions, hand raises, mute/camera toggles — at human-realistic intervals.

Unlike Playwright (which opens a real browser per user and needs 300MB+ each), this uses lightweight WebSocket connections (~5KB per user). **500 users comfortably run on a single laptop.**

## Prerequisites

- Python 3.8 or higher (you already have this since you're a Python developer)
- pip

## Setup

```bash
cd load-tests
pip install -r requirements.txt
```

That's it. Three packages: `locust`, `websocket-client`, `PyJWT`.

## How to Run

### Option 1: With Web Dashboard (recommended for first run)

```bash
locust -f locustfile.py --host ws://localhost:3000
```

Open http://localhost:8089 in your browser. You'll see the Locust dashboard. Set:
- **Number of users**: 500
- **Spawn rate**: 50 (adds 50 users per second — reaches 500 in 10 seconds)
- Click **Start swarming**

You'll see real-time charts showing:
- Requests per second
- Response times
- Number of connected users
- Failure rate

### Option 2: Headless (no browser needed)

```bash
# 500 users, spawn 50/sec, run for 5 minutes
locust -f locustfile.py --host ws://localhost:3000 \
    --headless -u 500 -r 50 --run-time 5m
```

### Option 3: Against production

```bash
# Make sure to set the correct JWT_SECRET
JWT_SECRET="your-production-secret" ROOM_SLUG="your-room-slug" \
    locust -f locustfile.py --host wss://konn3ctedge.konn3ct.net
```

## Environment Variables

| Variable     | Default                        | Description                                  |
|-------------|-------------------------------|----------------------------------------------|
| JWT_SECRET  | test-secret-for-playwright    | Must match the backend's JWT_SECRET          |
| ROOM_SLUG   | playwright-test-room          | The room slug to join                        |

## What Each Simulated User Does

Users perform actions at weighted frequencies (higher weight = more frequent):

| Action           | Weight | Description                        |
|-----------------|--------|------------------------------------|
| Idle             | 40     | Just listens (keeps connection alive) |
| Send chat        | 20     | Sends a random chat message        |
| Send reaction    | 15     | Sends a random emoji (👍❤️🔥 etc)  |
| Toggle mute      | 10     | Toggles microphone state           |
| Toggle camera    | 8      | Toggles camera state               |
| Raise/lower hand | 5      | Toggles hand raise                 |
| Send caption     | 2      | Simulates speech-to-text           |

The `wait_time` between actions is 2–8 seconds per user, mimicking real human behaviour in a meeting.

## What to Watch For

### In the Locust Dashboard

- **Response time climbing** → The server is struggling to handle the message load
- **Failure rate increasing** → WebSocket connections are being dropped
- **"server_load_high_warning"** in the stats → The backend is reporting CPU overload (>85%)

### In the Backend Terminal

- Watch for `CPU LOAD IS HIGH!!!` messages
- Watch for memory usage (use `htop` in another terminal)
- Watch for `User ... grace period expired` messages (means users are disconnecting)

### Key Metrics to Report

After the test, Locust shows a summary table. Report these to your supervisor:

1. **Peak concurrent users**: How many users were connected at the same time
2. **Connect success rate**: % of WebSocket connections that succeeded
3. **Average response time**: How fast the server processes messages
4. **95th percentile response time**: How fast for the slowest 5% of messages
5. **Failure rate**: % of messages that failed
6. **Server warnings**: How many "server_load_high" events occurred

## Scaling Beyond 500

If your machine runs out of file descriptors at high user counts:

```bash
# Increase the open file limit for this session
ulimit -n 65536
```

For 1000+ users, you can run multiple Locust workers:

```bash
# Terminal 1: master
locust -f locustfile.py --host ws://localhost:3000 --master

# Terminal 2-4: workers (run on same or different machines)
locust -f locustfile.py --host ws://localhost:3000 --worker --master-host=localhost
```

## Combining with Playwright

For the most realistic test, run the load test AND a headed Playwright test simultaneously:

```bash
# Terminal 1: Start 499 simulated users
locust -f locustfile.py --host ws://localhost:3000 --headless -u 499 -r 50

# Terminal 2: Open one real browser to watch the UI under load
cd ~/projects/konn3ct_edge/frontend
npx playwright test e2e/controls.spec.ts --headed
```

This lets you verify the UI still works while 499 fake users are hammering the server.
