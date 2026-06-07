"""
Konn3ct Silent Load Test v2 — Bots connect and sit quietly.
No chat, no reactions, no unmuting. Pure connection stress test.

USAGE
-----
    pip install -r requirements.txt

    # Web dashboard
    locust -f locustfile_silent.py --host wss://konn3ctedge.konn3ct.net

    # Set: 500 users, ramp-up 10, then Start

    # Headless
    JWT_SECRET="your-secret" ROOM_SLUG="your-room" \
        locust -f locustfile_silent.py --host wss://konn3ctedge.konn3ct.net \
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

JWT_SECRET = os.environ.get("JWT_SECRET", "test-secret-for-playwright")
ROOM_SLUG = os.environ.get("ROOM_SLUG", "playwright-test-room")

logger = logging.getLogger("konn3ct-silent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

connection_stats = {"connected": 0, "failed": 0, "rejected": 0, "disconnected": 0}


def generate_token(user_id, name, email):
    return jwt.encode({
        "userId": user_id, "email": email, "name": name,
        "role": "attendee", "isBot": False, "isMobile": False,
        "exp": int(time.time()) + 86400,
    }, JWT_SECRET, algorithm="HS256")


def random_name():
    names = [
        "Aisha", "Chidi", "Fatima", "Emeka", "Zainab", "Tunde", "Ngozi", "Kofi",
        "Amina", "Yusuf", "Sarah", "James", "David", "Grace", "Samuel", "Mary",
        "Joseph", "Esther", "Michael", "Ruth", "Daniel", "Rebecca", "Peter",
        "Emmanuel", "Mercy", "Isaac", "Deborah", "Stephen", "Hannah", "Philip",
    ]
    return random.choice(names) + " " + random.choice(string.ascii_uppercase) + "."


class SilentUser(User):
    wait_time = between(5, 15)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws = None
        self.user_id = "silent_" + uuid.uuid4().hex[:12]
        self.display_name = random_name()
        self.email = self.user_id + "@loadtest.konn3ct.net"
        self.connected = False
        self.joined = False
        self._connect_attempts = 0

    def on_start(self):
        self._connect()

    def on_stop(self):
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

    def _connect(self):
        self._connect_attempts += 1
        token = generate_token(self.user_id, self.display_name, self.email)
        host = self.host.rstrip("/")
        ws_url = host + "/signal?token=" + token + "&roomId=" + ROOM_SLUG + "&isMobile=false"

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
            logger.error("[%s] REJECTED status %s", self.display_name, status_code)
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
        """Drain receive buffer to keep connection alive. Parse nothing."""
        if not self.connected or not self.ws:
            return

        try:
            self.ws.settimeout(0.1)
            for _ in range(20):
                try:
                    raw = self.ws.recv()
                    if not raw:
                        break

                    # Only check for session-ending messages
                    if "session_status" in raw:
                        data = json.loads(raw)
                        status = data.get("status")
                        if status in ("kicked", "denied", "ended"):
                            self.connected = False
                            connection_stats["disconnected"] += 1
                            return

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

    @task
    def idle(self):
        """Just sit there. Drain buffer to stay alive. Do nothing else."""
        if not self.connected:
            if self._connect_attempts < 3:
                time.sleep(self._connect_attempts * 2)
                self._connect()
            return
        self._drain_incoming()


# ─── Event Hooks ──────────────────────────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("\n" + "=" * 70)
    print("  KONN3CT SILENT LOAD TEST v2")
    print("  Room: " + ROOM_SLUG)
    print("  Target: " + str(environment.host))
    print("  Mode: SILENT (bots connect and sit, no actions)")
    print()
    print("  TIP: Set ramp-up to 10 users/sec (not 50)")
    print("=" * 70 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.runner.stats
    print("\n" + "=" * 70)
    print("  SILENT LOAD TEST COMPLETE")
    print("  Total requests: " + str(stats.total.num_requests))
    print("  Failures: " + str(stats.total.num_failures))
    print()
    print("  Connection Stats:")
    print("    Currently connected: " + str(connection_stats["connected"]))
    print("    Rejected by server: " + str(connection_stats["rejected"]))
    print("    Connection failures: " + str(connection_stats["failed"]))
    print("    Disconnected during test: " + str(connection_stats["disconnected"]))
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_single_user(SilentUser)
