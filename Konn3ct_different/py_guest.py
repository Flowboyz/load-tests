# py_guest.py — Advanced Multi-Browser/Device WebSocket Load Testing Bot

import sys
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
class Registry:
    def __init__(self):
        self.user_id_to_name = {}
        self.active_actions = {}  # maps user_id -> action_type -> (value, sent_time)
        self.lock = asyncio.Lock()

    async def register(self, user_id, name):
        if not user_id:
            return
        async with self.lock:
            self.user_id_to_name[user_id] = name

    async def lookup(self, user_id):
        async with self.lock:
            return self.user_id_to_name.get(user_id, f"User({user_id})")

    async def record_sent(self, user_id, action_type, value):
        if not user_id:
            return
        async with self.lock:
            if user_id not in self.active_actions:
                self.active_actions[user_id] = {}
            self.active_actions[user_id][action_type] = (value, time.time())

    async def get_sent_time(self, user_id, action_type, value):
        if not user_id:
            return None
        async with self.lock:
            if user_id in self.active_actions and action_type in self.active_actions[user_id]:
                val, ts = self.active_actions[user_id][action_type]
                if val == value:
                    return ts
            return None

registry = Registry()
metrics = MetricsCollector()
logger: ActionLogger = None

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

    def add(self, action_key, expected_value, sent_at):
        self.pending[action_key] = (expected_value, sent_at)

    def confirm(self, action_key):
        return self.pending.pop(action_key, None)

    def sweep_timeouts(self, now, timeout_s):
        timed_out = []
        for key, (value, sent_at) in list(self.pending.items()):
            if now - sent_at > timeout_s:
                timed_out.append((key, value))
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
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            data = await resp.json()
            session_token = data.get("sessionToken")
            if not session_token:
                return None
    except Exception as exc:
        return None

    try:
        async with session.post(
            f"{frontend_url}/api/join",
            json={"roomId": room_id, "sessionToken": session_token},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            data = await resp.json()
            ws_token = data.get("token")
            return ws_token
    except Exception:
        return None

# Core action loop for simulated activity
async def action_loop(
    ws, bot_id, name, email, my_user_id, fingerprint, pending,
    action_interval, chat_interval, webrtc_client,
    camera_enabled, mic_enabled, hand_enabled, chat_enabled, screen_share_enabled,
    stop_event, scenario_event, scenarios=[], role="attendee"
):
    camera_on = random.choice([True, False])
    is_muted = random.choice([True, False])
    hand_raised = False
    screen_sharing = False

    # Send initial states
    now = time.time()
    if camera_enabled:
        await ws.send(json.dumps({"type": "camera_state", "isCameraOn": camera_on}))
        pending.add("camera", camera_on, now)
        await registry.record_sent(my_user_id, "camera", camera_on)
        await logger.log_action(bot_id, name, email, "camera", camera_on, "sent", fingerprint=fingerprint)
        if webrtc_client:
            await webrtc_client.send_media("video", camera_on)

    if mic_enabled:
        await ws.send(json.dumps({"type": "mute_state", "isMuted": is_muted}))
        pending.add("mic", is_muted, now)
        await registry.record_sent(my_user_id, "mic", is_muted)
        await logger.log_action(bot_id, name, email, "mic", is_muted, "sent", fingerprint=fingerprint)
        if webrtc_client:
            await webrtc_client.send_media("audio", not is_muted)

    next_action_at = now + random.uniform(action_interval * 0.7, action_interval * 1.3)
    next_chat_at = now + random.uniform(chat_interval * 0.7, chat_interval * 1.3)

    while not stop_event.is_set():
        await asyncio.sleep(1)
        now = time.time()

        # Handle external Scenario Triggers
        if scenario_event.is_set():
            # Clear event and run scenario action
            scenario_event.clear()
            # Toggle camera immediately
            camera_on = not camera_on
            await ws.send(json.dumps({"type": "camera_state", "isCameraOn": camera_on}))
            pending.add("camera", camera_on, now)
            await registry.record_sent(my_user_id, "camera", camera_on)
            await logger.log_action(bot_id, name, email, "camera", camera_on, "sent", fingerprint=fingerprint)
            continue

        # Normal random action intervals
        if now >= next_action_at:
            choices = []
            if camera_enabled: choices.append("camera")
            if mic_enabled: choices.append("mic")
            if hand_enabled: choices.append("hand")
            if screen_share_enabled: choices.append("screen_share")
            if "note_update" in scenarios: choices.append("note_update")
            if role == "host": choices.append("force_mute")

            if choices:
                act = random.choice(choices)
                try:
                    if act == "camera":
                        camera_on = not camera_on
                        await ws.send(json.dumps({"type": "camera_state", "isCameraOn": camera_on}))
                        pending.add("camera", camera_on, now)
                        await registry.record_sent(my_user_id, "camera", camera_on)
                        await logger.log_action(bot_id, name, email, "camera", camera_on, "sent", fingerprint=fingerprint)
                        if webrtc_client:
                            await webrtc_client.send_media("video", camera_on)
                    elif act == "mic":
                        is_muted = not is_muted
                        await ws.send(json.dumps({"type": "mute_state", "isMuted": is_muted}))
                        pending.add("mic", is_muted, now)
                        await registry.record_sent(my_user_id, "mic", is_muted)
                        await logger.log_action(bot_id, name, email, "mic", is_muted, "sent", fingerprint=fingerprint)
                        if webrtc_client:
                            await webrtc_client.send_media("audio", not is_muted)
                    elif act == "hand":
                        hand_raised = not hand_raised
                        await ws.send(json.dumps({"type": "hand_raise", "isHandRaised": hand_raised}))
                        pending.add("hand", hand_raised, now)
                        await registry.record_sent(my_user_id, "hand", hand_raised)
                        await logger.log_action(bot_id, name, email, "hand", hand_raised, "sent", fingerprint=fingerprint)
                    elif act == "screen_share":
                        screen_sharing = not screen_sharing
                        await ws.send(json.dumps({"type": "screen_share", "isScreenSharing": screen_sharing}))
                        pending.add("screen_share", screen_sharing, now)
                        await registry.record_sent(my_user_id, "screen_share", screen_sharing)
                        await logger.log_action(bot_id, name, email, "screen_share", screen_sharing, "sent", fingerprint=fingerprint)
                    elif act == "note_update":
                        new_content = f"Notes session updated by {name} at {datetime.datetime.now().strftime('%H:%M:%S')}"
                        await ws.send(json.dumps({"type": "note_update", "content": new_content}))
                        pending.add("note_update", new_content, now)
                        await registry.record_sent(my_user_id, "note_update", new_content)
                        await logger.log_action(bot_id, name, email, "note_update", "Broadcasting notes sync", "sent", fingerprint=fingerprint)
                    elif act == "force_mute":
                        other_ids = [uid for uid in registry.user_id_to_name.keys() if uid != my_user_id]
                        if other_ids:
                            target_uid = random.choice(other_ids)
                            target_name = registry.user_id_to_name.get(target_uid, target_uid)
                            t0 = time.time()
                            await ws.send(json.dumps({"type": "force_mute", "userId": target_uid}))
                            elapsed = (time.time() - t0) * 1000
                            await logger.log_action(bot_id, name, email, "force_mute", f"Muted {target_name}", "confirmed", elapsed, fingerprint=fingerprint)
                            await metrics.record_action("force_mute", fingerprint["browser_type"], "confirmed", elapsed)
                except Exception:
                    break
            next_action_at = now + random.uniform(action_interval * 0.7, action_interval * 1.3)

        # Normal chat sends
        if chat_enabled and now >= next_chat_at:
            msg = random.choice(CHAT_MESSAGES)
            chat_id = f"{bot_id}-{int(now*1000)}"
            try:
                await ws.send(json.dumps({"type": "chat", "message": msg, "clientMsgId": chat_id}))
                pending.add(f"chat:{chat_id}", msg, now)
                await registry.record_sent(my_user_id, f"chat:{chat_id}", msg)
                await logger.log_action(bot_id, name, email, "chat", msg, "sent", fingerprint=fingerprint)
            except Exception:
                break
            next_chat_at = now + random.uniform(chat_interval * 0.7, chat_interval * 1.3)

# Individual bot WebSocket session loop
async def ws_session(
    ws_url, bot_id, name, email, emulator, auto_leave_s,
    chat_enabled, chat_interval, camera_enabled, mic_enabled, hand_enabled, screen_share_enabled,
    action_interval, confirm_timeout, webrtc_enabled, media_quality, network_profile, network_degradation, degradation_interval,
    stop_event, scenario_event, cross_confirm,
    role="attendee", max_subscriptions=2, decode_downlink=False, in_breakout=False, scenarios=[]
):
    fingerprint = emulator.fingerprint
    simulator = NetworkSimulator(network_profile, network_degradation, degradation_interval)
    webrtc_client = None
    try:
        headers = {"User-Agent": fingerprint["user_agent"]}
        async with websockets.connect(
            ws_url,
            additional_headers=headers,
            ping_interval=15,
            ping_timeout=20,
            close_timeout=10,
            open_timeout=15
        ) as ws:
            await stats.inc("active")
            
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
                                    stop_event.set()
                                    
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
                                    
                            elif mtype == "note_update":
                                uid = msg.get("userId")
                                content = msg.get("content")
                                if uid == my_user_id:
                                    result = pending.confirm("note_update")
                                    if result:
                                        elapsed = (time.time() - result[1]) * 1000
                                        await logger.log_action(bot_id, name, email, "note_update", "Sync confirmed", "confirmed", elapsed, fingerprint)
                                        await metrics.record_action("note_update", fingerprint["browser_type"], "confirmed", elapsed)
                                else:
                                    if cross_confirm:
                                        sent_time = await registry.get_sent_time(uid, "note_update", content)
                                        elapsed = (time.time() - sent_time) * 1000 if sent_time else None
                                        other_name = await registry.lookup(uid)
                                        await logger.log_action(bot_id, name, email, "note_update", f"Observed update from {other_name}", f"observed:{other_name}", elapsed, fingerprint)
                                        if elapsed is not None:
                                            await metrics.record_action("note_update", fingerprint["browser_type"], "observed", elapsed)

                            elif mtype in ("camera_state", "mute_state", "hand_raise", "screen_share", "chat"):
                                uid = msg.get("userId")
                                if uid == my_user_id:
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
                                        act = f"chat:{msg.get('clientMsgId')}"
                                    
                                    result = pending.confirm(act)
                                    if result:
                                        elapsed = (time.time() - result[1]) * 1000
                                        clean_act = act.split(":")[0]
                                        await logger.log_action(bot_id, name, email, clean_act, val, "confirmed", elapsed, fingerprint)
                                        await metrics.record_action(clean_act, fingerprint["browser_type"], "confirmed", elapsed)
                                else:
                                    if cross_confirm:
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
                                            client_id = msg.get("clientMsgId")
                                            act = f"chat:{client_id}" if client_id else "chat"
                                        
                                        sent_time = await registry.get_sent_time(uid, act, val)
                                        elapsed = (time.time() - sent_time) * 1000 if sent_time else None
                                        
                                        other_name = await registry.lookup(uid)
                                        clean_act = act.split(":")[0]
                                        await logger.log_action(bot_id, name, email, clean_act, val, f"observed:{other_name}", elapsed, fingerprint)
                                        if elapsed is not None:
                                            await metrics.record_action(clean_act, fingerprint["browser_type"], "observed", elapsed)
                                            
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
                        success = await webrtc_client.connect(send_request)
                    except Exception as exc:
                        success = False
                        await logger.record_event("error_logged", bot_id=bot_id, name=name, action="webrtc_connection", error=str(exc), browser=fingerprint["browser_type"])
                        
                    if success:
                        await logger.log_action(bot_id, name, email, "webrtc_connection", "CONNECTED", "confirmed", fingerprint=fingerprint)
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
                        await logger.log_action(bot_id, name, email, "webrtc_connection", "FAILED", "failed", fingerprint=fingerprint)
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
                        stop_event=stop_event, scenario_event=scenario_event, scenarios=scenarios, role=role
                    )
                )

                while not stop_event.is_set():
                    now = time.time()
                    
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
                        
                    for key, val in pending.sweep_timeouts(now, confirm_timeout):
                        act_type = key.split(":")[0]
                        await logger.log_action(bot_id, name, email, act_type, val, "timed_out", fingerprint=fingerprint)
                        await metrics.record_action(act_type, fingerprint["browser_type"], "timed_out")
                        await logger.record_event("error_logged", bot_id=bot_id, name=name, action=act_type, error="Action confirmation timeout", browser=fingerprint["browser_type"])
                        
                    await asyncio.sleep(1.0)
                    
            finally:
                if webrtc_client and webrtc_enabled:
                    try:
                        qoe = await webrtc_client.collect_qoe_stats()
                        browser = fingerprint["browser_type"]
                        resolution = f"{webrtc_client.video_track.width}x{webrtc_client.video_track.height}" if webrtc_client.video_track else "N/A"
                        prefs = emulator.get_codec_preferences()
                        codec = prefs[0] if prefs else "VP8"
                        
                        await metrics.record_webrtc(
                            browser=browser,
                            ice_time_ms=(webrtc_client._ice_connected_time - webrtc_client._start_time) * 1000 if webrtc_client._ice_connected_time else None,
                            dtls_time_ms=(webrtc_client._dtls_connected_time - webrtc_client._ice_connected_time) * 1000 if (webrtc_client._dtls_connected_time and webrtc_client._ice_connected_time) else None,
                            packet_loss=qoe["packet_loss"],
                            jitter_ms=qoe["jitter_ms"],
                            bitrate_kbps=800,
                            codec=codec,
                            resolution=resolution,
                            rtt_ms=qoe["rtt_ms"]
                        )
                    except Exception:
                        pass
                if action_task and not action_task.done():
                    action_task.cancel()
                if reader_task and not reader_task.done():
                    reader_task.cancel()
                if webrtc_client:
                    await webrtc_client.close()
                    
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
    jwt_secret=None, max_subscriptions=2, decode_downlink=False, host_bot_id=1, presenter_bot_id=2, scenarios=[]
):
    name, email = await generate_identity()
    
    # 1. Sample profiles
    profile = device_manager.sample_profile()
    emulator = BrowserEmulator(profile)
    fingerprint = emulator.fingerprint

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
        return f"{proto}://{signal_domain}/signal?roomId={room}&token={token}&isMobile={str(profile['device_type'] != 'desktop').lower()}"

    current_room = room_id
    ws_url = await get_ws_url(current_room)
    if not ws_url:
        await stats.inc("failed")
        await metrics.record_join(fingerprint["browser_type"], False)
        return

    await stats.inc("joined")
    await logger.record_event("bot_joined", bot_id, name, email, fingerprint=fingerprint)
    logger.log("🌐", "grey", bot_id, name, f"Token acquired — connecting to room: {current_room}...", fingerprint=fingerprint)
    
    attempt = 0
    in_breakout = False

    while not stop_event.is_set() and attempt <= max_retries:
        result = await ws_session(
            ws_url=ws_url, bot_id=bot_id, name=name, email=email, emulator=emulator, auto_leave_s=auto_leave_s,
            chat_enabled=chat_enabled, chat_interval=chat_interval,
            camera_enabled=camera_enabled, mic_enabled=mic_enabled, hand_enabled=hand_enabled, screen_share_enabled=screen_share_enabled,
            action_interval=action_interval, confirm_timeout=confirm_timeout,
            webrtc_enabled=webrtc_enabled, media_quality=media_quality,
            network_profile=network_profile, network_degradation=network_degradation, degradation_interval=degradation_interval,
            stop_event=stop_event, scenario_event=scenario_event, cross_confirm=cross_confirm,
            role=role, max_subscriptions=max_subscriptions, decode_downlink=decode_downlink, in_breakout=in_breakout, scenarios=scenarios
        )

        if stop_event.is_set():
            break

        if result == "migrate_to_breakout":
            in_breakout = True
            current_room = f"{room_id}-breakout-{((bot_id - 1) % 3) + 1}"
            logger.log("🚪", "cyan", bot_id, name, f"Migrating to breakout room: {current_room}", fingerprint=fingerprint)
            t_start = time.time()
            ws_url = await get_ws_url(current_room)
            if not ws_url:
                break
            elapsed = (time.time() - t_start) * 1000
            await logger.log_action(bot_id, name, email, "breakout_join", current_room, "confirmed", elapsed, fingerprint)
            await metrics.record_action("breakout_join", fingerprint["browser_type"], "confirmed", elapsed)
            continue
            
        elif result == "migrate_to_main":
            in_breakout = False
            current_room = room_id
            logger.log("🚪", "cyan", bot_id, name, f"Returning to main room: {current_room}", fingerprint=fingerprint)
            t_start = time.time()
            ws_url = await get_ws_url(current_room)
            if not ws_url:
                break
            elapsed = (time.time() - t_start) * 1000
            await logger.log_action(bot_id, name, email, "breakout_join", current_room, "confirmed", elapsed, fingerprint)
            await metrics.record_action("breakout_join", fingerprint["browser_type"], "confirmed", elapsed)
            continue

        if result is True:
            # Safe exit
            break

        attempt += 1
        await stats.inc("reconnects")
        backoff = min(2 ** attempt, 30) + random.uniform(0, 1)
        logger.log("🔄", "yellow", bot_id, name, f"Reconnecting in {backoff:.1f}s (attempt {attempt}/{max_retries})...", fingerprint=fingerprint)
        await asyncio.sleep(backoff)
        
        ws_url = await get_ws_url(current_room)
        if not ws_url:
            break

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
    semaphore = asyncio.Semaphore(args.concurrency)

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
        max_retries=args.max_retries
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

    connector = aiohttp.TCPConnector(limit=args.concurrency, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        
        async def launch(bot_id):
            async with semaphore:
                if stop_event.is_set():
                    return
                scen_event = asyncio.Event()
                scenario_events.append(scen_event)
                
                scenarios = [s.strip() for s in args.test_scenarios.split(",")]
                
                await run_bot(
                    bot_id=bot_id, room_id=args.room,
                    frontend_url=args.frontend, signal_domain=args.signal,
                    auto_leave_s=auto_leave_s,
                    chat_enabled=not args.no_chat, chat_interval=args.chat_interval,
                    camera_enabled=not args.no_camera, mic_enabled=not args.no_mic,
                    hand_enabled=not args.no_handraise, screen_share_enabled=not args.no_screen_share,
                    action_interval=args.action_interval, confirm_timeout=args.confirm_timeout,
                    max_retries=args.max_retries, webrtc_enabled=args.webrtc_enabled,
                    media_quality=args.media_quality, network_distribution=net_distribution,
                    network_degradation=args.network_degradation, degradation_interval=args.degradation_interval,
                    device_manager=device_manager, stop_event=stop_event, session=session,
                    scenario_event=scen_event, cross_confirm=not args.no_cross_confirm,
                    jwt_secret=args.jwt_secret, max_subscriptions=args.max_subscriptions,
                    decode_downlink=args.decode_downlink, host_bot_id=args.host_bot_id,
                    presenter_bot_id=args.presenter_bot_id, scenarios=scenarios
                )

        tasks = []
        bot_id = 1
        
        # Periodic statistics printing task
        async def stats_printer():
            while not stop_event.is_set():
                await asyncio.sleep(5)
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                print(f"{C['grey']}[{ts}] 📊 Stats Snapshot: {stats.summary()}{C['reset']}", flush=True)
                
        asyncio.create_task(stats_printer())

        # Scenarios triggering task
        async def scenario_runner():
            scenarios = [s.strip() for s in args.test_scenarios.split(",")]
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

        while bot_id <= args.bots and not stop_event.is_set():
            batch = []
            for _ in range(args.batch):
                if bot_id > args.bots:
                    break
                batch.append(asyncio.create_task(launch(bot_id)))
                bot_id += 1
            tasks.extend(batch)
            if bot_id <= args.bots and args.stagger > 0:
                await asyncio.sleep(args.stagger)

        print(f"{C['green']}  ✔  All {args.bots} bot(s) queued — press Ctrl+C to stop{C['reset']}\n")

        try:
            await asyncio.gather(*tasks)
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
    parser.add_argument("--jwt-secret", default="fallback-secret-key", help="JWT secret for local authentication tokens")
    parser.add_argument("--max-subscriptions", type=int, default=2, help="Maximum concurrent WebRTC downlink subscriptions per bot")
    parser.add_argument("--decode-downlink", action="store_true", help="Decode incoming downlink WebRTC video streams in software")
    parser.add_argument("--host-bot-id", type=int, default=1, help="The bot ID assigned as host/moderator")
    parser.add_argument("--presenter-bot-id", type=int, default=2, help="The bot ID assigned as presenter")
    
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print(f"\n{C['yellow']}🛑  Interrupted — shutting down...{C['reset']}", flush=True)
    finally:
        if 'args' in locals() and os.path.exists(args.report_log):
            print(f"\n📊 Automatically compiling report for {args.report_log}...", flush=True)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            generate_report_script = os.path.join(script_dir, "generate_report.py")
            try:
                import subprocess
                subprocess.run([sys.executable, generate_report_script, args.report_log, "--output", args.report_output], check=True)
            except Exception as e:
                print(f"⚠️ Failed to auto-compile report: {e}", flush=True)
