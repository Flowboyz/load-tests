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
import sys
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

# Force UTF-8 stdout/stderr for Windows terminal compatibility
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

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

REACTION_EMOJIS = ["👍", "👏", "❤️", "🎉", "😂", "😮", "🤔", "🔥", "💯", "✅", "👋", "🙌"]

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
        self.polls       = 0   # confirmed poll creates
        self.votes       = 0   # confirmed poll votes
        self.notes       = 0   # confirmed note updates
        self.reactions   = 0   # confirmed reaction sends
        self.unconfirmed = 0   # actions that timed out waiting for confirmation
        self.desyncs     = 0   # desync occurrences
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
            f"{C['magenta']}📷 cam={self.cameras} 🎤 mic={self.mutes} ✋ hand={self.handraises} 💬 chat={self.chats} 🗳️ vote={self.votes} 📊 poll={self.polls} 📝 note={self.notes} 👍 react={self.reactions}{C['reset']}  "
            f"{C['red']}⚠️ unconfirmed={self.unconfirmed} ⚡ desyncs={self.desyncs}{C['reset']}"
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
        self.persona     = "lurker"
        self.muted_by_host = False

# ──────────────────────────────────────────────────────────────────────────────
#  ACTION SIMULATOR — sends camera / mic / hand raise / chat at intervals
# ──────────────────────────────────────────────────────────────────────────────
async def send_poll_vote_delayed(ws, poll_id, bot_id, name, pending):
    await asyncio.sleep(random.uniform(2, 6))
    now = asyncio.get_event_loop().time()
    vote_id = f"vote-{bot_id}-{int(now*1000)}"
    try:
        await ws.send(json.dumps({
            "type": "poll_vote",
            "pollId": poll_id,
            "optionIndex": random.choice([0, 1, 2]),
            "clientMsgId": vote_id
        }))
        pending.add(f"poll_vote:{vote_id}", poll_id, now)
        log("🗳️", C["cyan"], bot_id, name, f"Voted on poll '{poll_id}' (awaiting confirmation…)")
        if recorder:
            await recorder.record("action_sent", bot_id, name, action="poll_vote", value=vote_id)
    except Exception:
        pass

async def action_loop_main(
    ws, bot_id, name, bot_state, pending,
    action_interval, chat_interval,
    camera_on, mic_on, hand_on, chat_on,
    stop_event,
):
    """
    Cleaner single-loop version: fires one random toggle action on action_interval,
    and chat independently on chat_interval. Upgraded to support bot personas.
    """
    now = asyncio.get_event_loop().time()
    persona = bot_state.persona

    # Set initial state according to persona
    if persona == "presenter":
        bot_state.camera_on = True
        bot_state.is_muted = False
    elif persona == "lurker":
        bot_state.camera_on = False
        bot_state.is_muted = True

    # Initial state push
    if persona in ("presenter", "active", "churner"):
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
    next_chat_at   = now + random.uniform(15, 45)
    next_reaction_at = now + random.uniform(10, 25)
    next_poll_at   = now + random.uniform(30, 60)
    next_note_at   = now + random.uniform(25, 55)
    next_abnormal_at = now + random.uniform(action_interval * 0.7, action_interval * 1.3)

    while not stop_event.is_set():
        await asyncio.sleep(1)
        if stop_event.is_set():
            break
        now = asyncio.get_event_loop().time()

        # Hostile mode checks
        if persona == "hostile":
            try:
                await ws.send("HOSTILE_MALFORMED_DATA_SPAM")
                await ws.send(json.dumps({"type": "hostile_spam", "spam": "random"}))
            except Exception:
                pass
            log("🚫", C["red"], bot_id, name, "Hostile persona disconnecting abruptly")
            break

        # Random toggle action (Active and Churner only)
        if persona in ("active", "churner") and now >= next_action_at:
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

        # Chat (Presenter, Active, Churner)
        if chat_on and persona in ("presenter", "active", "churner") and now >= next_chat_at:
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
            interval_factor = 0.5 if persona == "presenter" else 1.0
            next_chat_at = now + random.uniform(chat_interval * 0.8, chat_interval * 1.2) * interval_factor

        # Reactions (all except hostile)
        if now >= next_reaction_at:
            should_react = False
            if persona == "presenter" and random.random() < 0.6:
                should_react = True
            elif persona in ("active", "churner") and random.random() < 0.4:
                should_react = True
            elif persona == "lurker" and random.random() < 0.1:
                should_react = True

            if should_react:
                react = random.choice(REACTION_EMOJIS)
                react_id = f"react-{bot_id}-{int(now*1000)}"
                try:
                    await ws.send(json.dumps({"type": "reaction", "reaction": react, "clientMsgId": react_id}))
                    pending.add(f"reaction:{react_id}", react, now)
                    log("👍", C["cyan"], bot_id, name, f"Sent reaction: {react} (awaiting confirmation…)")
                    if recorder:
                        await recorder.record("action_sent", bot_id, name, action="reaction", value=react)
                except Exception:
                    pass
            next_reaction_at = now + random.uniform(10, 25)

        # Polls (only presenters)
        if persona == "presenter" and now >= next_poll_at:
            poll_id = f"poll-{bot_id}-{int(now*1000)}"
            try:
                await ws.send(json.dumps({
                    "type": "poll_create",
                    "pollId": poll_id,
                    "question": "How is the connection?",
                    "options": ["Excellent", "Good", "Poor"],
                    "clientMsgId": poll_id
                }))
                pending.add(f"poll_create:{poll_id}", "connection", now)
                log("📊", C["cyan"], bot_id, name, f"Sent: Poll '{poll_id}' (awaiting confirmation…)")
                if recorder:
                    await recorder.record("action_sent", bot_id, name, action="poll_create", value=poll_id)
            except Exception:
                pass
            next_poll_at = now + random.uniform(45, 95)

        # Shared notes (only presenters)
        if persona == "presenter" and now >= next_note_at:
            note_id = f"note-{bot_id}-{int(now*1000)}"
            try:
                await ws.send(json.dumps({
                    "type": "note_update",
                    "content": f"Meeting notes update from presenter {name}",
                    "clientMsgId": note_id
                }))
                pending.add(f"note_update:{note_id}", "content", now)
                log("📝", C["cyan"], bot_id, name, f"Sent: Note update (awaiting confirmation…)")
                if recorder:
                    await recorder.record("action_sent", bot_id, name, action="note_update", value=note_id)
            except Exception:
                pass
            next_note_at = now + random.uniform(30, 60)

        # Abnormal action (Abnormal persona only)
        if persona == "abnormal" and now >= next_abnormal_at:
            abnormal_actions = ["unauthorized_poll_create", "unauthorized_note_update", "invalid_poll_vote", "malformed_payload", "chat_spamming", "premium_features_unauthorized", "unmute_after_host_mute"]
            if not bot_state.muted_by_host:
                abnormal_actions.remove("unmute_after_host_mute")
            chosen = random.choice(abnormal_actions)
            try:
                if chosen == "unauthorized_poll_create":
                    poll_id = f"abnormal-poll-{bot_id}-{int(now*1000)}"
                    await ws.send(json.dumps({
                        "type": "poll_create",
                        "pollId": poll_id,
                        "question": "Should abnormal bots be allowed?",
                        "options": ["Yes", "No"],
                        "clientMsgId": poll_id
                    }))
                    pending.add(f"abnormal:poll_create:{poll_id}", "poll", now)
                    log("⚠️", C["yellow"], bot_id, name, f"Tried to create poll (unauthorized) → awaiting confirmation…")
                    if recorder:
                        await recorder.record("abnormal_action_sent", bot_id, name, action="poll_create", details="Tried to create poll (unauthorized)")
                
                elif chosen == "unauthorized_note_update":
                    note_id = f"abnormal-note-{bot_id}-{int(now*1000)}"
                    await ws.send(json.dumps({
                        "type": "note_update",
                        "content": f"Abnormal note update from unauthorized bot {name}",
                        "clientMsgId": note_id
                    }))
                    pending.add(f"abnormal:note_update:{note_id}", "note", now)
                    log("⚠️", C["yellow"], bot_id, name, f"Tried to update note (unauthorized) → awaiting confirmation…")
                    if recorder:
                        await recorder.record("abnormal_action_sent", bot_id, name, action="note_update", details="Tried to update note (unauthorized)")

                elif chosen == "invalid_poll_vote":
                    fake_poll_id = f"non-existent-poll-{int(now*1000)}"
                    await ws.send(json.dumps({
                        "type": "poll_vote",
                        "pollId": fake_poll_id,
                        "voteId": 1,
                        "clientMsgId": fake_poll_id
                    }))
                    pending.add(f"abnormal:poll_vote:{fake_poll_id}", "vote", now)
                    log("⚠️", C["yellow"], bot_id, name, f"Tried to vote on non-existent poll → awaiting confirmation…")
                    if recorder:
                        await recorder.record("abnormal_action_sent", bot_id, name, action="poll_vote", details="Tried to vote on non-existent poll")

                elif chosen == "malformed_payload":
                    if random.choice([True, False]):
                        chat_id = f"abnormal-chat-malformed-{bot_id}-{int(now*1000)}"
                        await ws.send(json.dumps({
                            "type": "chat",
                            "clientMsgId": chat_id
                        }))
                        pending.add(f"abnormal:malformed_payload:{chat_id}", "chat", now)
                        log("⚠️", C["yellow"], bot_id, name, f"Tried to send malformed chat payload (unauthorized) → awaiting confirmation…")
                        if recorder:
                            await recorder.record("abnormal_action_sent", bot_id, name, action="malformed_payload", details="Tried to send malformed chat payload (missing message text)")
                    else:
                        cam_id = f"abnormal-cam-malformed-{bot_id}-{int(now*1000)}"
                        await ws.send(json.dumps({
                            "type": "camera_state",
                            "isCameraOn": "invalid-non-bool",
                            "clientMsgId": cam_id
                        }))
                        pending.add("abnormal:malformed_payload:camera", "camera", now)
                        log("⚠️", C["yellow"], bot_id, name, f"Tried to send malformed camera state (unauthorized) → awaiting confirmation…")
                        if recorder:
                            await recorder.record("abnormal_action_sent", bot_id, name, action="malformed_payload", details="Tried to send malformed camera state payload (invalid datatype)")

                elif chosen == "chat_spamming":
                    log("⚠️", C["yellow"], bot_id, name, f"Initiating rate-limit bypass chat spamming (sending 5 rapid messages)…")
                    if recorder:
                        await recorder.record("abnormal_action_sent", bot_id, name, action="chat_spamming", details="Initiating rate-limit bypass chat spamming (5 rapid messages)")
                    for i in range(5):
                        spam_id = f"abnormal-spam-{bot_id}-{i}-{int(now*1000)}"
                        await ws.send(json.dumps({
                            "type": "chat",
                            "message": f"Spam message {i}!",
                            "clientMsgId": spam_id
                        }))
                        pending.add(f"abnormal:chat_spamming:{spam_id}", "chat", now)

                elif chosen == "premium_features_unauthorized":
                    ns_id = f"abnormal-ns-{bot_id}-{int(now*1000)}"
                    await ws.send(json.dumps({
                        "type": "noise_suppression",
                        "enabled": True,
                        "clientMsgId": ns_id
                    }))
                    pending.add(f"abnormal:premium_features:{ns_id}", "premium", now)
                    log("⚠️", C["yellow"], bot_id, name, f"Tried to enable AI Noise Suppression (premium feature) → awaiting confirmation…")
                    if recorder:
                        await recorder.record("abnormal_action_sent", bot_id, name, action="premium_features", details="Tried to enable AI Noise Suppression (premium feature)")

                elif chosen == "unmute_after_host_mute":
                    unmute_id = f"abnormal-unmute-{bot_id}-{int(now*1000)}"
                    bot_state.is_muted = False
                    await ws.send(json.dumps({
                        "type": "mute_state",
                        "isMuted": False,
                        "clientMsgId": unmute_id
                    }))
                    pending.add("abnormal:host_mute_bypass", "mute", now)
                    log("⚠️", C["yellow"], bot_id, name, f"Attempting host mute bypass (trying to unmute self) → awaiting confirmation…")
                    if recorder:
                        await recorder.record("abnormal_action_sent", bot_id, name, action="host_mute_bypass", details="Attempted host mute bypass (trying to unmute self after host mute)")

            except Exception:
                break
            next_abnormal_at = now + random.uniform(action_interval * 0.7, action_interval * 1.3)

async def ws_session(
    ws_url, bot_id, name, bot_state, connection_start_time, auto_leave_s,
    chat_enabled, chat_interval,
    camera_enabled, mic_enabled, hand_enabled, action_interval,
    confirm_timeout, cross_confirm,
    stop_event,
) -> (bool, bool):
    """
    Returns (intentional, joined_active)
    intentional: True = intentional disconnect (no retry), False = unexpected / churner reconnect
    joined_active: True = successfully completed join sequence to active meeting
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

            pending      = PendingActions()
            joined_at    = asyncio.get_event_loop().time()
            is_active    = False
            action_task  = None

            if bot_state.persona == "churner":
                auto_leave_s = random.uniform(30, 90)

            try:
                while not stop_event.is_set():
                    now = asyncio.get_event_loop().time()

                    # Auto-leave
                    if auto_leave_s and (now - joined_at) >= auto_leave_s:
                        if bot_state.persona == "churner":
                            log("🚪", C["yellow"], bot_id, name, f"Churner auto-leaving after {auto_leave_s:.1f}s")
                            try:
                                await ws.send(json.dumps({"type": "leave_meeting"}))
                            except Exception:
                                pass
                            await stats.inc("active", -1)
                            await stats.inc("left")
                            return False, is_active
                        else:
                            log("🚪", C["yellow"], bot_id, name, "Auto-leaving")
                            try:
                                await ws.send(json.dumps({"type": "leave_meeting"}))
                            except Exception:
                                pass
                            await stats.inc("active", -1)
                            await stats.inc("left")
                            return True, is_active

                    # Check for timed-out (unconfirmed) actions
                    for action_key, expected_value in pending.sweep_timeouts(now, confirm_timeout):
                        if action_key.startswith("abnormal:"):
                            parts = action_key.split(":")
                            action_name = parts[1]
                            log("🛡️", C["green"], bot_id, name,
                                f"tried to {action_name} and it didn't work")
                            if recorder:
                                await recorder.record("abnormal_action_resolved", bot_id, name,
                                                       action=action_name, outcome="blocked", status="PASS",
                                                       details=f"tried to {action_name} and it didn't work (correctly blocked)")
                        else:
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
                                elapsed_ms = (datetime.datetime.now() - connection_start_time).total_seconds() * 1000
                                log("🏠", C["cyan"], bot_id, name,
                                    f"In meeting (Time-to-Active: {elapsed_ms:.0f}ms) — cam={'ON' if bot_state.camera_on else 'OFF'} "
                                    f"mic={'MUTED' if bot_state.is_muted else 'LIVE'}")
                                if recorder:
                                    await recorder.record("time_to_active", bot_id, name, email=bot_state.user_id + "@botmail.test" if bot_state.user_id else "", elapsed_ms=elapsed_ms)

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
                                return True, is_active

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
                            
                            local_count = len(participants)
                            if local_count < stats.active:
                                await stats.inc("desyncs")
                                log("⚠️", C["red"], bot_id, name, f"Desync Detected! Local list has {local_count} participants, but process has {stats.active} active bots.")
                                if recorder:
                                    await recorder.record("desync_detected", bot_id, name, local_count=local_count, active_count=stats.active)

                        elif mtype == "camera_state":
                            uid = msg.get("userId")
                            is_on = msg.get("isCameraOn")
                            if uid == bot_state.user_id:
                                result = pending.confirm("abnormal:malformed_payload:camera")
                                if result:
                                    log("❌", C["red"], bot_id, name,
                                        f"tried to malformed_payload (camera) and it WORKED (incorrectly allowed!)")
                                    if recorder:
                                        await recorder.record("abnormal_action_resolved", bot_id, name,
                                                               action="malformed_payload", outcome="allowed", status="FAIL",
                                                               details="Server incorrectly allowed malformed camera_state payload")
                                else:
                                    # Self-confirmation
                                    result = pending.confirm("camera")
                                    if result:
                                        elapsed = asyncio.get_event_loop().time() - result[1]
                                        elapsed_ms = elapsed * 1000
                                        await stats.inc("cameras")
                                        log("📷", C["green"], bot_id, name,
                                            f"Camera → {'ON' if is_on else 'OFF'} "
                                            f"(✅ confirmed by server, propagation: {elapsed_ms:.1f}ms)")
                                        if recorder:
                                            await recorder.record("action_confirmed", bot_id, name,
                                                                   action="camera", value=is_on, elapsed_ms=elapsed_ms)
                            elif cross_confirm:
                                other_name = await registry.lookup(uid)
                                log("👀", C["blue"], bot_id, name,
                                    f"observed: {other_name} turned camera "
                                    f"{'ON' if is_on else 'OFF'}")

                        elif mtype == "mute_state":
                            uid = msg.get("userId")
                            is_muted = msg.get("isMuted")
                            if uid == bot_state.user_id:
                                result = pending.confirm("abnormal:host_mute_bypass")
                                if result:
                                    log("❌", C["red"], bot_id, name,
                                        f"tried to host_mute_bypass and it WORKED (incorrectly allowed!)")
                                    if recorder:
                                        await recorder.record("abnormal_action_resolved", bot_id, name,
                                                               action="host_mute_bypass", outcome="allowed", status="FAIL",
                                                               details="Server incorrectly allowed bot to unmute after host mute")
                                else:
                                    result = pending.confirm("mic")
                                    if result:
                                        elapsed = asyncio.get_event_loop().time() - result[1]
                                        elapsed_ms = elapsed * 1000
                                        await stats.inc("mutes")
                                        log("🎤", C["green"], bot_id, name,
                                            f"Mic → {'MUTED' if is_muted else 'UNMUTED'} "
                                            f"(✅ confirmed by server, propagation: {elapsed_ms:.1f}ms)")
                                        if recorder:
                                            await recorder.record("action_confirmed", bot_id, name,
                                                                   action="mic", value=is_muted, elapsed_ms=elapsed_ms)
                                    elif is_muted:
                                        # Host muted this bot
                                        bot_state.is_muted = True
                                        bot_state.muted_by_host = True
                                        log("🎤", C["yellow"], bot_id, name, "Muted by Host!")
                                        
                                        # If the bot is abnormal, it will immediately try to unmute itself in response!
                                        if bot_state.persona == "abnormal":
                                            async def try_unmute_delayed():
                                                await asyncio.sleep(random.uniform(1.5, 3))
                                                unmute_id = f"abnormal-unmute-{bot_id}-{int(asyncio.get_event_loop().time()*1000)}"
                                                bot_state.is_muted = False
                                                try:
                                                    await ws.send(json.dumps({
                                                        "type": "mute_state",
                                                        "isMuted": False,
                                                        "clientMsgId": unmute_id
                                                    }))
                                                    pending.add("abnormal:host_mute_bypass", "mute", asyncio.get_event_loop().time())
                                                    log("⚠️", C["yellow"], bot_id, name, f"Attempting host mute bypass (trying to unmute self) → awaiting confirmation…")
                                                    if recorder:
                                                        await recorder.record("abnormal_action_sent", bot_id, name, action="host_mute_bypass", details="Attempted host mute bypass (trying to unmute self after host mute)")
                                                except Exception:
                                                    pass
                                            asyncio.create_task(try_unmute_delayed())
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
                                    elapsed = asyncio.get_event_loop().time() - result[1]
                                    elapsed_ms = elapsed * 1000
                                    await stats.inc("handraises")
                                    log("✋", C["green"], bot_id, name,
                                        f"Hand → {'RAISED' if is_raised else 'LOWERED'} "
                                        f"(✅ confirmed by server, propagation: {elapsed_ms:.1f}ms)")
                                    if recorder:
                                        await recorder.record("action_confirmed", bot_id, name,
                                                               action="hand", value=is_raised, elapsed_ms=elapsed_ms)
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
                                result = pending.confirm(f"abnormal:malformed_payload:{client_id}")
                                if result:
                                    log("❌", C["red"], bot_id, name,
                                        f"tried to malformed_payload (chat) and it WORKED (incorrectly allowed!)")
                                    if recorder:
                                        await recorder.record("abnormal_action_resolved", bot_id, name,
                                                               action="malformed_payload", outcome="allowed", status="FAIL",
                                                               details="Server incorrectly allowed malformed chat payload")
                                else:
                                    result = pending.confirm(f"abnormal:chat_spamming:{client_id}")
                                    if result:
                                        log("❌", C["red"], bot_id, name,
                                            f"tried to chat_spamming and it WORKED (incorrectly allowed rate limit bypass!)")
                                        if recorder:
                                            await recorder.record("abnormal_action_resolved", bot_id, name,
                                                                   action="chat_spamming", outcome="allowed", status="FAIL",
                                                                   details="Server incorrectly allowed chat spamming without rate limiting")
                                    else:
                                        result = pending.confirm(f"chat:{client_id}")
                                        if result:
                                            elapsed = asyncio.get_event_loop().time() - result[1]
                                            elapsed_ms = elapsed * 1000
                                            await stats.inc("chats")
                                            log("💬", C["green"], bot_id, name,
                                                f'Chat "{chat_msg}" (✅ confirmed delivered by server, propagation: {elapsed_ms:.1f}ms)')
                                            if recorder:
                                                await recorder.record("action_confirmed", bot_id, name,
                                                                       action="chat", value=chat_msg, elapsed_ms=elapsed_ms)

                        elif mtype == "noise_suppression":
                            uid = msg.get("userId")
                            client_id = msg.get("clientMsgId")
                            if uid == bot_state.user_id and client_id:
                                result = pending.confirm(f"abnormal:premium_features:{client_id}")
                                if result:
                                    log("❌", C["red"], bot_id, name,
                                        f"tried to premium_features and it WORKED (incorrectly allowed!)")
                                    if recorder:
                                        await recorder.record("abnormal_action_resolved", bot_id, name,
                                                               action="premium_features", outcome="allowed", status="FAIL",
                                                               details="Server incorrectly allowed unauthorized premium feature toggle")
                            elif uid != bot_state.user_id and cross_confirm:
                                other_name = msg.get("name") or await registry.lookup(uid)
                                log("👀", C["blue"], bot_id, name,
                                    f'observed: {other_name} sent "{chat_msg}"')

                        elif mtype == "reaction":
                            uid = msg.get("userId")
                            react = msg.get("reaction")
                            client_id = msg.get("clientMsgId")
                            if uid == bot_state.user_id and client_id:
                                result = pending.confirm(f"reaction:{client_id}")
                                if result:
                                    elapsed = asyncio.get_event_loop().time() - result[1]
                                    elapsed_ms = elapsed * 1000
                                    await stats.inc("reactions")
                                    log("👍", C["green"], bot_id, name,
                                        f"Reaction {react} (✅ confirmed by server, propagation: {elapsed_ms:.1f}ms)")
                                    if recorder:
                                        await recorder.record("action_confirmed", bot_id, name,
                                                               action="reaction", value=react, elapsed_ms=elapsed_ms)
                            elif cross_confirm:
                                other_name = await registry.lookup(uid)
                                log("👀", C["blue"], bot_id, name,
                                    f"observed: {other_name} reacted with {react}")

                        elif mtype == "poll_create":
                            uid = msg.get("userId")
                            poll_id = msg.get("pollId")
                            client_id = msg.get("clientMsgId")
                            if uid == bot_state.user_id and client_id:
                                result = pending.confirm(f"abnormal:poll_create:{client_id}")
                                if result:
                                    log("❌", C["red"], bot_id, name,
                                        f"tried to poll_create and it WORKED (incorrectly allowed!)")
                                    if recorder:
                                        await recorder.record("abnormal_action_resolved", bot_id, name,
                                                               action="poll_create", outcome="allowed", status="FAIL",
                                                               details=f"Server incorrectly allowed unauthorized poll creation '{poll_id}'")
                                else:
                                    result = pending.confirm(f"poll_create:{client_id}")
                                    if result:
                                        elapsed = asyncio.get_event_loop().time() - result[1]
                                        elapsed_ms = elapsed * 1000
                                        await stats.inc("polls")
                                        log("📊", C["green"], bot_id, name,
                                            f"Poll '{poll_id}' (✅ confirmed created by server, propagation: {elapsed_ms:.1f}ms)")
                                        if recorder:
                                            await recorder.record("action_confirmed", bot_id, name,
                                                                   action="poll_create", value=poll_id, elapsed_ms=elapsed_ms)
                            elif uid != bot_state.user_id:
                                other_name = await registry.lookup(uid)
                                log("👀", C["blue"], bot_id, name, f"observed: Presenter {other_name} created poll '{poll_id}'")
                                if bot_state.persona in ("active", "lurker") and random.random() < 0.4:
                                    asyncio.create_task(send_poll_vote_delayed(ws, poll_id, bot_id, name, pending))

                        elif mtype == "poll_vote":
                            uid = msg.get("userId")
                            client_id = msg.get("clientMsgId")
                            if uid == bot_state.user_id and client_id:
                                result = pending.confirm(f"abnormal:poll_vote:{client_id}")
                                if result:
                                    log("❌", C["red"], bot_id, name,
                                        f"tried to poll_vote and it WORKED (incorrectly allowed!)")
                                    if recorder:
                                        await recorder.record("abnormal_action_resolved", bot_id, name,
                                                               action="poll_vote", outcome="allowed", status="FAIL",
                                                               details="Server incorrectly allowed vote on non-existent poll")
                                else:
                                    result = pending.confirm(f"poll_vote:{client_id}")
                                    if result:
                                        elapsed = asyncio.get_event_loop().time() - result[1]
                                        elapsed_ms = elapsed * 1000
                                        await stats.inc("votes")
                                        log("🗳️", C["green"], bot_id, name,
                                            f"Poll vote (✅ confirmed by server, propagation: {elapsed_ms:.1f}ms)")
                                        if recorder:
                                            await recorder.record("action_confirmed", bot_id, name,
                                                                   action="poll_vote", value=result[0], elapsed_ms=elapsed_ms)

                        elif mtype == "note_update":
                            uid = msg.get("userId")
                            client_id = msg.get("clientMsgId")
                            if uid == bot_state.user_id and client_id:
                                result = pending.confirm(f"abnormal:note_update:{client_id}")
                                if result:
                                    log("❌", C["red"], bot_id, name,
                                        f"tried to note_update and it WORKED (incorrectly allowed!)")
                                    if recorder:
                                        await recorder.record("abnormal_action_resolved", bot_id, name,
                                                               action="note_update", outcome="allowed", status="FAIL",
                                                               details="Server incorrectly allowed unauthorized note update")
                                else:
                                    result = pending.confirm(f"note_update:{client_id}")
                                    if result:
                                        elapsed = asyncio.get_event_loop().time() - result[1]
                                        elapsed_ms = elapsed * 1000
                                        await stats.inc("notes")
                                        log("📝", C["green"], bot_id, name,
                                            f"Note update (✅ confirmed by server, propagation: {elapsed_ms:.1f}ms)")
                                        if recorder:
                                            await recorder.record("action_confirmed", bot_id, name,
                                                                   action="note_update", value="", elapsed_ms=elapsed_ms)

                    except asyncio.TimeoutError:
                        pass

                    except websockets.exceptions.ConnectionClosed:
                        log("🔌", C["yellow"], bot_id, name, "Connection closed unexpectedly")
                        await stats.inc("active", -1)
                        return False, is_active

                # Stop event fired
                try:
                    await ws.send(json.dumps({"type": "leave_meeting"}))
                except Exception:
                    pass
                await stats.inc("active", -1)
                await stats.inc("left")
                return True, is_active

            finally:
                if action_task and not action_task.done():
                    action_task.cancel()
                    try:
                        await action_task
                    except asyncio.CancelledError:
                        pass

    except (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError) as exc:
        log("⚠️", C["yellow"], bot_id, name, f"Connection error: {type(exc).__name__}: {exc}")
        return False, False

    except Exception as exc:
        log("❌", C["red"], bot_id, name, f"Unexpected error: {exc}")
        return False, False

# ──────────────────────────────────────────────────────────────────────────────
#  BOT COROUTINE  (handles retries)
# ──────────────────────────────────────────────────────────────────────────────
async def run_bot(
    bot_id, room_id, frontend_url, signal_domain,
    auto_leave_s, chat_enabled, chat_interval,
    camera_enabled, mic_enabled, hand_enabled, action_interval,
    confirm_timeout, cross_confirm,
    max_retries, stop_event, session,
    persona_ratios,
):
    name, email = await generate_identity()
    bot_started_at = asyncio.get_event_loop().time()

    # Assign Persona
    personas = ["lurker", "active", "presenter", "churner", "hostile", "abnormal"]
    weights = [
        persona_ratios.get("lurkers_ratio", 0.75),
        persona_ratios.get("active_ratio", 0.15),
        persona_ratios.get("presenters_ratio", 0.05),
        persona_ratios.get("churners_ratio", 0.05),
        persona_ratios.get("hostiles_ratio", 0.00),
        persona_ratios.get("abnormal_ratio", 0.00),
    ]
    w_sum = sum(weights)
    if w_sum > 0:
        weights = [w / w_sum for w in weights]
    else:
        weights = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    persona = random.choices(personas, weights=weights)[0]

    bot_state = BotState()
    bot_state.persona = persona

    log("👤", C["grey"], bot_id, name, f"Assigned persona: {persona.upper()}")
    if recorder:
        await recorder.record("persona_assigned", bot_id, name, email, persona=persona)

    connection_start_time = datetime.datetime.now()
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
        intentional, joined_active = await ws_session(
            ws_url=ws_url, bot_id=bot_id, name=name, bot_state=bot_state,
            connection_start_time=connection_start_time,
            auto_leave_s=auto_leave_s,
            chat_enabled=chat_enabled, chat_interval=chat_interval,
            camera_enabled=camera_enabled, mic_enabled=mic_enabled,
            hand_enabled=hand_enabled, action_interval=action_interval,
            confirm_timeout=confirm_timeout, cross_confirm=cross_confirm,
            stop_event=stop_event,
        )

        if intentional or stop_event.is_set():
            break

        if joined_active:
            attempt = 0  # Reset retry attempts on successful connection

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

        connection_start_time = datetime.datetime.now()
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
                chats=stats.chats, polls=stats.polls, votes=stats.votes,
                notes=stats.notes, reactions=stats.reactions,
                unconfirmed=stats.unconfirmed, desyncs=stats.desyncs,
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

    persona_ratios = {
        "lurkers_ratio": args.lurkers_ratio,
        "active_ratio": args.active_ratio,
        "presenters_ratio": args.presenters_ratio,
        "churners_ratio": args.churners_ratio,
        "hostiles_ratio": args.hostiles_ratio,
        "abnormal_ratio": args.abnormal_ratio,
    }

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
        lurkers_ratio=args.lurkers_ratio, active_ratio=args.active_ratio,
        presenters_ratio=args.presenters_ratio, churners_ratio=args.churners_ratio,
        hostiles_ratio=args.hostiles_ratio, abnormal_ratio=args.abnormal_ratio,
    )

    print(f"\n{C['white']}{'-'*70}{C['reset']}")
    print(f"{C['white']}  🚀 py_guest — Konn3ct Load Bot (Confirmed Action Tracking & Personas){C['reset']}")
    print(f"{C['white']}{'-'*70}{C['reset']}")
    print(f"  Room          : {args.room}")
    print(f"  Bots          : {args.bots}")
    print(f"  Batch         : {args.batch} bots every {args.stagger}s")
    print(f"  Concurrency   : {args.concurrency} max active at once")
    print(f"  Auto-leave    : {'manual (Ctrl+C)' if not auto_leave_s else f'{args.leave} min'}")
    print(f"  Chat          : {'ON (~every ' + str(args.chat_interval) + 's)' if not args.no_chat else 'OFF'}")
    print(f"  Camera toggle : {'ON' if camera_enabled else 'OFF'}")
    print(f"  Mic toggle    : {'ON' if mic_enabled else 'OFF'}")
    print(f"  Hand raise    : {'ON' if hand_enabled else 'OFF'}")
    print(f"  Ratios        : Lurker={args.lurkers_ratio:.2f}, Active={args.active_ratio:.2f}, Presenter={args.presenters_ratio:.2f}, Churner={args.churners_ratio:.2f}, Hostile={args.hostiles_ratio:.2f}, Abnormal={args.abnormal_ratio:.2f}")
    print(f"  Action every  : ~{args.action_interval}s per bot (randomised ±30%)")
    print(f"  Confirm wait  : {args.confirm_timeout}s before flagging unconfirmed")
    print(f"  Cross-confirm : {'ON (bots log others actions)' if cross_confirm else 'OFF'}")
    print(f"  Max retries   : {args.max_retries}")
    print(f"{C['white']}{'-'*70}{C['reset']}\n")

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
                    persona_ratios=persona_ratios,
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

    print(f"\n{C['white']}{'-'*70}{C['reset']}")
    print(f"  📊 Final: {stats.summary()}")
    print(f"{C['white']}{'-'*70}{C['reset']}\n")
    print(f"{C['green']}  ✔  All bots stopped. Goodbye!{C['reset']}\n", flush=True)

    if recorder:
        await recorder.record_final({
            "joined": stats.joined, "active": stats.active, "left": stats.left,
            "failed": stats.failed, "reconnects": stats.reconnects,
            "cameras": stats.cameras, "mutes": stats.mutes, "handraises": stats.handraises,
            "chats": stats.chats, "polls": stats.polls, "votes": stats.votes,
            "notes": stats.notes, "reactions": stats.reactions,
            "unconfirmed": stats.unconfirmed, "desyncs": stats.desyncs,
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
    parser.add_argument("--lurkers-ratio",    type=float, default=0.75, help="Ratio of lurkers (default: 0.75)")
    parser.add_argument("--active-ratio",     type=float, default=0.15, help="Ratio of active bots (default: 0.15)")
    parser.add_argument("--presenters-ratio", type=float, default=0.05, help="Ratio of presenters (default: 0.05)")
    parser.add_argument("--churners-ratio",   type=float, default=0.05, help="Ratio of churners (default: 0.05)")
    parser.add_argument("--hostiles-ratio",   type=float, default=0.00, help="Ratio of hostile bots (default: 0.00)")
    parser.add_argument("--abnormal-ratio",   type=float, default=0.00, help="Ratio of abnormal bots (default: 0.00)")
    parser.add_argument("--report-log",       default="report_log.jsonl", help="Path to JSON event log for report generation")
    parser.add_argument("--frontend",         default=DEFAULT_FRONTEND, help="Frontend base URL")
    parser.add_argument("--signal",           default=DEFAULT_SIGNAL,   help="Signal server domain")
    args = parser.parse_args()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print(f"\n{C['yellow']}🛑  Interrupted — shutting down...{C['reset']}", flush=True)
