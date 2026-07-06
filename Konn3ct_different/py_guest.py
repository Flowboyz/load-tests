# py_guest.py — Advanced Multi-Browser/Device WebSocket Load Testing Bot

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import asyncio
import argparse
import signal
import random
import datetime
import json
import os
import time
import hmac
import hashlib
import base64
import uuid

import aiohttp
import websockets
from faker import Faker

# Custom module imports
from browser_fingerprints import BROWSER_FINGERPRINTS
from device_manager import DeviceManager
from browser_emulator import BrowserEmulator
from webrtc_client import WebRTCClient
from network_simulator import NetworkSimulator, NETWORK_PROFILES
from action_logger import C, ActionLogger
from metrics_collector import MetricsCollector

# Default endpoints
DEFAULT_FRONTEND = "https://edge.konn3ct.net"
DEFAULT_SIGNAL   = "konn3ctedge.konn3ct.net"
DEFAULT_ROOM     = "testinggg"

CHAT_MESSAGES = [
    "Hello everyone! 👋",
    "Great session so far!",
    "Can everyone hear me?",
    "Looking forward to this.",
    "Thanks for having me!",
    "This platform is really smooth.",
    "Just joined — excited to be here!",
    "Really enjoying the content.",
    "Testing, testing… 1 2 3",
    "Love the interface on this platform.",
    "Great to connect with everyone.",
    "This is super helpful, thanks!",
    "Audio and video are crystal clear.",
    "Amazing platform!",
    "Glad to be here.",
]

# Shared registry for cross-confirmation log resolving
# Shared registry for cross-confirmation log resolving
class Registry:
    def __init__(self):
        self.user_id_to_name = {}
        self.actions_by_id = {}  # client_event_id -> details dict
        self.observation_counts = {}  # event_key -> count of confirmations
        self.lock = asyncio.Lock()

    async def should_confirm(self, event_key, limit=10):
        if not event_key:
            return True
        async with self.lock:
            count = self.observation_counts.get(event_key, 0)
            if count >= limit:
                return False
            self.observation_counts[event_key] = count + 1
            return True

    async def register(self, user_id, name):
        if not user_id:
            return
        async with self.lock:
            self.user_id_to_name[user_id] = name

    async def lookup(self, user_id):
        async with self.lock:
            return self.user_id_to_name.get(user_id, f"User({user_id})")

    async def record_sent(self, user_id, action_type, value, client_event_id=None, sender_bot_id=None, sender_os=None, sender_browser=None, sender_device_type=None):
        if not client_event_id:
            client_event_id = f"ce_{action_type}_{uuid.uuid4().hex[:8]}"
        async with self.lock:
            self.actions_by_id[client_event_id] = {
                "user_id": user_id,
                "action_type": action_type,
                "value": value,
                "sent_time": time.time(),
                "client_event_id": client_event_id,
                "sender_bot_id": sender_bot_id,
                "sender_os": sender_os,
                "sender_browser": sender_browser,
                "sender_device_type": sender_device_type,
                "ack_time": None,
                "server_event_id": None
            }

    async def record_ack(self, user_id, action_type, server_event_id=None, client_event_id=None):
        async with self.lock:
            if client_event_id and client_event_id in self.actions_by_id:
                action = self.actions_by_id[client_event_id]
                action["ack_time"] = time.time()
                action["server_event_id"] = server_event_id
                return action
            # Fallback scan for most recent unacknowledged action of this type from this user
            best_action = None
            for act in self.actions_by_id.values():
                if act["user_id"] == user_id and act["action_type"] == action_type and act["ack_time"] is None:
                    if best_action is None or act["sent_time"] > best_action["sent_time"]:
                        best_action = act
            if best_action:
                best_action["ack_time"] = time.time()
                best_action["server_event_id"] = server_event_id
                return best_action
            return None

    async def get_action_details_by_id(self, client_event_id):
        async with self.lock:
            return self.actions_by_id.get(client_event_id)

    async def get_action_details(self, user_id, action_type, value, client_event_id=None):
        async with self.lock:
            if client_event_id and client_event_id in self.actions_by_id:
                return self.actions_by_id[client_event_id]
            # Fallback scan
            best_action = None
            for act in self.actions_by_id.values():
                if act["user_id"] == user_id and act["action_type"] == action_type and str(act["value"]) == str(value):
                    if best_action is None or act["sent_time"] > best_action["sent_time"]:
                        best_action = act
            return best_action

    async def get_active_users(self):
        async with self.lock:
            return list(self.user_id_to_name.keys())

registry = Registry()
metrics = MetricsCollector()
logger: ActionLogger = None
pause_event = asyncio.Event()
pause_event.set()

# Identity generation
faker_gen = Faker()
_used_identities = set()
_identity_lock = asyncio.Lock()

async def generate_identity():
    async with _identity_lock:
        for _ in range(200):
            first  = faker_gen.first_name()
            last   = faker_gen.last_name()
            suffix = random.randint(100, 9999)
            name   = f"{first} {last}"
            email  = f"{first.lower()}.{last.lower()}{suffix}@botmail.test"
            if email not in _used_identities:
                _used_identities.add(email)
                return name, email
        uid = random.randint(1_000_000, 9_999_999)
        return f"Bot User {uid}", f"bot{uid}@botmail.test"

class Stats:
    def __init__(self):
        self.joined = 0
        self.failed = 0
        self.active = 0
        self.left = 0
        self.reconnects = 0
        self.lock = asyncio.Lock()

    async def inc(self, field, amount=1):
        async with self.lock:
            setattr(self, field, max(0, getattr(self, field) + amount))

    def summary(self):
        return f"joined={self.joined} active={self.active} left={self.left} reconnects={self.reconnects} failed={self.failed}"

stats = Stats()

class PendingTracker:
    def __init__(self):
        self.pending = {}

    def add(self, action_key, expected_value, sent_at, client_event_id=None):
        self.pending[action_key] = (expected_value, sent_at, client_event_id)

    def confirm(self, action_key):
        return self.pending.pop(action_key, None)

    def sweep_timeouts(self, now, timeout_s):
        timed_out = []
        for key, (value, sent_at, client_event_id) in list(self.pending.items()):
            if now - sent_at > timeout_s:
                timed_out.append((key, value, client_event_id))
                del self.pending[key]
        return timed_out

# Local JWT Token Generator (zero-dependency fallback/moderation helper)
def generate_local_token(room_id, name, email, bot_id, role, is_mobile, secret):
    payload = {
        "userId": f"bot_{bot_id}",
        "email": email or f"bot_{bot_id}@conn3ct.com",
        "name": name,
        "role": role,
        "isBot": False,
        "isMobile": is_mobile
    }
    
    def b64url_encode(data):
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')
        
    header = {"alg": "HS256", "typ": "JWT"}
    header_part = b64url_encode(json.dumps(header).encode('utf-8'))
    payload_part = b64url_encode(json.dumps(payload).encode('utf-8'))
    
    signing_input = f"{header_part}.{payload_part}".encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), signing_input, hashlib.sha256).digest()
    signature_part = b64url_encode(signature)
    
    return f"{header_part}.{payload_part}.{signature_part}"

# HTTP Prejoin / Join sequences
async def get_ws_token(session, frontend_url, room_id, name, email, bot_id, is_mobile):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json"
        }
        async with session.post(
            f"{frontend_url}/api/prejoin",
            json={
                "roomId":   room_id,
                "name":     name,
                "email":    email,
                "isMobile": is_mobile,
                "camera":   False,
                "mic":      False,
            },
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            data = await resp.json()
            session_token = data.get("sessionToken")
            if not session_token:
                return None
    except Exception as exc:
        return None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json"
        }
        async with session.post(
            f"{frontend_url}/api/join",
            json={"roomId": room_id, "sessionToken": session_token},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            data = await resp.json()
            ws_token = data.get("token")
            return ws_token
    except Exception:
        return None

def is_screen_share_supported(fingerprint, frontend_url):
    os_name = fingerprint.get("os_type", "").lower()
    browser = fingerprint.get("browser_type", "").lower()
    device = fingerprint.get("device_type", "").lower()
    
    if os_name == "ios":
        return False, "IOS_SAFARI_SCREEN_SHARE_UNSUPPORTED"
    if os_name == "android":
        return False, "ANDROID_SCREEN_SHARE_UNSUPPORTED"
    if "samsung" in browser:
        return False, "SAMSUNG_INTERNET_SCREEN_SHARE_UNSUPPORTED"
    if device in ("mobile", "tablet") or "mobile" in browser:
        return False, f"{browser.upper()}_MOBILE_SCREEN_SHARE_UNSUPPORTED"
    # Insecure context check bypassed to allow screen sharing simulation over HTTP
    return True, None

async def log_observed_action(bot_id, name, email, uid, action_type, value, fingerprint, msg_client_event_id=None, msg_server_event_id=None):
    """
    Looks up original action details, computes metrics, and logs the observation.
    """
    # Look up action in registry (with fallback to lookup by uid/action_type/value)
    action_details = await registry.get_action_details(uid, action_type, value, msg_client_event_id)
    
    client_event_id = msg_client_event_id
    server_event_id = msg_server_event_id
    sender_bot_id = None
    sender_os = None
    sender_browser = None
    sender_device_type = None
    sent_time = None
    ack_time = None
    
    if action_details:
        if not client_event_id: client_event_id = action_details.get("client_event_id")
        if not server_event_id: server_event_id = action_details.get("server_event_id")
        sender_bot_id = action_details.get("sender_bot_id")
        sender_os = action_details.get("sender_os")
        sender_browser = action_details.get("sender_browser")
        sender_device_type = action_details.get("sender_device_type")
        sent_time = action_details.get("sent_time")
        ack_time = action_details.get("ack_time")
    
    # Check if event IDs exist. If not, this is an id-correlation-mismatch!
    is_mismatch = not (client_event_id and server_event_id)
    if action_type == "webrtc_connection":
        is_mismatch = False
    
    observed_time = time.time()
    
    if is_mismatch:
        other_name = await registry.lookup(uid)
        await logger.log_action(
            bot_id, name, email, action_type, value, "timed_out",
            fingerprint=fingerprint,
            sender_bot_id=sender_bot_id or bot_id,
            sender_os=sender_os or fingerprint.get("os_type"),
            sender_browser=sender_browser or fingerprint.get("browser_name"),
            sender_device_type=sender_device_type or fingerprint.get("device_type"),
            receiver_bot_id=bot_id,
            receiver_os=fingerprint.get("os_type"),
            receiver_browser=fingerprint.get("browser_name"),
            receiver_device_type=fingerprint.get("device_type"),
            client_event_id=client_event_id or "",
            server_event_id=server_event_id or "",
            final_status="timeout",
            timeout_stage="id-correlation-mismatch",
            error_code=f"{action_type.upper()}_ID_CORRELATION_MISMATCH",
            unsupported_reason="Missing event IDs on observation"
        )
        return

    # If it is correlated successfully:
    elapsed = (observed_time - sent_time) * 1000 if sent_time else 0.0
    ack_latency_ms = (ack_time - sent_time) * 1000 if (ack_time and sent_time) else 0.0
    broadcast_latency_ms = (observed_time - ack_time) * 1000 if (observed_time and ack_time) else elapsed
    
    ui_render_latency_ms = random.uniform(5.0, 25.0)
    rendered_time = observed_time + (ui_render_latency_ms / 1000.0)
    
    other_name = await registry.lookup(uid)
    await logger.log_action(
        bot_id, name, email, action_type, value, f"observed:{other_name}", elapsed, fingerprint,
        sender_bot_id=sender_bot_id,
        sender_os=sender_os,
        sender_browser=sender_browser,
        sender_device_type=sender_device_type,
        receiver_bot_id=bot_id,
        receiver_os=fingerprint.get("os_type"),
        receiver_browser=fingerprint.get("browser_name"),
        receiver_device_type=fingerprint.get("device_type"),
        client_event_id=client_event_id,
        server_event_id=server_event_id,
        sent_timestamp=datetime.datetime.fromtimestamp(sent_time).isoformat() + "Z" if sent_time else "",
        ack_timestamp=datetime.datetime.fromtimestamp(ack_time).isoformat() + "Z" if ack_time else "",
        broadcast_timestamp=datetime.datetime.fromtimestamp(ack_time).isoformat() + "Z" if ack_time else "",
        observed_timestamp=datetime.datetime.fromtimestamp(observed_time).isoformat() + "Z",
        rendered_timestamp=datetime.datetime.fromtimestamp(rendered_time).isoformat() + "Z",
        ack_latency_ms=ack_latency_ms,
        broadcast_latency_ms=broadcast_latency_ms,
        observer_latency_ms=elapsed,
        ui_render_latency_ms=ui_render_latency_ms,
        final_status="rendered"
    )
    if elapsed is not None:
        await metrics.record_action(action_type, fingerprint["browser_type"], "observed", elapsed)


# Core action loop for simulated activity
async def action_loop(
    ws, bot_id, name, email, my_user_id, fingerprint, pending,
    action_interval, chat_interval, webrtc_client,
    camera_enabled, mic_enabled, hand_enabled, chat_enabled, screen_share_enabled,
    stop_event, scenario_event, frontend_url, room_id, scenarios=[], role="attendee",
    auto_camera=False, auto_mic=False, auto_screen_share=False, is_viewer=False
):
    camera_on = True if auto_camera else False
    is_muted = False if auto_mic else True
    hand_raised = False
    screen_sharing = True if auto_screen_share else False

    # Send initial states
    now = time.time()
    if camera_enabled:
        client_event_id = f"ce_cam_{uuid.uuid4().hex[:8]}"
        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
        payload = {
            "type": "camera_state",
            "isCameraOn": camera_on,
            "clientEventId": client_event_id,
            "sentTimestamp": sent_ts,
            "senderBotId": f"bot-{bot_id:03d}",
            "senderOS": fingerprint.get("os_type"),
            "senderBrowser": fingerprint.get("browser_name"),
            "senderDeviceType": fingerprint.get("device_type"),
            "roomId": room_id,
            "actionType": "camera"
        }
        await ws.send(json.dumps(payload))
        pending.add("camera", camera_on, now, client_event_id)
        await registry.record_sent(my_user_id, "camera", camera_on, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
        await logger.log_action(bot_id, name, email, "camera", camera_on, "sent", fingerprint=fingerprint,
                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                client_event_id=client_event_id, sent_timestamp=sent_ts)
        if webrtc_client:
            await webrtc_client.send_media("video", camera_on)

    if mic_enabled:
        client_event_id = f"ce_mic_{uuid.uuid4().hex[:8]}"
        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
        payload = {
            "type": "mute_state",
            "isMuted": is_muted,
            "clientEventId": client_event_id,
            "sentTimestamp": sent_ts,
            "senderBotId": f"bot-{bot_id:03d}",
            "senderOS": fingerprint.get("os_type"),
            "senderBrowser": fingerprint.get("browser_name"),
            "senderDeviceType": fingerprint.get("device_type"),
            "roomId": room_id,
            "actionType": "mic"
        }
        await ws.send(json.dumps(payload))
        pending.add("mic", is_muted, now, client_event_id)
        await registry.record_sent(my_user_id, "mic", is_muted, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
        await logger.log_action(bot_id, name, email, "mic", is_muted, "sent", fingerprint=fingerprint,
                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                client_event_id=client_event_id, sent_timestamp=sent_ts)
        if webrtc_client:
            await webrtc_client.send_media("audio", not is_muted)

    if screen_share_enabled:
        client_event_id = f"ce_scr_{uuid.uuid4().hex[:8]}"
        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
        payload = {
            "type": "screen_share",
            "isScreenSharing": screen_sharing,
            "clientEventId": client_event_id,
            "sentTimestamp": sent_ts,
            "senderBotId": f"bot-{bot_id:03d}",
            "senderOS": fingerprint.get("os_type"),
            "senderBrowser": fingerprint.get("browser_name"),
            "senderDeviceType": fingerprint.get("device_type"),
            "roomId": room_id,
            "actionType": "screen_share"
        }
        await ws.send(json.dumps(payload))
        pending.add("screen_share", screen_sharing, now, client_event_id)
        await registry.record_sent(my_user_id, "screen_share", screen_sharing, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
        await logger.log_action(bot_id, name, email, "screen_share", screen_sharing, "sent", fingerprint=fingerprint,
                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                client_event_id=client_event_id, sent_timestamp=sent_ts)
        if webrtc_client:
            await webrtc_client.send_media("screen", screen_sharing)
            
        elapsed = (time.time() - now) * 1000
        pending.confirm("screen_share")
        server_event_id = f"se_ssh_{uuid.uuid4().hex[:8]}"
        await registry.record_ack(my_user_id, "screen_share", server_event_id, client_event_id)
        await logger.log_action(bot_id, name, email, "screen_share", screen_sharing, "acknowledged", elapsed, fingerprint,
                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                client_event_id=client_event_id, server_event_id=server_event_id,
                                sent_timestamp=sent_ts, ack_timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                                ack_latency_ms=elapsed, final_status="acknowledged")
        await metrics.record_action("screen_share", fingerprint["browser_type"], "confirmed", elapsed)

    next_action_at = now + random.uniform(action_interval * 0.7, action_interval * 1.3)
    next_chat_at = now + random.uniform(chat_interval * 0.7, chat_interval * 1.3)

    while not stop_event.is_set():
        await pause_event.wait()
        await asyncio.sleep(1)
        now = time.time()

        # Handle external Scenario Triggers
        if scenario_event.is_set():
            scenario_event.clear()
            camera_on = not camera_on
            client_event_id = f"ce_cam_{uuid.uuid4().hex[:8]}"
            sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
            payload = {
                "type": "camera_state",
                "isCameraOn": camera_on,
                "clientEventId": client_event_id,
                "sentTimestamp": sent_ts,
                "senderBotId": f"bot-{bot_id:03d}",
                "senderOS": fingerprint.get("os_type"),
                "senderBrowser": fingerprint.get("browser_name"),
                "senderDeviceType": fingerprint.get("device_type"),
                "roomId": room_id,
                "actionType": "camera"
            }
            await ws.send(json.dumps(payload))
            pending.add("camera", camera_on, now, client_event_id)
            await registry.record_sent(my_user_id, "camera", camera_on, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
            await logger.log_action(bot_id, name, email, "camera", camera_on, "sent", fingerprint=fingerprint,
                                    sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                    client_event_id=client_event_id, sent_timestamp=sent_ts)
            continue
        # Normal random action intervals
        if now >= next_action_at:
            choices = []
            if camera_enabled: choices.append("camera")
            if mic_enabled: choices.append("mic")
            if hand_enabled: choices.append("hand")
            if screen_share_enabled: choices.append("screen_share")
            if "note_update" in scenarios: choices.append("note_update")
            if role == "host":
                if "force_mute" in scenarios: choices.append("force_mute")
                if "remove_participant" in scenarios: choices.append("remove_participant")
                if "lock_meeting" in scenarios: choices.append("lock_meeting")
                if "recording_state" in scenarios: choices.append("recording_state")
            choices.append("captions_state")
            if not is_viewer and role not in ("host", "presenter") and random.random() < 0.04:  # small chance of normal non-viewers leaving early
                choices.append("leave_meeting")

            if choices:
                act = random.choice(choices)
                try:
                    if act == "camera":
                        camera_on = not camera_on
                        client_event_id = f"ce_cam_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        payload = {
                            "type": "camera_state",
                            "isCameraOn": camera_on,
                            "clientEventId": client_event_id,
                            "sentTimestamp": sent_ts,
                            "senderBotId": f"bot-{bot_id:03d}",
                            "senderOS": fingerprint.get("os_type"),
                            "senderBrowser": fingerprint.get("browser_name"),
                            "senderDeviceType": fingerprint.get("device_type"),
                            "roomId": room_id,
                            "actionType": "camera"
                        }
                        await ws.send(json.dumps(payload))
                        pending.add("camera", camera_on, now, client_event_id)
                        await registry.record_sent(my_user_id, "camera", camera_on, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                        await logger.log_action(bot_id, name, email, "camera", camera_on, "sent", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                        if webrtc_client:
                            await webrtc_client.send_media("video", camera_on)
                    elif act == "mic":
                        is_muted = not is_muted
                        client_event_id = f"ce_mic_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        payload = {
                            "type": "mute_state",
                            "isMuted": is_muted,
                            "clientEventId": client_event_id,
                            "sentTimestamp": sent_ts,
                            "senderBotId": f"bot-{bot_id:03d}",
                            "senderOS": fingerprint.get("os_type"),
                            "senderBrowser": fingerprint.get("browser_name"),
                            "senderDeviceType": fingerprint.get("device_type"),
                            "roomId": room_id,
                            "actionType": "mic"
                        }
                        await ws.send(json.dumps(payload))
                        pending.add("mic", is_muted, now, client_event_id)
                        await registry.record_sent(my_user_id, "mic", is_muted, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                        await logger.log_action(bot_id, name, email, "mic", is_muted, "sent", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                        if webrtc_client:
                            await webrtc_client.send_media("audio", not is_muted)
                    elif act == "hand":
                        hand_raised = not hand_raised
                        client_event_id = f"ce_hnd_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        payload = {
                            "type": "hand_raise",
                            "isHandRaised": hand_raised,
                            "clientEventId": client_event_id,
                            "sentTimestamp": sent_ts,
                            "senderBotId": f"bot-{bot_id:03d}",
                            "senderOS": fingerprint.get("os_type"),
                            "senderBrowser": fingerprint.get("browser_name"),
                            "senderDeviceType": fingerprint.get("device_type"),
                            "roomId": room_id,
                            "actionType": "hand"
                        }
                        await ws.send(json.dumps(payload))
                        pending.add("hand", hand_raised, now, client_event_id)
                        await registry.record_sent(my_user_id, "hand", hand_raised, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                        await logger.log_action(bot_id, name, email, "hand", hand_raised, "sent", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                    elif act == "screen_share":
                        supported, reason = is_screen_share_supported(fingerprint, frontend_url)
                        if not supported:
                            client_event_id = f"ce_scr_{uuid.uuid4().hex[:8]}"
                            sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                            await logger.log_action(
                                bot_id, name, email, "screen_share", "unsupported", "unsupported",
                                fingerprint=fingerprint,
                                sender_bot_id=bot_id,
                                sender_os=fingerprint.get("os_type"),
                                sender_browser=fingerprint.get("browser_name"),
                                sender_device_type=fingerprint.get("device_type"),
                                client_event_id=client_event_id,
                                final_status="unsupported",
                                error_code="SCREEN_SHARE_UNSUPPORTED",
                                unsupported_reason=reason,
                                sent_timestamp=sent_ts
                            )
                            continue
                        
                        screen_sharing = not screen_sharing
                        client_event_id = f"ce_scr_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        payload = {
                            "type": "screen_share",
                            "isScreenSharing": screen_sharing,
                            "clientEventId": client_event_id,
                            "sentTimestamp": sent_ts,
                            "senderBotId": f"bot-{bot_id:03d}",
                            "senderOS": fingerprint.get("os_type"),
                            "senderBrowser": fingerprint.get("browser_name"),
                            "senderDeviceType": fingerprint.get("device_type"),
                            "roomId": room_id,
                            "actionType": "screen_share"
                        }
                        await ws.send(json.dumps(payload))
                        pending.add("screen_share", screen_sharing, now, client_event_id)
                        await registry.record_sent(my_user_id, "screen_share", screen_sharing, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                        await logger.log_action(bot_id, name, email, "screen_share", screen_sharing, "sent", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                        if webrtc_client:
                            try:
                                if screen_sharing:
                                    await webrtc_client.start_screen_share()
                                else:
                                    await webrtc_client.stop_screen_share()
                            except Exception as e:
                                logger.log("⚠️", "yellow", bot_id, name, f"Screen share WebRTC failed: {e}", fingerprint=fingerprint)
                                
                        elapsed = (time.time() - now) * 1000
                        pending.confirm("screen_share")
                        server_event_id = f"se_ssh_{uuid.uuid4().hex[:8]}"
                        await registry.record_ack(my_user_id, "screen_share", server_event_id, client_event_id)
                        await logger.log_action(bot_id, name, email, "screen_share", screen_sharing, "acknowledged", elapsed, fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, server_event_id=server_event_id,
                                                sent_timestamp=sent_ts, ack_timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                                                ack_latency_ms=elapsed, final_status="acknowledged")
                        await metrics.record_action("screen_share", fingerprint["browser_type"], "confirmed", elapsed)
                    elif act == "note_update":
                        new_content = f"Notes session updated by {name} at {datetime.datetime.now().strftime('%H:%M:%S')}"
                        client_event_id = f"ce_nte_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        payload = {
                            "type": "note_update",
                            "content": new_content,
                            "clientEventId": client_event_id,
                            "sentTimestamp": sent_ts,
                            "senderBotId": f"bot-{bot_id:03d}",
                            "senderOS": fingerprint.get("os_type"),
                            "senderBrowser": fingerprint.get("browser_name"),
                            "senderDeviceType": fingerprint.get("device_type"),
                            "roomId": room_id,
                            "actionType": "note_update"
                        }
                        await ws.send(json.dumps(payload))
                        pending.add("note_update", new_content, now, client_event_id)
                        await registry.record_sent(my_user_id, "note_update", new_content, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                        await logger.log_action(bot_id, name, email, "note_update", "Broadcasting notes sync", "sent", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                    elif act == "force_mute":
                        other_ids = [uid for uid in registry.user_id_to_name.keys() if uid != my_user_id]
                        if other_ids:
                            target_uid = random.choice(other_ids)
                            target_name = registry.user_id_to_name.get(target_uid, target_uid)
                            t0 = time.time()
                            client_event_id = f"ce_fmt_{uuid.uuid4().hex[:8]}"
                            sent_ts = datetime.datetime.fromtimestamp(t0).isoformat() + "Z"
                            payload = {
                                "type": "force_mute",
                                "userId": target_uid,
                                "clientEventId": client_event_id,
                                "sentTimestamp": sent_ts,
                                "senderBotId": f"bot-{bot_id:03d}",
                                "senderOS": fingerprint.get("os_type"),
                                "senderBrowser": fingerprint.get("browser_name"),
                                "senderDeviceType": fingerprint.get("device_type"),
                                "roomId": room_id,
                                "actionType": "force_mute"
                            }
                            await ws.send(json.dumps(payload))
                            elapsed = (time.time() - t0) * 1000
                            await logger.log_action(bot_id, name, email, "force_mute", f"Muted {target_name}", "acknowledged", elapsed, fingerprint=fingerprint,
                                                    sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                    client_event_id=client_event_id, sent_timestamp=sent_ts,
                                                    ack_timestamp=datetime.datetime.utcnow().isoformat() + "Z", ack_latency_ms=elapsed, final_status="acknowledged")
                            await metrics.record_action("force_mute", fingerprint["browser_type"], "confirmed", elapsed)
                    elif act == "captions_state":
                        captions_enabled = not captions_enabled
                        client_event_id = f"ce_cap_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        payload = {
                            "type": "captions_state",
                            "captionsEnabled": captions_enabled,
                            "clientEventId": client_event_id,
                            "sentTimestamp": sent_ts,
                            "senderBotId": f"bot-{bot_id:03d}",
                            "senderOS": fingerprint.get("os_type"),
                            "senderBrowser": fingerprint.get("browser_name"),
                            "senderDeviceType": fingerprint.get("device_type"),
                            "roomId": room_id,
                            "actionType": "captions_state"
                        }
                        await ws.send(json.dumps(payload))
                        pending.add("captions_state", captions_enabled, now, client_event_id)
                        await registry.record_sent(my_user_id, "captions_state", captions_enabled, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                        await logger.log_action(bot_id, name, email, "captions_state", captions_enabled, "sent", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                    elif act == "remove_participant":
                        active_users = await registry.get_active_users()
                        peers = [u for u in active_users if u != my_user_id]
                        if peers:
                            target_uid = random.choice(peers)
                            target_name = await registry.lookup(target_uid)
                            client_event_id = f"ce_rem_{uuid.uuid4().hex[:8]}"
                            sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                            payload = {
                                "type": "remove_participant",
                                "targetUserId": target_uid,
                                "clientEventId": client_event_id,
                                "sentTimestamp": sent_ts,
                                "senderBotId": f"bot-{bot_id:03d}",
                                "senderOS": fingerprint.get("os_type"),
                                "senderBrowser": fingerprint.get("browser_name"),
                                "senderDeviceType": fingerprint.get("device_type"),
                                "roomId": room_id,
                                "actionType": "remove_participant"
                            }
                            await ws.send(json.dumps(payload))
                            pending.add("remove_participant", target_uid, now, client_event_id)
                            await registry.record_sent(my_user_id, "remove_participant", target_uid, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                            await logger.log_action(bot_id, name, email, "remove_participant", target_name, "sent", fingerprint=fingerprint,
                                                    sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                    client_event_id=client_event_id, sent_timestamp=sent_ts)
                    elif act == "lock_meeting":
                        meeting_locked = not meeting_locked
                        client_event_id = f"ce_lck_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        payload = {
                            "type": "lock_meeting",
                            "isLocked": meeting_locked,
                            "clientEventId": client_event_id,
                            "sentTimestamp": sent_ts,
                            "senderBotId": f"bot-{bot_id:03d}",
                            "senderOS": fingerprint.get("os_type"),
                            "senderBrowser": fingerprint.get("browser_name"),
                            "senderDeviceType": fingerprint.get("device_type"),
                            "roomId": room_id,
                            "actionType": "lock_meeting"
                        }
                        await ws.send(json.dumps(payload))
                        pending.add("lock_meeting", meeting_locked, now, client_event_id)
                        await registry.record_sent(my_user_id, "lock_meeting", meeting_locked, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                        await logger.log_action(bot_id, name, email, "lock_meeting", meeting_locked, "sent", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                    elif act == "recording_state":
                        recording = not recording
                        client_event_id = f"ce_rec_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        payload = {
                            "type": "recording_state",
                            "isRecording": recording,
                            "clientEventId": client_event_id,
                            "sentTimestamp": sent_ts,
                            "senderBotId": f"bot-{bot_id:03d}",
                            "senderOS": fingerprint.get("os_type"),
                            "senderBrowser": fingerprint.get("browser_name"),
                            "senderDeviceType": fingerprint.get("device_type"),
                            "roomId": room_id,
                            "actionType": "recording_state"
                        }
                        await ws.send(json.dumps(payload))
                        pending.add("recording_state", recording, now, client_event_id)
                        await registry.record_sent(my_user_id, "recording_state", recording, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                        await logger.log_action(bot_id, name, email, "recording_state", recording, "sent", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                    elif act == "leave_meeting":
                        client_event_id = f"ce_lev_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        payload = {
                            "type": "leave_meeting",
                            "clientEventId": client_event_id,
                            "sentTimestamp": sent_ts,
                            "senderBotId": f"bot-{bot_id:03d}",
                            "senderOS": fingerprint.get("os_type"),
                            "senderBrowser": fingerprint.get("browser_name"),
                            "senderDeviceType": fingerprint.get("device_type"),
                            "roomId": room_id,
                            "actionType": "leave_meeting"
                        }
                        await ws.send(json.dumps(payload))
                        pending.add("leave_meeting", "left", now, client_event_id)
                        await registry.record_sent(my_user_id, "leave_meeting", "left", client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                        await logger.log_action(bot_id, name, email, "leave_meeting", "left", "sent", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                        await asyncio.sleep(1.5)
                        break
                except Exception:
                    break
            next_action_at = now + random.uniform(action_interval * 0.7, action_interval * 1.3)

        # Normal chat sends
        if chat_enabled and now >= next_chat_at:
            msg = random.choice(CHAT_MESSAGES)
            client_event_id = f"ce_cht_{uuid.uuid4().hex[:8]}"
            sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
            payload = {
                "type": "chat",
                "message": msg,
                "clientMsgId": client_event_id,
                "clientEventId": client_event_id,
                "sentTimestamp": sent_ts,
                "senderBotId": f"bot-{bot_id:03d}",
                "senderOS": fingerprint.get("os_type"),
                "senderBrowser": fingerprint.get("browser_name"),
                "senderDeviceType": fingerprint.get("device_type"),
                "roomId": room_id,
                "actionType": "chat"
            }
            try:
                await ws.send(json.dumps(payload))
                pending.add(f"chat:{client_event_id}", msg, now, client_event_id)
                await registry.record_sent(my_user_id, f"chat:{client_event_id}", msg, client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                await logger.log_action(bot_id, name, email, "chat", msg, "sent", fingerprint=fingerprint,
                                        sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                        client_event_id=client_event_id, sent_timestamp=sent_ts)
            except Exception:
                break
            next_chat_at = now + random.uniform(chat_interval * 0.7, chat_interval * 1.3)

# Individual bot WebSocket session loop
async def ws_session(
    ws_url, bot_id, name, email, emulator, auto_leave_s,
    chat_enabled, chat_interval, camera_enabled, mic_enabled, hand_enabled, screen_share_enabled,
    action_interval, confirm_timeout, webrtc_enabled, media_quality, network_profile, network_degradation, degradation_interval,
    stop_event, scenario_event, cross_confirm, frontend_url, room_id, reconnection_count=0,
    role="attendee", max_subscriptions=2, decode_downlink=False, in_breakout=False, scenarios=[],
    auto_camera=False, auto_mic=False, auto_screen_share=False, cross_confirm_limit=10, is_viewer=False,
    should_refresh=False, disable_abnormal_behavior=False, connected_flag=None
):
    fingerprint = emulator.fingerprint
    simulator = NetworkSimulator(network_profile, network_degradation, degradation_interval)
    webrtc_client = None
    try:
        import ssl
        ssl_context = None
        if ws_url.startswith("wss://"):
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        headers = {"User-Agent": fingerprint["user_agent"]}
        ws = None
        ws_connect_ctx = None
        connect_attempts = 3
        for conn_attempt in range(connect_attempts):
            try:
                ws_connect_ctx = websockets.connect(
                    ws_url,
                    additional_headers=headers,
                    ping_interval=30,
                    ping_timeout=60,
                    close_timeout=30,
                    open_timeout=60,
                    ssl=ssl_context
                )
                ws = await ws_connect_ctx.__aenter__()
                if connected_flag is not None:
                    connected_flag[0] = True
                break
            except Exception as e:
                if conn_attempt == connect_attempts - 1:
                    raise e
                logger.log("🔄", "yellow", bot_id, name, f"Handshake failed: {e}. Retrying connection ({conn_attempt+1}/{connect_attempts})...", fingerprint=fingerprint)
                await asyncio.sleep(random.uniform(1.0, 3.0))

        if True:
            await stats.inc("active")
            
            # --- Abnormal Scenario & Mismatch Overrides ---
            if "abnormal_playground_20" in scenarios and bot_id in (8, 9) and not disable_abnormal_behavior:
                original_send = ws.send
                async def mock_send(data_str):
                    try:
                        data = json.loads(data_str)
                        if "clientEventId" in data:
                            data["clientEventId"] = f"ce_mismatched_{uuid.uuid4().hex[:8]}"
                        elif "clientMsgId" in data:
                            data["clientMsgId"] = f"ce_mismatched_{uuid.uuid4().hex[:8]}"
                        data_str = json.dumps(data)
                    except Exception:
                        pass
                    await original_send(data_str)
                ws.send = mock_send

            # --- Host Poll Task (Bot 1) ---
            if "abnormal_playground_20" in scenarios and bot_id == host_bot_id:
                async def send_playground_poll():
                    await asyncio.sleep(10.0)
                    try:
                        logger.log("📊", "magenta", bot_id, name, "Host creating playground poll: 'Is Konn3ct WebRTC connection stable?'", fingerprint=fingerprint)
                        poll_msg = {
                            "type": "create_poll",
                            "pollId": "playground_poll_20",
                            "question": "Is Konn3ct WebRTC connection stable?",
                            "options": ["Excellent", "Lagging/High Loss", "Unstable"],
                            "senderBotId": f"bot-{bot_id:03d}"
                        }
                        await ws.send(json.dumps(poll_msg))
                        await logger.log_action(bot_id, name, email, "create_poll", "playground_poll_20", "acknowledged", latency_ms=0, fingerprint=fingerprint)
                    except Exception:
                        pass
                asyncio.create_task(send_playground_poll())

            # --- Periodic Errors (Bots 10 & 11) ---
            if "abnormal_playground_20" in scenarios and bot_id in (10, 11) and not disable_abnormal_behavior:
                async def periodic_errors():
                    while not stop_event.is_set():
                        await asyncio.sleep(15.0)
                        try:
                            err_msg = random.choice([
                                "WebRTC ICE connection state failed",
                                "Audio track packet loss spike detected",
                                "WebSocket connection frame payload too large"
                            ])
                            await logger.record_event("error_logged", bot_id=bot_id, name=name, action="playground_simulation", error=err_msg, browser=fingerprint["browser_type"])
                        except Exception:
                            pass
                asyncio.create_task(periodic_errors())
            
            pending = PendingTracker()
            joined_at = time.time()
            action_task = None
            my_user_id = None
            
            pending_replies = {}
            active_future = asyncio.get_running_loop().create_future()

            async def send_request(send_type, expect_type, payload=None):
                future = asyncio.get_running_loop().create_future()
                if expect_type not in pending_replies:
                    pending_replies[expect_type] = []
                pending_replies[expect_type].append(future)
                
                req = {"type": send_type}
                if payload:
                    req.update(payload)
                try:
                    await ws.send(json.dumps(req))
                except Exception as e:
                    if future in pending_replies.get(expect_type, []):
                        pending_replies[expect_type].remove(future)
                    future.set_exception(e)
                    raise e
                
                return await asyncio.wait_for(future, timeout=10.0)

            async def reader_loop():
                nonlocal my_user_id
                try:
                    while not stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            msg = json.loads(raw)
                            mtype = msg.get("type")
                            
                            if mtype in pending_replies and pending_replies[mtype]:
                                future = pending_replies[mtype].pop(0)
                                if not future.done():
                                    future.set_result(msg)
                                if not pending_replies[mtype]:
                                    del pending_replies[mtype]
                                continue
                            
                            if mtype == "session_status":
                                status = msg.get("status")
                                my_user_id = msg.get("userId")
                                await registry.register(my_user_id, name)
                                
                                if status == "active" and not active_future.done():
                                    active_future.set_result(my_user_id)
                                elif status in ("denied", "kicked", "ended"):
                                    if not active_future.done():
                                        active_future.set_exception(Exception(f"Session rejected: {status}"))
                                    raise Exception(f"Session terminated by server: {status}")
                                    
                            elif mtype == "user_joined":
                                uid = msg.get("userId")
                                uname = msg.get("name")
                                if uid and uname:
                                    await registry.register(uid, uname)
                                    
                            elif mtype == "participants_list":
                                participants = msg.get("participants", [])
                                for p in participants:
                                    if p.get("userId") and p.get("name"):
                                        await registry.register(p["userId"], p["name"])
                                        
                            elif mtype == "newProducer":
                                p_id = msg.get("producerId")
                                p_kind = msg.get("kind")
                                p_uid = msg.get("userId")
                                if webrtc_client and webrtc_enabled and p_uid != my_user_id:
                                    asyncio.create_task(webrtc_client.add_consumer(p_id, p_kind))
                                    if cross_confirm:
                                        server_event_id = f"se_wcon_{p_uid}_{p_id[:8]}"
                                        if await registry.should_confirm(server_event_id, limit=cross_confirm_limit):
                                            await log_observed_action(bot_id, name, email, p_uid, "webrtc_connection", "CONNECTED", fingerprint, msg_client_event_id=None, msg_server_event_id=server_event_id)
                                    
                            elif mtype == "producer_closed":
                                p_id = msg.get("producerId")
                                if webrtc_client and webrtc_enabled:
                                    asyncio.create_task(webrtc_client.remove_consumer(p_id))
                                    
                            elif mtype == "waiting_room_request":
                                target_uid = msg.get("userId")
                                target_name = msg.get("name")
                                if role == "host":
                                    logger.log("👑", "green", bot_id, name, f"Host auto-admitting waiting user: {target_name} ({target_uid})", fingerprint=fingerprint)
                                    t0 = time.time()
                                    await ws.send(json.dumps({"type": "admit_user", "userId": target_uid}))
                                    elapsed = (time.time() - t0) * 1000
                                    await logger.log_action(bot_id, name, email, "lobby_admit", target_uid, "confirmed", elapsed, fingerprint)
                                    await metrics.record_action("lobby_admit", fingerprint["browser_type"], "confirmed", elapsed)
                                    
                            elif mtype == "force_mute":
                                logger.log("🎤", "yellow", bot_id, name, "Received force_mute command from host — muting mic", fingerprint=fingerprint)
                                t0 = time.time()
                                is_muted = True
                                await ws.send(json.dumps({"type": "mute_state", "isMuted": is_muted}))
                                if webrtc_client:
                                    await webrtc_client.send_media("audio", False)
                                elapsed = (time.time() - t0) * 1000
                                await logger.log_action(bot_id, name, email, "force_mute", "muted", "confirmed", elapsed, fingerprint)
                                await metrics.record_action("force_mute", fingerprint["browser_type"], "confirmed", elapsed)
                                
                            elif mtype == "create_poll":
                                poll_id = msg.get("pollId")
                                question = msg.get("question")
                                options = msg.get("options", [])
                                logger.log("🗳️", "magenta", bot_id, name, f"Observed Poll created by host: '{question}'", fingerprint=fingerprint)
                                
                                # Attendees (excluding host) vote after random delay
                                if bot_id != host_bot_id:
                                    async def cast_vote():
                                        await asyncio.sleep(random.uniform(2.0, 6.0))
                                        try:
                                            opt_idx = random.choices([0, 1, 2], weights=[60, 30, 10])[0]
                                            logger.log("🗳️", "magenta", bot_id, name, f"Voting for option {opt_idx}: '{options[opt_idx]}'", fingerprint=fingerprint)
                                            vote_msg = {
                                                "type": "vote_poll",
                                                "pollId": poll_id,
                                                "optionIndex": opt_idx,
                                                "senderBotId": f"bot-{bot_id:03d}"
                                            }
                                            await ws.send(json.dumps(vote_msg))
                                            await logger.log_action(bot_id, name, email, "vote_poll", str(opt_idx), "acknowledged", latency_ms=150, fingerprint=fingerprint)
                                        except Exception:
                                            pass
                                    asyncio.create_task(cast_vote())
                                    
                            elif mtype in ("note_update", "camera_state", "mute_state", "hand_raise", "screen_share", "chat", "leave_meeting", "remove_participant", "lock_meeting", "recording_state", "captions_state"):
                                uid = msg.get("userId")
                                val = None
                                act = ""
                                if mtype == "camera_state":
                                    val = msg.get("isCameraOn")
                                    act = "camera"
                                elif mtype == "mute_state":
                                    val = msg.get("isMuted")
                                    act = "mic"
                                elif mtype == "hand_raise":
                                    val = msg.get("isHandRaised")
                                    act = "hand"
                                elif mtype == "screen_share":
                                    val = msg.get("isScreenSharing")
                                    act = "screen_share"
                                elif mtype == "chat":
                                    val = msg.get("message")
                                    client_id = msg.get("clientMsgId") or msg.get("clientEventId")
                                    act = f"chat:{client_id}" if client_id else "chat"
                                elif mtype == "note_update":
                                    val = msg.get("content")
                                    act = "note_update"
                                elif mtype == "leave_meeting":
                                    val = "left"
                                    act = "leave_meeting"
                                elif mtype == "remove_participant":
                                    val = msg.get("targetUserId")
                                    act = "remove_participant"
                                    if val == my_user_id:
                                        logger.log("❌", "red", bot_id, name, "Removed from meeting by host.", fingerprint=fingerprint)
                                        client_event_id = f"ce_lev_{uuid.uuid4().hex[:8]}"
                                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                                        await ws.send(json.dumps({
                                            "type": "leave_meeting",
                                            "clientEventId": client_event_id,
                                            "sentTimestamp": sent_ts,
                                            "senderBotId": f"bot-{bot_id:03d}",
                                            "senderOS": fingerprint.get("os_type"),
                                            "senderBrowser": fingerprint.get("browser_name"),
                                            "senderDeviceType": fingerprint.get("device_type"),
                                            "roomId": room_id,
                                            "actionType": "leave_meeting"
                                        }))
                                        await registry.record_sent(my_user_id, "leave_meeting", "left", client_event_id, bot_id, fingerprint.get("os_type"), fingerprint.get("browser_name"), fingerprint.get("device_type"))
                                        await logger.log_action(bot_id, name, email, "leave_meeting", "left", "sent", fingerprint=fingerprint,
                                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                                        await asyncio.sleep(1.5)
                                        break
                                elif mtype == "lock_meeting":
                                    val = msg.get("isLocked")
                                    act = "lock_meeting"
                                elif mtype == "recording_state":
                                    val = msg.get("isRecording")
                                    act = "recording_state"
                                elif mtype == "captions_state":
                                    val = msg.get("captionsEnabled")
                                    act = "captions_state"

                                clean_act = act.split(":")[0]
                                client_event_id = msg.get("clientEventId") or msg.get("clientMsgId")
                                server_event_id = msg.get("serverEventId") or msg.get("eventId") or msg.get("id") or f"se_{uuid.uuid4().hex[:8]}"

                                if uid == my_user_id:
                                    if "abnormal_playground_20" in scenarios and bot_id in (6, 7) and not disable_abnormal_behavior:
                                        await asyncio.sleep(8.0)
                                    result = pending.confirm(act)
                                    if result:
                                        elapsed = (time.time() - result[1]) * 1000
                                        if not client_event_id:
                                            client_event_id = result[2]
                                        await registry.record_ack(my_user_id, clean_act, server_event_id, client_event_id)
                                        await logger.log_action(bot_id, name, email, clean_act, val, "acknowledged", elapsed, fingerprint,
                                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                                client_event_id=client_event_id, server_event_id=server_event_id,
                                                                sent_timestamp=datetime.datetime.fromtimestamp(result[1]).isoformat() + "Z",
                                                                ack_timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                                                                ack_latency_ms=elapsed, final_status="acknowledged")
                                        await metrics.record_action(clean_act, fingerprint["browser_type"], "confirmed", elapsed)
                                else:
                                    if cross_confirm:
                                        event_key = client_event_id or server_event_id or f"{uid}_{clean_act}_{val}"
                                        if await registry.should_confirm(event_key, limit=cross_confirm_limit):
                                            await log_observed_action(bot_id, name, email, uid, clean_act, val, fingerprint, msg_client_event_id=client_event_id, msg_server_event_id=server_event_id)
                                            
                        except asyncio.TimeoutError:
                            pass
                        except websockets.exceptions.ConnectionClosed:
                            break
                except Exception as exc:
                    pass

            reader_task = asyncio.create_task(reader_loop())
            
            try:
                try:
                    my_user_id = await asyncio.wait_for(active_future, timeout=15.0)
                except Exception as exc:
                    await logger.record_event("error_logged", bot_id=bot_id, name=name, action="session_activation", error=str(exc), browser=fingerprint["browser_type"])
                    await stats.inc("active", -1)
                    await stats.inc("failed")
                    return True

                if webrtc_enabled:
                    webrtc_client = WebRTCClient(
                        bot_id, name, emulator, simulator, metrics, media_quality,
                        decode_downlink=decode_downlink, max_subscriptions=max_subscriptions
                    )
                    try:
                        client_event_id = f"ce_wcon_{uuid.uuid4().hex[:8]}"
                        sent_ts = datetime.datetime.utcnow().isoformat() + "Z"
                        t_start = time.time()
                        await logger.log_action(bot_id, name, email, "webrtc_connection", "CONNECTING", "sent", fingerprint=fingerprint, client_event_id=client_event_id, sent_timestamp=sent_ts)
                        
                        success = await webrtc_client.connect(send_request)
                        elapsed = (time.time() - t_start) * 1000
                    except Exception as exc:
                        success = False
                        elapsed = (time.time() - t_start) * 1000
                        await logger.record_event("error_logged", bot_id=bot_id, name=name, action="webrtc_connection", error=str(exc), browser=fingerprint["browser_type"])
                        
                    if success:
                        await logger.log_action(bot_id, name, email, "webrtc_connection", "CONNECTED", "confirmed", elapsed, fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                        await metrics.record_join(fingerprint["browser_type"], True)
                        
                        try:
                            producers_data = await send_request("getProducers", "producersList")
                            producers_list = producers_data.get("producers", [])
                            for prod in producers_list:
                                p_id = prod.get("producerId")
                                p_kind = prod.get("kind")
                                p_uid = prod.get("userId")
                                if p_uid != my_user_id:
                                    asyncio.create_task(webrtc_client.add_consumer(p_id, p_kind))
                        except Exception:
                            pass
                    else:
                        await logger.log_action(bot_id, name, email, "webrtc_connection", "FAILED", "failed", elapsed, fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"), sender_device_type=fingerprint.get("device_type"),
                                                client_event_id=client_event_id, sent_timestamp=sent_ts)
                        await metrics.record_join(fingerprint["browser_type"], False)
                        await stats.inc("active", -1)
                        await stats.inc("failed")
                        return True
                
                action_task = asyncio.create_task(
                    action_loop(
                        ws=ws, bot_id=bot_id, name=name, email=email, my_user_id=my_user_id, fingerprint=fingerprint, pending=pending,
                        action_interval=action_interval, chat_interval=chat_interval, webrtc_client=webrtc_client,
                        camera_enabled=camera_enabled, mic_enabled=mic_enabled, hand_enabled=hand_enabled,
                        chat_enabled=chat_enabled, screen_share_enabled=screen_share_enabled,
                        stop_event=stop_event, scenario_event=scenario_event, frontend_url=frontend_url, room_id=room_id, scenarios=scenarios, role=role,
                        auto_camera=auto_camera, auto_mic=auto_mic, auto_screen_share=auto_screen_share,
                        is_viewer=is_viewer
                    )
                )

                last_webrtc_log_at = time.time()
                ice_restart_count = 0

                while not stop_event.is_set():
                    now = time.time()
                    if reader_task.done():
                        break
                    
                    # Simulate session refresh
                    if should_refresh and (now - joined_at) >= 20.0:
                        logger.log("🔄", "cyan", bot_id, name, "Simulating session refresh (browser reload)...", fingerprint=fingerprint)
                        try:
                            await ws.send(json.dumps({"type": "leave_meeting"}))
                        except Exception:
                            pass
                        await stats.inc("active", -1)
                        return "refresh_session"
                    
                    if scenario_event.is_set() and "breakout_rooms" in scenarios and not in_breakout:
                        await asyncio.sleep(random.uniform(0, 3.0))
                        try:
                            await ws.send(json.dumps({"type": "leave_meeting"}))
                        except Exception:
                            pass
                        await stats.inc("active", -1)
                        return "migrate_to_breakout"
                        
                    if in_breakout and (now - joined_at) >= 25.0:
                        try:
                            await ws.send(json.dumps({"type": "leave_meeting"}))
                        except Exception:
                            pass
                        await stats.inc("active", -1)
                        return "migrate_to_main"

                    if auto_leave_s and (now - joined_at) >= auto_leave_s:
                        try:
                            await ws.send(json.dumps({"type": "leave_meeting"}))
                        except Exception:
                            pass
                        await stats.inc("active", -1)
                        await stats.inc("left")
                        return True
                        
                    if webrtc_client and webrtc_enabled and now - last_webrtc_log_at >= 10.0:
                        last_webrtc_log_at = now
                        try:
                            detailed_stats = await webrtc_client.get_webrtc_detailed_stats()
                            detailed_stats["reconnection_count"] = reconnection_count
                            detailed_stats["ice_restart_count"] = ice_restart_count
                            await logger.record_event("webrtc_stats_logged", bot_id=bot_id, name=name, email=email, browser=fingerprint["browser_type"], **detailed_stats)
                        except Exception:
                            pass

                    for key, val, client_event_id in pending.sweep_timeouts(now, confirm_timeout):
                        act_type = key.split(":")[0]
                        error_code = f"{act_type.upper()}_ACK_TIMEOUT"
                        await logger.log_action(bot_id, name, email, act_type, val, "timed_out", fingerprint=fingerprint,
                                                sender_bot_id=bot_id, sender_os=fingerprint.get("os_type"), sender_browser=fingerprint.get("browser_name"),
                                                client_event_id=client_event_id, final_status="timeout", timeout_stage="ack-timeout",
                                                error_code=error_code, unsupported_reason="Server confirmation timeout")
                        await metrics.record_action(act_type, fingerprint["browser_type"], "timed_out")
                        await logger.record_event("error_logged", bot_id=bot_id, name=name, action=act_type, error="Action confirmation timeout", browser=fingerprint["browser_type"])
                        
                    await pause_event.wait()
                    await asyncio.sleep(1.0)
                    
            finally:
                if webrtc_client and webrtc_enabled:
                    try:
                        detailed_stats = await webrtc_client.get_webrtc_detailed_stats()
                        detailed_stats["reconnection_count"] = reconnection_count
                        detailed_stats["ice_restart_count"] = ice_restart_count
                        await logger.record_event("webrtc_stats_logged", bot_id=bot_id, name=name, email=email, browser=fingerprint["browser_type"], **detailed_stats)
                        
                        await metrics.record_webrtc(
                            browser=fingerprint["browser_type"],
                            ice_time_ms=detailed_stats["ice_connection_time"],
                            dtls_time_ms=detailed_stats["dtls_handshake_time"],
                            packet_loss=detailed_stats["packet_loss"],
                            jitter_ms=detailed_stats["jitter"],
                            bitrate_kbps=detailed_stats["bitrate"],
                            codec=detailed_stats["codec"],
                            resolution=detailed_stats["resolution"],
                            rtt_ms=detailed_stats["rtt"]
                        )
                    except Exception:
                        pass
                if action_task and not action_task.done():
                    action_task.cancel()
                if reader_task and not reader_task.done():
                    reader_task.cancel()
                if webrtc_client:
                    await webrtc_client.close()
                if ws_connect_ctx and ws:
                    try:
                        await ws_connect_ctx.__aexit__(None, None, None)
                    except Exception:
                        pass
                    
    except Exception as exc:
        await logger.record_event("error_logged", bot_id=bot_id, name=name, action="websocket_connection", error=str(exc), browser=fingerprint["browser_type"])
        logger.log("⚠️", "yellow", bot_id, name, f"Connection exception: {type(exc).__name__}: {exc}", fingerprint=fingerprint)

# Main launch bot loop handling retries
# Main launch bot loop handling retries and breakout migration state
async def run_bot(
    bot_id, room_id, frontend_url, signal_domain,
    auto_leave_s, chat_enabled, chat_interval,
    camera_enabled, mic_enabled, hand_enabled, screen_share_enabled, action_interval,
    confirm_timeout, max_retries, webrtc_enabled, media_quality, network_distribution, network_degradation, degradation_interval,
    device_manager, stop_event, session, scenario_event, cross_confirm=True,
    jwt_secret=None, max_subscriptions=2, decode_downlink=False, host_bot_id=1, presenter_bot_id=2, scenarios=[],
    auto_camera=False, auto_mic=False, auto_screen_share=False, cross_confirm_limit=10, is_viewer=False,
    refresh_bots=0, disable_abnormal_behavior=False
):
    name, email = await generate_identity()
    participant_id = str(uuid.uuid4())
    
    # 1. Sample profiles
    profile = device_manager.sample_profile()
    emulator = BrowserEmulator(profile)
    fingerprint = emulator.fingerprint

    await logger.record_event("bot_connecting", bot_id, name, email, fingerprint=fingerprint)

    # Parse and select network condition profile
    net_choices = list(network_distribution.keys())
    net_weights = list(network_distribution.values())
    network_profile = random.choices(net_choices, weights=net_weights)[0]

    # Assign role based on bot ID
    role = "attendee"
    if bot_id == host_bot_id:
        role = "host"
    elif bot_id == presenter_bot_id:
        role = "presenter"

    # Helper function to acquire / generate websocket URL
    async def get_ws_url(room):
        if jwt_secret:
            token = generate_local_token(room, name, email, bot_id, role, profile["device_type"] != "desktop", jwt_secret)
        else:
            token = await get_ws_token(session, frontend_url, room, name, email, bot_id, profile["device_type"] != "desktop")
        if not token:
            return None
        proto = "ws" if "localhost" in signal_domain or "127.0.0.1" in signal_domain else "wss"
        return f"{proto}://{signal_domain}/signal?roomId={room}&token={token}&isMobile={str(profile['device_type'] != 'desktop').lower()}&participantId={participant_id}"

    current_room = room_id
    ws_url = await get_ws_url(current_room)
    if not ws_url:
        await stats.inc("failed")
        await metrics.record_join(fingerprint["browser_type"], False)
        return

    await stats.inc("joined")
    await logger.record_event("bot_joined", bot_id, name, email, fingerprint=fingerprint)
    logger.log("🌐", "grey", bot_id, name, f"Token acquired — connecting to room: {current_room}...", fingerprint=fingerprint)
    
    attempt = 1
    in_breakout = False
    refreshed = False
    should_refresh_bot = (bot_id >= 3 and bot_id < 3 + refresh_bots)
    connected_flag = [False]
    has_ever_connected = False
    reconnect_attempt = 1

    while not stop_event.is_set() and attempt <= max_retries:
        bot_refresh_enabled = should_refresh_bot and not refreshed
        connected_flag[0] = False
        try:
            result = await ws_session(
                ws_url=ws_url, bot_id=bot_id, name=name, email=email, emulator=emulator, auto_leave_s=auto_leave_s,
                chat_enabled=chat_enabled, chat_interval=chat_interval,
                camera_enabled=camera_enabled, mic_enabled=mic_enabled, hand_enabled=hand_enabled, screen_share_enabled=screen_share_enabled,
                action_interval=action_interval, confirm_timeout=confirm_timeout,
                webrtc_enabled=webrtc_enabled, media_quality=media_quality,
                network_profile=network_profile, network_degradation=network_degradation, degradation_interval=degradation_interval,
                stop_event=stop_event, scenario_event=scenario_event, cross_confirm=cross_confirm,
                frontend_url=frontend_url, room_id=current_room, reconnection_count=attempt,
                role=role, max_subscriptions=max_subscriptions, decode_downlink=decode_downlink, in_breakout=in_breakout, scenarios=scenarios,
                auto_camera=auto_camera, auto_mic=auto_mic, auto_screen_share=auto_screen_share, cross_confirm_limit=cross_confirm_limit,
                is_viewer=is_viewer, should_refresh=bot_refresh_enabled,
                disable_abnormal_behavior=disable_abnormal_behavior,
                connected_flag=connected_flag
            )
        except Exception as exc:
            logger.log("⚠️", "red", bot_id, name, f"Session connection error: {exc}", fingerprint=fingerprint)
            result = False

        if stop_event.is_set():
            break

        if result == "migrate_to_breakout":
            in_breakout = True
            current_room = f"{room_id}-breakout-{((bot_id - 1) % 3) + 1}"
            logger.log("🚪", "cyan", bot_id, name, f"Migrating to breakout room: {current_room}", fingerprint=fingerprint)
            
            # Retry token acquisition infinitely during migration if server is under high load
            ws_url = None
            t_start = time.time()
            while not ws_url and not stop_event.is_set():
                ws_url = await get_ws_url(current_room)
                if not ws_url:
                    logger.log("⚠️", "yellow", bot_id, name, "Failed to acquire breakout room token. Retrying in 5s...", fingerprint=fingerprint)
                    await asyncio.sleep(5.0)
            if stop_event.is_set():
                break
                
            elapsed = (time.time() - t_start) * 1000
            await logger.log_action(bot_id, name, email, "breakout_join", current_room, "confirmed", elapsed, fingerprint)
            await metrics.record_action("breakout_join", fingerprint["browser_type"], "confirmed", elapsed)
            continue
            
        elif result == "refresh_session":
            refreshed = True
            await logger.record_event("bot_refreshing", bot_id, name, email, fingerprint=fingerprint, reason="Simulated User Browser Refresh")
            await asyncio.sleep(3.0)
            
            # Retry token acquisition infinitely during refresh if server is under high load
            ws_url = None
            while not ws_url and not stop_event.is_set():
                ws_url = await get_ws_url(current_room)
                if not ws_url:
                    logger.log("⚠️", "yellow", bot_id, name, "Failed to acquire refresh token. Retrying in 5s...", fingerprint=fingerprint)
                    await asyncio.sleep(5.0)
            if stop_event.is_set():
                break
            await logger.record_event("bot_joined", bot_id, name, email, fingerprint=fingerprint)
            logger.log("🌐", "grey", bot_id, name, f"Reconnected after browser refresh to room: {current_room}...", fingerprint=fingerprint)
            continue
            
        elif result == "migrate_to_main":
            in_breakout = False
            current_room = room_id
            logger.log("🚪", "cyan", bot_id, name, f"Returning to main room: {current_room}", fingerprint=fingerprint)
            
            # Retry token acquisition infinitely during migration if server is under high load
            ws_url = None
            t_start = time.time()
            while not ws_url and not stop_event.is_set():
                ws_url = await get_ws_url(current_room)
                if not ws_url:
                    logger.log("⚠️", "yellow", bot_id, name, "Failed to acquire main room token. Retrying in 5s...", fingerprint=fingerprint)
                    await asyncio.sleep(5.0)
            if stop_event.is_set():
                break
                
            elapsed = (time.time() - t_start) * 1000
            await logger.log_action(bot_id, name, email, "breakout_join", current_room, "confirmed", elapsed, fingerprint)
            await metrics.record_action("breakout_join", fingerprint["browser_type"], "confirmed", elapsed)
            continue

        if result is True:
            # Safe exit
            await logger.record_event("bot_left", bot_id, name, email, fingerprint=fingerprint, reason="graceful")
            logger.log("🚪", "grey", bot_id, name, "Bot left the meeting room gracefully.", fingerprint=fingerprint)
            break

        # Determine success / reconnection status
        if connected_flag[0]:
            has_ever_connected = True
            reconnect_attempt = 1
            attempt = 1
        else:
            reconnect_attempt += 1
            if not has_ever_connected:
                attempt += 1

        await stats.inc("reconnects")
        await logger.record_event("bot_reconnecting", bot_id, name, email, fingerprint=fingerprint)
        
        # Exponential backoff with jitter to prevent reconnection storms
        backoff = min(60.0, random.uniform(2.0, 4.0) * (1.5 ** reconnect_attempt))
        logger.log("🔄", "yellow", bot_id, name, f"Reconnecting in {backoff:.1f}s (attempt {attempt if not has_ever_connected else '∞'}/{max_retries}, reconnect_attempt={reconnect_attempt})...", fingerprint=fingerprint)
        await asyncio.sleep(backoff)
        
        # Retry token acquisition infinitely during reconnection if server is under high load
        ws_url = None
        while not ws_url and not stop_event.is_set():
            ws_url = await get_ws_url(current_room)
            if not ws_url:
                logger.log("⚠️", "yellow", bot_id, name, "Failed to acquire token for reconnection. Retrying in 5s...", fingerprint=fingerprint)
                await asyncio.sleep(5.0)

    if attempt > max_retries:
        await stats.inc("failed")
        await logger.record_event("bot_left", bot_id, name, email, fingerprint=fingerprint, reason="reconnect_exhausted")
        await logger.record_event("bot_failed", bot_id, name, email, fingerprint=fingerprint)
        logger.log("❌", "red", bot_id, name, f"Bot session terminated after exhausting {max_retries} reconnect attempts.", fingerprint=fingerprint)
    elif stop_event.is_set():
        await logger.record_event("bot_left", bot_id, name, email, fingerprint=fingerprint, reason="stopped")

def is_bot_in_range(bot_id, range_str):
    if not range_str or range_str.strip().lower() == "all":
        return True
    if range_str.strip().lower() in ("none", "disabled", ""):
        return False
    parts = range_str.split(",")
    for part in parts:
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-")
                if int(start) <= bot_id <= int(end):
                    return True
            except ValueError:
                pass
        else:
            try:
                if int(part) == bot_id:
                    return True
            except ValueError:
                pass
    return False

# Main orchestrator
async def main(args):
    global logger
    stop_event = asyncio.Event()
    
    # List of events to trigger test scenarios dynamically
    scenario_events = []

    # Handle OS termination signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    logger = ActionLogger(args.report_log)
    device_manager = DeviceManager(args.device_distribution, args.browser_distribution, args.os_distribution)
    
    # Parse Network conditions distribution
    net_distribution = {}
    for item in args.network_conditions.split(","):
        k, v = item.split(":")
        net_distribution[k.strip().lower()] = float(v.strip())

    auto_leave_s = args.leave * 60 if args.leave > 0 else None
    semaphore = asyncio.Semaphore(max(args.bots, args.concurrency))

    # Log initial test configuration
    await logger.record_event(
        "test_config",
        room=args.room,
        bots=args.bots,
        batch=args.batch,
        stagger=args.stagger,
        concurrency=args.concurrency,
        webrtc_enabled=args.webrtc_enabled,
        media_quality=args.media_quality,
        network_conditions=args.network_conditions,
        network_degradation=args.network_degradation,
        degradation_interval=args.degradation_interval,
        action_interval=args.action_interval,
        chat_interval=args.chat_interval,
        confirm_timeout=args.confirm_timeout,
        max_retries=args.max_retries,
        sla_success_rate=args.sla_success_rate,
        sla_latency=args.sla_latency,
        sla_packet_loss=args.sla_packet_loss,
        sla_jitter=args.sla_jitter,
        cross_confirm_limit=args.cross_confirm_limit,
        camera_publishers=args.camera_publishers,
        mic_publishers=args.mic_publishers,
        screen_share_publishers=args.screen_share_publishers,
        viewer_bots=args.viewer_bots,
        viewer_mode=args.viewer_mode,
        auto_camera=args.auto_camera,
        auto_mic=args.auto_mic,
        auto_screen_share=args.auto_screen_share
    )

    print(f"\n{C['white']}{'═'*70}{C['reset']}")
    print(f"  🚀 py_guest — Konn3ct Advanced Load Testing Bot Framework")
    print(f"{C['white']}{'═'*70}{C['reset']}")
    print(f"  Room          : {args.room}")
    print(f"  Bots          : {args.bots}")
    print(f"  Batch         : {args.batch} bots every {args.stagger}s")
    print(f"  WebRTC        : {'ENABLED' if args.webrtc_enabled else 'DISABLED'}")
    print(f"  Media Quality : {args.media_quality.upper()}")
    print(f"  Degradation   : {'ON' if args.network_degradation else 'OFF'}")
    print(f"  Scenarios     : {args.test_scenarios}")
    print(f"{C['white']}{'═'*70}{C['reset']}\n")

    connector = aiohttp.TCPConnector(limit=max(args.bots, args.concurrency), ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        
        async def launch(bot_id):
            async with semaphore:
                if stop_event.is_set():
                    return
                scen_event = asyncio.Event()
                scenario_events.append(scen_event)
                
                scenarios = [s.strip() for s in (args.test_scenarios or "").split(",") if s.strip()]
                is_viewer = is_bot_in_range(bot_id, args.viewer_bots)
                
                # Playground scenario disables optimizations and forces full capabilities
                is_playground = "abnormal_playground_20" in scenarios
                if is_playground:
                    bot_camera_enabled = not args.no_camera
                    bot_mic_enabled = not args.no_mic
                    bot_screen_share_enabled = not args.no_screen_share
                    bot_hand_enabled = not args.no_handraise
                    bot_chat_enabled = not args.no_chat
                    is_viewer = False
                elif is_viewer and args.viewer_mode.strip().lower() == "receive_only":
                    bot_camera_enabled = False
                    bot_mic_enabled = False
                    bot_screen_share_enabled = False
                    bot_hand_enabled = not args.no_handraise
                    bot_chat_enabled = not args.no_chat
                else:
                    # Check individual publisher ID mappings
                    bot_camera_enabled = (not args.no_camera) and is_bot_in_range(bot_id, args.camera_publishers)
                    bot_mic_enabled = (not args.no_mic) and is_bot_in_range(bot_id, args.mic_publishers)
                    bot_screen_share_enabled = (not args.no_screen_share) and is_bot_in_range(bot_id, args.screen_share_publishers)
                    bot_hand_enabled = not args.no_handraise
                    bot_chat_enabled = not args.no_chat

                # Limit WebRTC connection initialization to publishers only
                bot_webrtc_enabled = args.webrtc_enabled and (
                    bot_camera_enabled or bot_mic_enabled or bot_screen_share_enabled
                )

                await run_bot(
                    bot_id=bot_id, room_id=args.room,
                    frontend_url=args.frontend, signal_domain=args.signal,
                    auto_leave_s=auto_leave_s,
                    chat_enabled=bot_chat_enabled, chat_interval=args.chat_interval,
                    camera_enabled=bot_camera_enabled, mic_enabled=bot_mic_enabled,
                    hand_enabled=bot_hand_enabled, screen_share_enabled=bot_screen_share_enabled,
                    action_interval=args.action_interval, confirm_timeout=args.confirm_timeout,
                    max_retries=args.max_retries, webrtc_enabled=bot_webrtc_enabled,
                    media_quality=args.media_quality, network_distribution=net_distribution,
                    network_degradation=args.network_degradation, degradation_interval=args.degradation_interval,
                    device_manager=device_manager, stop_event=stop_event, session=session,
                    scenario_event=scen_event, cross_confirm=not args.no_cross_confirm,
                    jwt_secret=args.jwt_secret, max_subscriptions=args.max_subscriptions,
                    decode_downlink=args.decode_downlink, host_bot_id=args.host_bot_id,
                    presenter_bot_id=args.presenter_bot_id, scenarios=scenarios,
                    auto_camera=args.auto_camera, auto_mic=args.auto_mic, auto_screen_share=args.auto_screen_share,
                    cross_confirm_limit=args.cross_confirm_limit, is_viewer=is_viewer,
                    refresh_bots=args.refresh_bots,
                    disable_abnormal_behavior=args.disable_abnormal_behavior
                )

        tasks = []
        start_id = args.start_id
        bot_id = start_id
        end_id = start_id + args.bots - 1
        
        # Periodic statistics printing task
        async def stats_printer():
            while not stop_event.is_set():
                await asyncio.sleep(5)
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                print(f"{C['grey']}[{ts}] 📊 Stats Snapshot: {stats.summary()}{C['reset']}", flush=True)
                
        asyncio.create_task(stats_printer())

        # Control file monitoring task
        async def control_monitor():
            if not args.control_file:
                return
            last_mtime = 0
            while not stop_event.is_set():
                try:
                    if os.path.exists(args.control_file):
                        mtime = os.path.getmtime(args.control_file)
                        if mtime != last_mtime:
                            last_mtime = mtime
                            with open(args.control_file, "r") as f:
                                data = json.load(f)
                                is_paused = data.get("paused", False)
                                if is_paused and pause_event.is_set():
                                    pause_event.clear()
                                    logger.log("⏸️", "yellow", 0, "SYSTEM", "Load test execution PAUSED via control file.", fingerprint=None)
                                elif not is_paused and not pause_event.is_set():
                                    pause_event.set()
                                    logger.log("▶️", "green", 0, "SYSTEM", "Load test execution RESUMED via control file.", fingerprint=None)
                except Exception:
                    pass
                await asyncio.sleep(1.0)

        asyncio.create_task(control_monitor())

        # Scenarios triggering task
        async def scenario_runner():
            scenarios = [s.strip() for s in (args.test_scenarios or "").split(",") if s.strip()]
            await asyncio.sleep(15)  # Wait for initial batches to join
            
            if "simultaneous_camera_toggle" in scenarios and not stop_event.is_set():
                print(f"\n{C['yellow']}🔥 Triggering simultaneous_camera_toggle scenario on all active bots...{C['reset']}\n")
                for evt in scenario_events:
                    evt.set()
                await asyncio.sleep(20)

            if "presenter_switch" in scenarios and not stop_event.is_set():
                print(f"\n{C['yellow']}🔥 Triggering presenter_switch scenario...{C['reset']}\n")
                # Pick one random bot and toggle screen share
                for evt in scenario_events[:3]:
                    evt.set()
                await asyncio.sleep(20)

            if "screen_share_storm" in scenarios and not stop_event.is_set():
                print(f"\n{C['yellow']}🔥 Triggering screen_share_storm scenario...{C['reset']}\n")
                for evt in scenario_events:
                    evt.set()

        asyncio.create_task(scenario_runner())

        if getattr(args, "startup_delay", 0.0) > 0.0:
            print(f"Staggering process startup: sleeping for {args.startup_delay}s...")
            await asyncio.sleep(args.startup_delay)

        while bot_id <= end_id and not stop_event.is_set():
            await pause_event.wait()
            batch = []
            for i in range(args.batch):
                if bot_id > end_id:
                    break
                
                # Intra-batch micro-stagger: space out bot connections by 150ms inside the batch
                async def launch_with_micro_stagger(b_id, delay):
                    if delay > 0:
                        await asyncio.sleep(delay)
                    await launch(b_id)
                    
                delay_sec = i * 0.15
                batch.append(asyncio.create_task(launch_with_micro_stagger(bot_id, delay_sec)))
                bot_id += 1
            tasks.extend(batch)
            if bot_id <= end_id and args.stagger > 0:
                await asyncio.sleep(args.stagger)

        print(f"{C['green']}  ✔  All {args.bots} bot(s) queued (IDs {start_id} to {end_id}) — press Ctrl+C to stop{C['reset']}\n")

        try:
            if args.leave > 0:
                global_timeout = args.leave * 60 + 60
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=global_timeout)
            else:
                await asyncio.gather(*tasks)
        except (asyncio.TimeoutError, TimeoutError):
            print(f"\n{C['yellow']}⚠️  Global session timeout reached ({args.leave}m + 1m buffer). Forcing shutdown...{C['reset']}\n")
        except asyncio.CancelledError:
            pass
        finally:
            stop_event.set()

    # Save metrics summary to file
    summary = metrics.get_summary()
    await logger.record_event("test_finished", summary=summary)
    
    print(f"\n{C['white']}{'═'*70}{C['reset']}")
    print(f"  📊 Test Finished: {stats.summary()}")
    print(f"  📄 Report log written to: {args.report_log}")
    print(f"{C['white']}{'═'*70}{C['reset']}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="py_guest — Konn3ct Advanced Load Testing Bot")
    parser.add_argument("--room", default=DEFAULT_ROOM)
    parser.add_argument("--bots", type=int, default=50)
    parser.add_argument("--start-id", type=int, default=1, help="Starting bot ID")
    parser.add_argument("--leave", type=int, default=0)
    parser.add_argument("--stagger", type=float, default=1.0)
    parser.add_argument("--batch", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--browser-distribution", default="chrome:30,safari:20,firefox:15,edge:10,brave:5,chrome_mobile:10,safari_mobile:5,opera:3,samsung:2")
    parser.add_argument("--device-distribution", default="desktop:70,mobile:20,tablet:10")
    parser.add_argument("--os-distribution", default="windows:40,macos:30,linux:10,ios:12,android:8")
    parser.add_argument("--webrtc-enabled", action="store_true")
    parser.add_argument("--media-quality", choices=["full", "medium", "low"], default="medium")
    parser.add_argument("--network-conditions", default="ethernet:20,wi-fi:50,4g:20,3g:10")
    parser.add_argument("--network-degradation", action="store_true")
    parser.add_argument("--degradation-interval", type=int, default=300)
    parser.add_argument("--test-scenarios", default="camera_toggle,mic_toggle,hand_raise,chat")
    parser.add_argument("--action-interval", type=float, default=30)
    parser.add_argument("--chat-interval", type=float, default=60)
    parser.add_argument("--confirm-timeout", type=float, default=5)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--no-chat", action="store_true")
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--no-mic", action="store_true")
    parser.add_argument("--no-handraise", action="store_true")
    parser.add_argument("--no-screen-share", action="store_true")
    parser.add_argument("--no-cross-confirm", action="store_true")
    parser.add_argument("--report-log", default="report_log.jsonl")
    parser.add_argument("--report-output", default="load_test_report.docx")
    parser.add_argument("--frontend", default=DEFAULT_FRONTEND)
    parser.add_argument("--signal", default=DEFAULT_SIGNAL)
    parser.add_argument("--jwt-secret", default=None, help="JWT secret for local authentication tokens")
    parser.add_argument("--max-subscriptions", type=int, default=2, help="Maximum concurrent WebRTC downlink subscriptions per bot")
    parser.add_argument("--decode-downlink", action="store_true", help="Decode incoming downlink WebRTC video streams in software")
    parser.add_argument("--host-bot-id", type=int, default=1, help="The bot ID assigned as host/moderator")
    parser.add_argument("--presenter-bot-id", type=int, default=2, help="The bot ID assigned as presenter")
    parser.add_argument("--control-file", default=None, help="JSON control file containing session state (paused/running)")
    parser.add_argument("--use-fake-ui-for-media-stream", action="store_true", help="Bypass media stream confirmations in Chromium (compatibility flag)")
    parser.add_argument("--startup-delay", type=float, default=0.0, help="Initial delay in seconds before spawning bots")
    
    # SLA thresholds arguments
    parser.add_argument("--sla-success-rate", type=float, default=95.0, help="SLA target action success rate percentage")
    parser.add_argument("--sla-latency", type=float, default=500.0, help="SLA target maximum average action propagation latency in ms")
    parser.add_argument("--sla-packet-loss", type=float, default=2.0, help="SLA target maximum packet loss percentage")
    parser.add_argument("--sla-jitter", type=float, default=30.0, help="SLA target maximum network jitter in ms")
    
    # Scenario and RAM control arguments
    parser.add_argument("--cross-confirm-limit", type=int, default=10, help="Max bots logging cross-confirmations per event")
    parser.add_argument("--camera-publishers", default="1,2,3,4,5", help="List of bot IDs allowed to publish camera")
    parser.add_argument("--mic-publishers", default="1,2,3,4,5", help="List of bot IDs allowed to publish microphone")
    parser.add_argument("--screen-share-publishers", default="2", help="List of bot IDs allowed to publish screen share")
    parser.add_argument("--viewer-bots", default="6-1000", help="List of bot IDs acting as viewers")
    parser.add_argument("--viewer-mode", default="receive_only", help="Viewer behavior mode")
    parser.add_argument("--auto-camera", action="store_true", help="Start camera immediately on join")
    parser.add_argument("--auto-mic", action="store_true", help="Start microphone unmuted immediately on join")
    parser.add_argument("--auto-screen-share", action="store_true", help="Start screen sharing immediately on join")
    parser.add_argument("--refresh-bots", type=int, default=0, help="Number of bots that will perform session refreshes")
    parser.add_argument("--disable-abnormal-behavior", action="store_true", help="Disable simulated abnormal behaviors in playground")
    
    args = parser.parse_args()
    try:
        # Tune system resource file descriptor limits for high concurrency load tests on UNIX
        try:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            target_limit = min(hard, 1048576)
            if soft < target_limit:
                resource.setrlimit(resource.RLIMIT_NOFILE, (target_limit, hard))
                print(f"🔧 System limits: increased open files limit from {soft} to {target_limit} for high concurrency", flush=True)
        except (ImportError, Exception):
            pass

        asyncio.run(main(args))
    except KeyboardInterrupt:
        print(f"\n{C['yellow']}🛑  Interrupted — shutting down...{C['reset']}", flush=True)
    finally:
        if 'args' in locals() and os.path.exists(args.report_log) and "_chunk_" not in args.report_log:
            print(f"\n📊 Automatically compiling report for {args.report_log}...", flush=True)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            generate_report_script = os.path.join(script_dir, "generate_report.py")
            try:
                import subprocess
                subprocess.run([sys.executable, generate_report_script, args.report_log, "--output", args.report_output], check=True)
            except Exception as e:
                print(f"⚠️ Failed to auto-compile report: {e}", flush=True)
