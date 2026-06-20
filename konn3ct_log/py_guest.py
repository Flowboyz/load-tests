"""
py_guest.py — Konn3ct Load Testing Bot (WebSocket + Confirmed Action Tracking)
Simulates attendees joining with realistic random camera, mic, and hand raise activity.

Every action a bot performs (camera, mic, hand raise, chat) is tracked end-to-end:
  1. Bot sends the action
  2. Bot waits for the server to broadcast it back (confirmation)
  3. If no confirmation arrives in time, a WARNING is logged — this exposes silent failures
  4. Other bots that observe the broadcast log a cross-confirmation line too,
     e.g. "Bot-0014 (James Carter) — observed: Jessica Turner turned camera ON"

Dependencies:
    pip install faker aiohttp websockets

Usage:
    python py_guest.py --room testinggg --bots 50
    python py_guest.py --room testinggg --bots 200 --leave 10 --no-chat
    python py_guest.py --room testinggg --bots 100 --batch 5 --stagger 2.0

Arguments:
    --room              Room slug/ID (default: testinggg)
    --bots              Number of bots (default: 50)
    --leave             Auto-leave after N minutes, 0 = Ctrl+C (default: 0)
    --stagger           Seconds between each batch (default: 1.0)
    --batch             Bots per stagger interval (default: 3)
    --concurrency       Max bots active at once (default: 100)
    --no-chat           Disable chat simulation
    --chat-interval     Seconds between chat messages (default: 60)
    --no-camera         Disable camera toggle simulation
    --no-mic            Disable mic mute/unmute simulation
    --no-handraise      Disable hand raise simulation
    --action-interval   Seconds between random actions (default: 30)
    --confirm-timeout   Seconds to wait for server confirmation before warning (default: 5)
    --no-cross-confirm  Disable other bots logging observed actions (reduces log volume)
    --max-retries       Max reconnect attempts per bot (default: 5)
    --report-log        Path to JSON event log for report generation (default: report_log.jsonl)
    --frontend          Frontend base URL (default: https://edge.konn3ct.net)
    --signal            WebSocket signal server domain (default: konn3ctedge.konn3ct.net)
"""

import asyncio
import argparse
import signal
import random
import datetime
import json
import os

import aiohttp
import websockets
from faker import Faker

# ──────────────────────────────────────────────────────────────────────────────
#  DEFAULTS
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
#  COLOURS
# ──────────────────────────────────────────────────────────────────────────────
C = {
    "green":   "\033[92m",
    "red":     "\033[91m",
    "cyan":    "\033[96m",
    "yellow":  "\033[93m",
    "grey":    "\033[90m",
    "white":   "\033[97m",
    "magenta": "\033[95m",
    "blue":    "\033[94m",
    "reset":   "\033[0m",
}

def log(icon, colour, bot_id, name, msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(
        f"{C['grey']}[{ts}]{C['reset']} "
        f"{colour}{icon} Bot-{bot_id:04d}{C['reset']} "
        f"{C['grey']}({name}){C['reset']} — {msg}",
        flush=True,
    )

# ──────────────────────────────────────────────────────────────────────────────
#  IDENTITY GENERATOR
# ──────────────────────────────────────────────────────────────────────────────
faker_gen        = Faker()
_used_identities = set()
_identity_lock   = asyncio.Lock()

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

# ──────────────────────────────────────────────────────────────────────────────
#  GLOBAL REGISTRY  — shared across all bots in this process
#  Lets any bot resolve another bot's userId -> display name for cross-confirmation
# ──────────────────────────────────────────────────────────────────────────────
class Registry:
    def __init__(self):
        self.user_id_to_name = {}   # serverUserId -> display name
        self.lock = asyncio.Lock()

    async def register(self, user_id, name):
        if not user_id:
            return
        async with self.lock:
            self.user_id_to_name[user_id] = name

    async def lookup(self, user_id):
        async with self.lock:
            return self.user_id_to_name.get(user_id, f"Unknown({user_id})")

registry = Registry()

# ──────────────────────────────────────────────────────────────────────────────
#  STATS
# ──────────────────────────────────────────────────────────────────────────────
class Stats:
    def __init__(self):
        self.joined      = 0
        self.failed      = 0
        self.active      = 0
        self.left        = 0
        self.reconnects  = 0
        self.cameras     = 0   # confirmed camera toggles
        self.mutes       = 0   # confirmed mic toggles
        self.handraises  = 0   # confirmed hand raises
        self.chats       = 0   # confirmed chat sends
        self.unconfirmed = 0   # actions that timed out waiting for confirmation
        self.lock        = asyncio.Lock()

    async def inc(self, field, amount=1):
        async with self.lock:
            setattr(self, field, max(0, getattr(self, field) + amount))

    def summary(self):
        return (
            f"{C['green']}✅ joined={self.joined}{C['reset']}  "
            f"{C['cyan']}🟢 active={self.active}{C['reset']}  "
            f"{C['yellow']}🚪 left={self.left}{C['reset']}  "
            f"{C['yellow']}🔄 reconnects={self.reconnects}{C['reset']}  "
            f"{C['red']}❌ failed={self.failed}{C['reset']}  "
            f"{C['magenta']}📷 cam={self.cameras} 🎤 mic={self.mutes} ✋ hand={self.handraises} 💬 chat={self.chats}{C['reset']}  "
            f"{C['red']}⚠️ unconfirmed={self.unconfirmed}{C['reset']}"
        )

stats = Stats()

# ──────────────────────────────────────────────────────────────────────────────
#  EVENT RECORDER  — writes structured JSON lines for report generation later
# ──────────────────────────────────────────────────────────────────────────────
class EventRecorder:
    def __init__(self, path: str):
        self.path  = path
        self.lock  = asyncio.Lock()
        self.start_time = datetime.datetime.now()
        with open(self.path, "w") as f:
            f.write(json.dumps({
                "event": "test_started",
                "ts": self.start_time.isoformat(),
            }) + "\n")

    async def record(self, event_type, bot_id=None, name=None, email=None, **extra):
        entry = {
            "event": event_type,
            "ts":    datetime.datetime.now().isoformat(),
            "bot_id": bot_id,
            "name":   name,
            "email":  email,
            **extra,
        }
        async with self.lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(entry) + "\n")

    async def record_config(self, **config):
        await self.record("test_config", **config)

    async def record_final(self, summary: dict):
        await self.record("test_finished", **summary)

recorder: "EventRecorder | None" = None  # set in main()

# ──────────────────────────────────────────────────────────────────────────────
#  PENDING ACTION TRACKER  — per-bot, tracks actions awaiting server confirmation
# ──────────────────────────────────────────────────────────────────────────────
class PendingActions:
    """
    Tracks actions this bot has sent but not yet confirmed by the server.
    Key: action type ("camera", "mic", "hand", "chat:<id>")
    Value: (expected_value, sent_at_loop_time)
    """
    def __init__(self):
        self.pending = {}

    def add(self, action_key, expected_value, sent_at):
        self.pending[action_key] = (expected_value, sent_at)

    def confirm(self, action_key):
        return self.pending.pop(action_key, None)

    def sweep_timeouts(self, now, timeout_s):
        """Return list of (action_key, expected_value) that have timed out, removing them."""
        timed_out = []
        for key, (value, sent_at) in list(self.pending.items()):
            if now - sent_at > timeout_s:
                timed_out.append((key, value))
                del self.pending[key]
        return timed_out

# ──────────────────────────────────────────────────────────────────────────────
#  TOKEN FETCH
# ──────────────────────────────────────────────────────────────────────────────
async def get_ws_token(session, frontend_url, room_id, name, email, bot_id):
    try:
        async with session.post(
            f"{frontend_url}/api/prejoin",
            json={
                "roomId":   room_id,
                "name":     name,
                "email":    email,
                "isMobile": False,
                "camera":   False,
                "mic":      False,
            },
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            data = await resp.json()
            session_token = data.get("sessionToken")
            if not session_token:
                log("❌", C["red"], bot_id, name, f"Prejoin failed: {data}")
                return None
    except Exception as exc:
        log("❌", C["red"], bot_id, name, f"Prejoin error: {exc}")
        return None

    try:
        async with session.post(
            f"{frontend_url}/api/join",
            json={"roomId": room_id, "sessionToken": session_token},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            data = await resp.json()
            ws_token = data.get("token")
            if not ws_token:
                log("❌", C["red"], bot_id, name, f"Join failed: {data}")
                return None
            return ws_token
    except Exception as exc:
        log("❌", C["red"], bot_id, name, f"Join error: {exc}")
        return None

# ──────────────────────────────────────────────────────────────────────────────
#  BOT STATE
# ──────────────────────────────────────────────────────────────────────────────
class BotState:
    def __init__(self):
        self.camera_on   = random.choice([True, False])
        self.is_muted    = random.choice([True, False])
        self.hand_raised = False
        self.user_id     = None   # filled in once session_status gives us our server userId

# ──────────────────────────────────────────────────────────────────────────────
#  ACTION SIMULATOR — sends camera / mic / hand raise / chat at intervals
# ──────────────────────────────────────────────────────────────────────────────
async def action_loop_main(
    ws, bot_id, name, bot_state, pending,
    action_interval, chat_interval,
    camera_on, mic_on, hand_on, chat_on,
    stop_event,
):
    """
    Cleaner single-loop version: fires one random toggle action on action_interval,
    and chat independently on chat_interval.
    """
    now = asyncio.get_event_loop().time()

    # Initial state push
    if camera_on:
        await ws.send(json.dumps({"type": "camera_state", "isCameraOn": bot_state.camera_on}))
        pending.add("camera", bot_state.camera_on, now)
        if recorder:
            await recorder.record("action_sent", bot_id, name, action="camera", value=bot_state.camera_on)
    if mic_on:
        await ws.send(json.dumps({"type": "mute_state", "isMuted": bot_state.is_muted}))
        pending.add("mic", bot_state.is_muted, now)
        if recorder:
            await recorder.record("action_sent", bot_id, name, action="mic", value=bot_state.is_muted)

    next_action_at = now + random.uniform(action_interval * 0.7, action_interval * 1.3)
    next_chat_at   = now + random.uniform(15, 30)

    while not stop_event.is_set():
        await asyncio.sleep(1)
        if stop_event.is_set():
            break
        now = asyncio.get_event_loop().time()

        # Random toggle action
        if now >= next_action_at:
            available = []
            if camera_on: available.append("camera")
            if mic_on:    available.append("mic")
            if hand_on:   available.append("hand")

            if available:
                action = random.choice(available)
                try:
                    if action == "camera":
                        bot_state.camera_on = not bot_state.camera_on
                        await ws.send(json.dumps({"type": "camera_state", "isCameraOn": bot_state.camera_on}))
                        pending.add("camera", bot_state.camera_on, now)
                        log("📷", C["magenta"], bot_id, name,
                            f"Sent camera → {'ON' if bot_state.camera_on else 'OFF'} (awaiting confirmation…)")
                        if recorder:
                            await recorder.record("action_sent", bot_id, name, action="camera", value=bot_state.camera_on)

                    elif action == "mic":
                        bot_state.is_muted = not bot_state.is_muted
                        await ws.send(json.dumps({"type": "mute_state", "isMuted": bot_state.is_muted}))
                        pending.add("mic", bot_state.is_muted, now)
                        log("🎤", C["magenta"], bot_id, name,
                            f"Sent mic → {'MUTED' if bot_state.is_muted else 'UNMUTED'} (awaiting confirmation…)")
                        if recorder:
                            await recorder.record("action_sent", bot_id, name, action="mic", value=bot_state.is_muted)

                    elif action == "hand":
                        bot_state.hand_raised = not bot_state.hand_raised
                        await ws.send(json.dumps({"type": "hand_raise", "isHandRaised": bot_state.hand_raised}))
                        pending.add("hand", bot_state.hand_raised, now)
                        log("✋", C["magenta"], bot_id, name,
                            f"Sent hand → {'RAISED' if bot_state.hand_raised else 'LOWERED'} (awaiting confirmation…)")
                        if recorder:
                            await recorder.record("action_sent", bot_id, name, action="hand", value=bot_state.hand_raised)

                except Exception:
                    break

            next_action_at = now + random.uniform(action_interval * 0.7, action_interval * 1.3)

        # Chat
        if chat_on and now >= next_chat_at:
            message  = random.choice(CHAT_MESSAGES)
            chat_id  = f"{bot_id}-{int(now*1000)}"
            try:
                await ws.send(json.dumps({"type": "chat", "message": message, "clientMsgId": chat_id}))
                pending.add(f"chat:{chat_id}", message, now)
                log("💬", C["cyan"], bot_id, name, f'Sent: "{message}" (awaiting confirmation…)')
                if recorder:
                    await recorder.record("action_sent", bot_id, name, action="chat", value=message)
            except Exception:
                pass
            next_chat_at = now + random.uniform(chat_interval * 0.8, chat_interval * 1.2)


# ──────────────────────────────────────────────────────────────────────────────
#  WEBSOCKET SESSION
# ──────────────────────────────────────────────────────────────────────────────
async def ws_session(
    ws_url, bot_id, name, auto_leave_s,
    chat_enabled, chat_interval,
    camera_enabled, mic_enabled, hand_enabled, action_interval,
    confirm_timeout, cross_confirm,
    stop_event,
) -> bool:
    """
    Returns True  = intentional disconnect (no retry needed)
    Returns False = unexpected drop (caller should retry)
    """
    try:
        async with websockets.connect(
            ws_url,
            ping_interval=15,
            ping_timeout=20,
            close_timeout=10,
            max_size=2**20,
            open_timeout=15,
        ) as ws:
            await stats.inc("active")

            bot_state    = BotState()
            pending      = PendingActions()
            joined_at    = asyncio.get_event_loop().time()
            is_active    = False
            action_task  = None

            try:
                while not stop_event.is_set():
                    now = asyncio.get_event_loop().time()

                    # Auto-leave
                    if auto_leave_s and (now - joined_at) >= auto_leave_s:
                        log("🚪", C["yellow"], bot_id, name, "Auto-leaving")
                        try:
                            await ws.send(json.dumps({"type": "leave_meeting"}))
                        except Exception:
                            pass
                        await stats.inc("active", -1)
                        await stats.inc("left")
                        return True

                    # Check for timed-out (unconfirmed) actions
                    for action_key, expected_value in pending.sweep_timeouts(now, confirm_timeout):
                        await stats.inc("unconfirmed")
                        action_name = action_key.split(":")[0]
                        log("⚠️", C["red"], bot_id, name,
                            f"NO CONFIRMATION received for {action_name} → {expected_value} "
                            f"after {confirm_timeout}s — server may not have applied it!")
                        if recorder:
                            await recorder.record("action_unconfirmed", bot_id, name,
                                                   action=action_name, expected_value=expected_value)

                    # Receive messages
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        msg = json.loads(raw)
                        mtype = msg.get("type")

                        if mtype == "session_status":
                            status = msg.get("status")

                            if msg.get("userId"):
                                bot_state.user_id = msg["userId"]
                                await registry.register(bot_state.user_id, name)

                            if status == "active" and not is_active:
                                is_active = True
                                log("🏠", C["cyan"], bot_id, name,
                                    f"In meeting — cam={'ON' if bot_state.camera_on else 'OFF'} "
                                    f"mic={'MUTED' if bot_state.is_muted else 'LIVE'}")

                                action_task = asyncio.create_task(
                                    action_loop_main(
                                        ws=ws, bot_id=bot_id, name=name,
                                        bot_state=bot_state, pending=pending,
                                        action_interval=action_interval, chat_interval=chat_interval,
                                        camera_on=camera_enabled, mic_on=mic_enabled,
                                        hand_on=hand_enabled, chat_on=chat_enabled,
                                        stop_event=stop_event,
                                    )
                                )

                            elif status == "waiting":
                                log("⏳", C["yellow"], bot_id, name, "In waiting room")

                            elif status in ("denied", "kicked", "ended"):
                                log("🚫", C["red"], bot_id, name, f"Session {status}")
                                await stats.inc("active", -1)
                                await stats.inc("left")
                                return True

                        elif mtype == "user_joined":
                            uid = msg.get("userId")
                            uname = msg.get("name")
                            if uid and uname:
                                await registry.register(uid, uname)

                        elif mtype == "participants_list":
                            for p in msg.get("participants", []):
                                if p.get("userId") and p.get("name"):
                                    await registry.register(p["userId"], p["name"])

                        elif mtype == "camera_state":
                            uid = msg.get("userId")
                            is_on = msg.get("isCameraOn")
                            if uid == bot_state.user_id:
                                # Self-confirmation
                                result = pending.confirm("camera")
                                if result:
                                    await stats.inc("cameras")
                                    log("📷", C["green"], bot_id, name,
                                        f"Camera → {'ON' if is_on else 'OFF'} "
                                        f"(✅ confirmed by server)")
                                    if recorder:
                                        await recorder.record("action_confirmed", bot_id, name,
                                                               action="camera", value=is_on)
                            elif cross_confirm:
                                other_name = await registry.lookup(uid)
                                log("👀", C["blue"], bot_id, name,
                                    f"observed: {other_name} turned camera "
                                    f"{'ON' if is_on else 'OFF'}")

                        elif mtype == "mute_state":
                            uid = msg.get("userId")
                            is_muted = msg.get("isMuted")
                            if uid == bot_state.user_id:
                                result = pending.confirm("mic")
                                if result:
                                    await stats.inc("mutes")
                                    log("🎤", C["green"], bot_id, name,
                                        f"Mic → {'MUTED' if is_muted else 'UNMUTED'} "
                                        f"(✅ confirmed by server)")
                                    if recorder:
                                        await recorder.record("action_confirmed", bot_id, name,
                                                               action="mic", value=is_muted)
                            elif cross_confirm:
                                other_name = await registry.lookup(uid)
                                log("👀", C["blue"], bot_id, name,
                                    f"observed: {other_name} is now "
                                    f"{'muted' if is_muted else 'unmuted'}")

                        elif mtype == "hand_raise":
                            uid = msg.get("userId")
                            is_raised = msg.get("isHandRaised")
                            if uid == bot_state.user_id:
                                result = pending.confirm("hand")
                                if result:
                                    await stats.inc("handraises")
                                    log("✋", C["green"], bot_id, name,
                                        f"Hand → {'RAISED' if is_raised else 'LOWERED'} "
                                        f"(✅ confirmed by server)")
                                    if recorder:
                                        await recorder.record("action_confirmed", bot_id, name,
                                                               action="hand", value=is_raised)
                            elif cross_confirm:
                                other_name = await registry.lookup(uid)
                                log("👀", C["blue"], bot_id, name,
                                    f"observed: {other_name} "
                                    f"{'raised' if is_raised else 'lowered'} their hand")

                        elif mtype == "chat":
                            uid = msg.get("userId")
                            chat_msg = msg.get("message")
                            client_id = msg.get("clientMsgId")
                            if uid == bot_state.user_id and client_id:
                                result = pending.confirm(f"chat:{client_id}")
                                if result:
                                    await stats.inc("chats")
                                    log("💬", C["green"], bot_id, name,
                                        f'Chat "{chat_msg}" (✅ confirmed delivered by server)')
                                    if recorder:
                                        await recorder.record("action_confirmed", bot_id, name,
                                                               action="chat", value=chat_msg)
                            elif uid != bot_state.user_id and cross_confirm:
                                other_name = msg.get("name") or await registry.lookup(uid)
                                log("👀", C["blue"], bot_id, name,
                                    f'observed: {other_name} sent "{chat_msg}"')

                    except asyncio.TimeoutError:
                        pass

                    except websockets.exceptions.ConnectionClosed:
                        log("🔌", C["yellow"], bot_id, name, "Connection closed unexpectedly")
                        await stats.inc("active", -1)
                        return False

                # Stop event fired
                try:
                    await ws.send(json.dumps({"type": "leave_meeting"}))
                except Exception:
                    pass
                await stats.inc("active", -1)
                await stats.inc("left")
                return True

            finally:
                if action_task and not action_task.done():
                    action_task.cancel()
                    try:
                        await action_task
                    except asyncio.CancelledError:
                        pass

    except (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError) as exc:
        log("⚠️", C["yellow"], bot_id, name, f"Connection error: {type(exc).__name__}: {exc}")
        return False

    except Exception as exc:
        log("❌", C["red"], bot_id, name, f"Unexpected error: {exc}")
        return False

# ──────────────────────────────────────────────────────────────────────────────
#  BOT COROUTINE  (handles retries)
# ──────────────────────────────────────────────────────────────────────────────
async def run_bot(
    bot_id, room_id, frontend_url, signal_domain,
    auto_leave_s, chat_enabled, chat_interval,
    camera_enabled, mic_enabled, hand_enabled, action_interval,
    confirm_timeout, cross_confirm,
    max_retries, stop_event, session,
):
    name, email = await generate_identity()
    bot_started_at = asyncio.get_event_loop().time()

    ws_token = await get_ws_token(session, frontend_url, room_id, name, email, bot_id)
    if not ws_token:
        await stats.inc("failed")
        if recorder:
            await recorder.record("bot_failed", bot_id, name, email, reason="prejoin_or_join_failed")
        return

    log("🌐", C["grey"], bot_id, name, "Token acquired — connecting…")
    await stats.inc("joined")
    if recorder:
        await recorder.record("bot_joined", bot_id, name, email)

    ws_url  = f"wss://{signal_domain}/signal?roomId={room_id}&token={ws_token}&isMobile=false"
    attempt = 0

    while not stop_event.is_set() and attempt <= max_retries:
        intentional = await ws_session(
            ws_url=ws_url, bot_id=bot_id, name=name,
            auto_leave_s=auto_leave_s,
            chat_enabled=chat_enabled, chat_interval=chat_interval,
            camera_enabled=camera_enabled, mic_enabled=mic_enabled,
            hand_enabled=hand_enabled, action_interval=action_interval,
            confirm_timeout=confirm_timeout, cross_confirm=cross_confirm,
            stop_event=stop_event,
        )

        if intentional or stop_event.is_set():
            break

        attempt += 1
        await stats.inc("reconnects")
        if recorder:
            await recorder.record("bot_reconnect_attempt", bot_id, name, email, attempt=attempt)

        if attempt > max_retries:
            log("❌", C["red"], bot_id, name, f"Max retries ({max_retries}) reached — giving up")
            await stats.inc("failed")
            if recorder:
                await recorder.record("bot_failed", bot_id, name, email,
                                       reason="max_retries_exceeded", attempts=attempt)
            break

        backoff = min(2 ** attempt, 32) + random.uniform(0, 2)
        log("🔄", C["yellow"], bot_id, name,
            f"Reconnecting in {backoff:.1f}s (attempt {attempt}/{max_retries})…")
        await asyncio.sleep(backoff)

        ws_token = await get_ws_token(session, frontend_url, room_id, name, email, bot_id)
        if not ws_token:
            log("❌", C["red"], bot_id, name, "Could not re-acquire token — giving up")
            await stats.inc("failed")
            if recorder:
                await recorder.record("bot_failed", bot_id, name, email, reason="token_reacquire_failed")
            break
        ws_url = f"wss://{signal_domain}/signal?roomId={room_id}&token={ws_token}&isMobile=false"

    duration = round(asyncio.get_event_loop().time() - bot_started_at, 1)
    log("🔒", C["grey"], bot_id, name, "Session ended")
    if recorder:
        await recorder.record("bot_session_ended", bot_id, name, email, duration_seconds=duration)

# ──────────────────────────────────────────────────────────────────────────────
#  STATS PRINTER
# ──────────────────────────────────────────────────────────────────────────────
async def stats_printer(stop_event):
    while not stop_event.is_set():
        await asyncio.sleep(5)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"\n{C['grey']}[{ts}] 📊 {stats.summary()}{C['reset']}\n", flush=True)
        if recorder:
            await recorder.record(
                "stats_snapshot",
                joined=stats.joined, active=stats.active, left=stats.left,
                failed=stats.failed, reconnects=stats.reconnects,
                cameras=stats.cameras, mutes=stats.mutes, handraises=stats.handraises,
                chats=stats.chats, unconfirmed=stats.unconfirmed,
            )

# ──────────────────────────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────────────────────────
async def main(args):
    global recorder
    stop_event = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    auto_leave_s    = args.leave * 60 if args.leave > 0 else None
    semaphore       = asyncio.Semaphore(args.concurrency)
    camera_enabled  = not args.no_camera
    mic_enabled     = not args.no_mic
    hand_enabled    = not args.no_handraise
    cross_confirm   = not args.no_cross_confirm

    report_path = args.report_log
    if os.path.dirname(report_path):
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
    recorder = EventRecorder(report_path)
    await recorder.record_config(
        room=args.room, bots=args.bots, batch=args.batch, stagger=args.stagger,
        concurrency=args.concurrency, auto_leave_minutes=args.leave,
        chat_enabled=not args.no_chat, camera_enabled=camera_enabled,
        mic_enabled=mic_enabled, hand_enabled=hand_enabled,
        max_retries=args.max_retries, confirm_timeout=args.confirm_timeout,
    )

    print(f"\n{C['white']}{'─'*70}{C['reset']}")
    print(f"{C['white']}  🚀 py_guest — Konn3ct Load Bot (Confirmed Action Tracking){C['reset']}")
    print(f"{C['white']}{'─'*70}{C['reset']}")
    print(f"  Room          : {args.room}")
    print(f"  Bots          : {args.bots}")
    print(f"  Batch         : {args.batch} bots every {args.stagger}s")
    print(f"  Concurrency   : {args.concurrency} max active at once")
    print(f"  Auto-leave    : {'manual (Ctrl+C)' if not auto_leave_s else f'{args.leave} min'}")
    print(f"  Chat          : {'ON (~every ' + str(args.chat_interval) + 's)' if not args.no_chat else 'OFF'}")
    print(f"  Camera toggle : {'ON' if camera_enabled else 'OFF'}")
    print(f"  Mic toggle    : {'ON' if mic_enabled else 'OFF'}")
    print(f"  Hand raise    : {'ON' if hand_enabled else 'OFF'}")
    print(f"  Action every  : ~{args.action_interval}s per bot (randomised ±30%)")
    print(f"  Confirm wait  : {args.confirm_timeout}s before flagging unconfirmed")
    print(f"  Cross-confirm : {'ON (bots log others actions)' if cross_confirm else 'OFF'}")
    print(f"  Max retries   : {args.max_retries}")
    print(f"{C['white']}{'─'*70}{C['reset']}\n")

    connector = aiohttp.TCPConnector(
        limit=args.concurrency,
        ssl=False,
        force_close=False,
        enable_cleanup_closed=True,
    )

    async with aiohttp.ClientSession(
        connector=connector,
        headers={"Content-Type": "application/json"},
    ) as http_session:

        asyncio.create_task(stats_printer(stop_event))

        async def launch(bot_id):
            async with semaphore:
                if stop_event.is_set():
                    return
                await run_bot(
                    bot_id=bot_id, room_id=args.room,
                    frontend_url=args.frontend, signal_domain=args.signal,
                    auto_leave_s=auto_leave_s,
                    chat_enabled=not args.no_chat, chat_interval=args.chat_interval,
                    camera_enabled=camera_enabled, mic_enabled=mic_enabled,
                    hand_enabled=hand_enabled, action_interval=args.action_interval,
                    confirm_timeout=args.confirm_timeout, cross_confirm=cross_confirm,
                    max_retries=args.max_retries, stop_event=stop_event,
                    session=http_session,
                )

        tasks  = []
        bot_id = 1
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

        print(
            f"{C['green']}  ✔  All {args.bots} bot(s) queued — press Ctrl+C to stop{C['reset']}\n",
            flush=True,
        )

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    print(f"\n{C['white']}{'─'*70}{C['reset']}")
    print(f"  📊 Final: {stats.summary()}")
    print(f"{C['white']}{'─'*70}{C['reset']}\n")
    print(f"{C['green']}  ✔  All bots stopped. Goodbye!{C['reset']}\n", flush=True)

    if recorder:
        await recorder.record_final({
            "joined": stats.joined, "active": stats.active, "left": stats.left,
            "failed": stats.failed, "reconnects": stats.reconnects,
            "cameras": stats.cameras, "mutes": stats.mutes, "handraises": stats.handraises,
            "chats": stats.chats, "unconfirmed": stats.unconfirmed,
        })
        print(f"{C['cyan']}  📄 Report data saved to: {recorder.path}{C['reset']}")
        print(f"{C['cyan']}     Run: python generate_report.py {recorder.path}{C['reset']}\n")

# ──────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="py_guest — Konn3ct Load Testing Bot")
    parser.add_argument("--room",             default=DEFAULT_ROOM,     help="Room ID")
    parser.add_argument("--bots",             type=int,   default=50,   help="Number of bots (default: 50)")
    parser.add_argument("--leave",            type=int,   default=0,    help="Auto-leave after N min (default: 0)")
    parser.add_argument("--stagger",          type=float, default=1.0,  help="Seconds between batches (default: 1.0)")
    parser.add_argument("--batch",            type=int,   default=3,    help="Bots per batch (default: 3)")
    parser.add_argument("--concurrency",      type=int,   default=100,  help="Max active bots (default: 100)")
    parser.add_argument("--chat-interval",    type=float, default=60,   help="Seconds between chats (default: 60)")
    parser.add_argument("--action-interval",  type=float, default=30,   help="Seconds between actions (default: 30)")
    parser.add_argument("--confirm-timeout",  type=float, default=5,    help="Seconds to wait for server confirmation (default: 5)")
    parser.add_argument("--max-retries",      type=int,   default=5,    help="Max reconnect attempts (default: 5)")
    parser.add_argument("--no-chat",          action="store_true",      help="Disable chat")
    parser.add_argument("--no-camera",        action="store_true",      help="Disable camera toggles")
    parser.add_argument("--no-mic",           action="store_true",      help="Disable mic toggles")
    parser.add_argument("--no-handraise",     action="store_true",      help="Disable hand raise")
    parser.add_argument("--no-cross-confirm", action="store_true",      help="Disable bots logging observed actions from other bots")
    parser.add_argument("--report-log",       default="report_log.jsonl", help="Path to JSON event log for report generation")
    parser.add_argument("--frontend",         default=DEFAULT_FRONTEND, help="Frontend base URL")
    parser.add_argument("--signal",           default=DEFAULT_SIGNAL,   help="Signal server domain")
    args = parser.parse_args()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print(f"\n{C['yellow']}🛑  Interrupted — shutting down...{C['reset']}", flush=True)
