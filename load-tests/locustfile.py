"""
Konn3ct Load Test — 500+ User Room Simulation (v2 - Fixed)
============================================================

Fixes from v1:
  1. Reduced default spawn rate to 10/sec to avoid overwhelming the server
  2. Lightweight receiver — drains the WebSocket buffer without heavy parsing
  3. No separate threads — uses Locust's built-in gevent concurrency
     (avoids Python GIL bottleneck at 100+ users)
  4. Better error logging to diagnose connection rejections
  5. Graceful reconnection with backoff
  6. Origin header matches production domain
  7. Increased connection timeout to 30s

USAGE
-----
    pip install -r requirements.txt

    # Web dashboard (recommended)
    locust -f locustfile.py --host wss://konn3ctedge.konn3ct.net

    # Set Number of users: 500, Ramp up: 10 (NOT 50)
    # 10 users/second = all 500 connected in 50 seconds without choking the server

    # Headless: 500 users, 10/sec spawn, 5 minutes
    locust -f locustfile.py --host wss://konn3ctedge.konn3ct.net \
        --headless -u 500 -r 10 --run-time 5m
"""

import os
import json
import time
import random
import string
import uuid
import logging
import ssl

import jwt
import websocket
from locust import User, task, between, events, run_single_user

# ─── Configuration ────────────────────────────────────────────────────────────

JWT_SECRET = os.environ.get("JWT_SECRET", "test-secret-for-playwright")
ROOM_SLUG = os.environ.get("ROOM_SLUG", "playwright-test-room")

CHAT_MESSAGES = [
    "Hello everyone!", "Can you hear me?", "Great presentation!",
    "I have a question about that slide", "Could you share the document?",
    "Sounds good, let's proceed", "I agree with that approach",
    "Can we revisit the timeline?", "Thanks for the update",
    "Let's table that for the next meeting", "Does anyone have the link?",
    "I'll follow up on that", "Looks great to me!",
    "What do you all think?", "Sorry, I was on mute",
    "Let's wrap up in 5 minutes", "Good meeting everyone!",
]

REACTION_EMOJIS = ["👍", "👏", "❤️", "🎉", "😂", "😮", "🤔", "🔥", "💯", "✅", "👋", "🙌"]

logger = logging.getLogger("konn3ct-loadtest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Track connection stats
connection_stats = {"connected": 0, "failed": 0, "rejected": 0, "disconnected": 0}


# ─── JWT Helper ───────────────────────────────────────────────────────────────

def generate_join_token(user_id, name, email, role="attendee"):
    payload = {
        "userId": user_id,
        "email": email,
        "name": name,
        "role": role,
        "isBot": False,
        "isMobile": False,
        "exp": int(time.time()) + 86400,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def random_name():
    first_names = [
        "Aisha", "Chidi", "Fatima", "Emeka", "Zainab", "Tunde", "Ngozi", "Kofi",
        "Amina", "Yusuf", "Sarah", "James", "Oluwaseun", "Blessing", "David",
        "Grace", "Samuel", "Mary", "Joseph", "Esther", "Michael", "Ruth",
        "Daniel", "Rebecca", "Peter", "Judith", "Emmanuel", "Mercy", "Isaac",
        "Deborah", "Stephen", "Hannah", "Philip", "Lydia", "Andrew", "Miriam",
    ]
    return random.choice(first_names) + " " + random.choice(string.ascii_uppercase) + "."


# ─── WebSocket Meeting User ──────────────────────────────────────────────────

class MeetingUser(User):
    wait_time = between(3, 10)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws = None
        self.user_id = "loadtest_" + uuid.uuid4().hex[:12]
        self.display_name = random_name()
        self.email = self.user_id + "@loadtest.konn3ct.net"
        self.connected = False
        self.joined = False
        self.is_muted = True
        self.is_camera_on = False
        self.is_hand_raised = False
        self._connect_attempts = 0

    def on_start(self):
        self._connect()

    def on_stop(self):
        self._disconnect()

    def _connect(self):
        self._connect_attempts += 1
        token = generate_join_token(self.user_id, self.display_name, self.email)
        host = self.host.rstrip("/")
        ws_url = host + "/signal?token=" + token + "&roomId=" + ROOM_SLUG + "&isMobile=false"

        # SSL for wss://
        sslopt = {}
        if ws_url.startswith("wss://"):
            sslopt = {"cert_reqs": ssl.CERT_NONE}

        start_time = time.time()
        try:
            self.ws = websocket.create_connection(
                ws_url,
                timeout=30,
                header={"Origin": "https://konn3ct.net"},
                sslopt=sslopt,
            )
            elapsed_ms = (time.time() - start_time) * 1000

            events.request.fire(
                request_type="WebSocket", name="connect",
                response_time=elapsed_ms, response_length=0,
                exception=None, context={},
            )

            self.connected = True
            self._connect_attempts = 0
            connection_stats["connected"] += 1

            # Read initial messages to confirm join
            self._drain_initial_messages()
            logger.info("[%s] Connected (%d total)", self.display_name, connection_stats["connected"])

        except websocket.WebSocketBadStatusException as e:
            elapsed_ms = (time.time() - start_time) * 1000
            status_code = getattr(e, "status_code", 0)
            connection_stats["rejected"] += 1
            events.request.fire(
                request_type="WebSocket", name="connect_rejected_" + str(status_code),
                response_time=elapsed_ms, response_length=0,
                exception=e, context={},
            )
            logger.error("[%s] REJECTED status %s: %s", self.display_name, status_code, e)
            self.connected = False

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            connection_stats["failed"] += 1
            events.request.fire(
                request_type="WebSocket", name="connect_failed",
                response_time=elapsed_ms, response_length=0,
                exception=e, context={},
            )
            logger.error("[%s] FAILED (attempt %d): %s: %s",
                         self.display_name, self._connect_attempts, type(e).__name__, e)
            self.connected = False

    def _drain_initial_messages(self):
        """Read the first few messages to confirm join status."""
        try:
            self.ws.settimeout(5.0)
            for _ in range(5):
                try:
                    raw = self.ws.recv()
                    if not raw:
                        break
                    data = json.loads(raw)
                    msg_type = data.get("type", "")

                    if msg_type == "session_status":
                        status = data.get("status")
                        if status == "active":
                            self.joined = True
                        elif status in ("kicked", "denied", "ended"):
                            self.connected = False
                            connection_stats["rejected"] += 1
                            return

                    elif msg_type == "participants_list":
                        count = len(data.get("participants", []))
                        logger.debug("[%s] Room has %d participants", self.display_name, count)

                except websocket.WebSocketTimeoutException:
                    break
                except Exception:
                    break
        finally:
            if self.ws:
                self.ws.settimeout(2.0)

    def _drain_incoming(self):
        """
        Lightweight drain — read and discard pending messages.
        Prevents the receive buffer from filling up (which causes the server
        to think the client is dead and close the connection).
        Only parses messages we actually care about.
        """
        if not self.connected or not self.ws:
            return

        try:
            self.ws.settimeout(0.1)
            for _ in range(20):
                try:
                    raw = self.ws.recv()
                    if not raw:
                        break

                    # Only parse session-critical messages
                    if "session_status" in raw:
                        data = json.loads(raw)
                        status = data.get("status")
                        if status in ("kicked", "denied", "ended"):
                            self.connected = False
                            connection_stats["disconnected"] += 1
                            return

                    elif "server_load_high" in raw:
                        events.request.fire(
                            request_type="WebSocket", name="server_load_high",
                            response_time=0, response_length=0,
                            exception=None, context={},
                        )

                except websocket.WebSocketTimeoutException:
                    break
                except websocket.WebSocketConnectionClosedException:
                    logger.warning("[%s] Connection closed by server", self.display_name)
                    self.connected = False
                    connection_stats["disconnected"] += 1
                    break
                except Exception:
                    break
        except Exception:
            pass

    def _disconnect(self):
        if self.ws and self.connected:
            try:
                self.ws.send(json.dumps({"type": "leave_meeting"}))
                time.sleep(0.05)
                self.ws.close()
            except Exception:
                pass

        if self.connected:
            connection_stats["connected"] = max(0, connection_stats["connected"] - 1)
            connection_stats["disconnected"] += 1

        self.connected = False
        self.joined = False

    def _send_message(self, data):
        if not self.connected or not self.ws:
            return False

        msg_type = data.get("type", "unknown")
        payload = json.dumps(data)

        start_time = time.time()
        try:
            self.ws.send(payload)
            elapsed_ms = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket", name="send_" + msg_type,
                response_time=elapsed_ms, response_length=len(payload),
                exception=None, context={},
            )
            return True
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="WebSocket", name="send_" + msg_type,
                response_time=elapsed_ms, response_length=0,
                exception=e, context={},
            )
            self.connected = False
            connection_stats["disconnected"] += 1
            return False

    # ─── Tasks ────────────────────────────────────────────────────────────────

    @task(40)
    def idle(self):
        """Just sit and listen. Drains incoming to keep connection alive."""
        if not self.connected:
            if self._connect_attempts < 3:
                time.sleep(self._connect_attempts * 2)
                self._connect()
            return
        self._drain_incoming()

    @task(20)
    def send_chat_message(self):
        if not self.joined:
            return
        self._drain_incoming()
        self._send_message({"type": "chat", "message": random.choice(CHAT_MESSAGES)})

    @task(15)
    def send_reaction(self):
        if not self.joined:
            return
        self._drain_incoming()
        self._send_message({"type": "reaction", "reaction": random.choice(REACTION_EMOJIS)})

    @task(10)
    def toggle_mute(self):
        if not self.joined:
            return
        self._drain_incoming()
        self.is_muted = not self.is_muted
        self._send_message({"type": "mute_state", "isMuted": self.is_muted})

    @task(8)
    def toggle_camera(self):
        if not self.joined:
            return
        self._drain_incoming()
        self.is_camera_on = not self.is_camera_on
        self._send_message({"type": "camera_state", "isCameraOn": self.is_camera_on})

    @task(5)
    def toggle_hand_raise(self):
        if not self.joined:
            return
        self._drain_incoming()
        self.is_hand_raised = not self.is_hand_raised
        self._send_message({"type": "hand_raise", "isHandRaised": self.is_hand_raised})


# ─── Event Hooks ──────────────────────────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("\n" + "=" * 70)
    print("  KONN3CT LOAD TEST v2")
    print("  Room: " + ROOM_SLUG)
    print("  Target: " + str(environment.host))
    print("  JWT: " + ("[CUSTOM]" if JWT_SECRET != "test-secret-for-playwright" else "[DEFAULT]"))
    print()
    print("  TIP: Set ramp-up to 10 users/sec (not 50)")
    print("=" * 70 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.runner.stats
    print("\n" + "=" * 70)
    print("  LOAD TEST COMPLETE")
    print("  Total requests: " + str(stats.total.num_requests))
    print("  Failures: " + str(stats.total.num_failures))
    print("  Avg response time: %.1fms" % stats.total.avg_response_time)
    if stats.total.num_requests > 0:
        fail_rate = (stats.total.num_failures / stats.total.num_requests) * 100
        print("  Failure rate: %.1f%%" % fail_rate)
    print()
    print("  Connection Stats:")
    print("    Currently connected: " + str(connection_stats["connected"]))
    print("    Rejected by server: " + str(connection_stats["rejected"]))
    print("    Connection failures: " + str(connection_stats["failed"]))
    print("    Disconnected during test: " + str(connection_stats["disconnected"]))
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_single_user(MeetingUser)
