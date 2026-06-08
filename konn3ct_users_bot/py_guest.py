"""
py_guest.py — Konn3ct Load Testing Bot (WebSocket + Camera/Mic/Hand Raise Simulation)
Simulates attendees joining with realistic random camera, mic, and hand raise activity.

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
    --max-retries       Max reconnect attempts per bot (default: 5)
    --frontend          Frontend base URL (default: https://edge.konn3ct.net)
    --signal            WebSocket signal server domain (default: konn3ctedge.konn3ct.net)
"""

import asyncio
import argparse
import signal
import random
import datetime
import json

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
#  STATS
# ──────────────────────────────────────────────────────────────────────────────
class Stats:
    def __init__(self):
        self.joined     = 0
        self.failed     = 0
        self.active     = 0
        self.left       = 0
        self.reconnects = 0
        self.cameras    = 0   # total camera toggles
        self.mutes      = 0   # total mic toggles
        self.handraises = 0   # total hand raises
        self.lock       = asyncio.Lock()

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
            f"{C['magenta']}📷 cam={self.cameras} 🎤 mic={self.mutes} ✋ hand={self.handraises}{C['reset']}"
        )

stats = Stats()

# ──────────────────────────────────────────────────────────────────────────────
#  BOT STATE  — tracks each bot's current camera/mic/hand state
# ──────────────────────────────────────────────────────────────────────────────
class BotState:
    def __init__(self):
        # Randomise initial state so not all bots start the same
        self.camera_on    = random.choice([True, False])
        self.is_muted     = random.choice([True, False])
        self.hand_raised  = False  # Always start with hand down

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
#  ACTION SIMULATOR — sends camera / mic / hand raise at random intervals
# ──────────────────────────────────────────────────────────────────────────────
async def action_loop(
    ws,
    bot_id:          int,
    name:            str,
    bot_state:       BotState,
    action_interval: float,
    camera_on:       bool,
    mic_on:          bool,
    hand_on:         bool,
    stop_event:      asyncio.Event,
):
    """
    Runs concurrently with the message receive loop.
    Every action_interval (±30%) one random action fires.
    """

    # Send initial state immediately on joining
    if camera_on:
        await ws.send(json.dumps({"type": "camera_state", "isCameraOn": bot_state.camera_on}))
    if mic_on:
        await ws.send(json.dumps({"type": "mute_state",   "isMuted":    bot_state.is_muted}))

    while not stop_event.is_set():
        # Wait a random interval before next action
        wait = random.uniform(action_interval * 0.7, action_interval * 1.3)
        await asyncio.sleep(wait)

        if stop_event.is_set():
            break

        # Pick which actions are enabled this round
        available = []
        if camera_on:   available.append("camera")
        if mic_on:      available.append("mic")
        if hand_on:     available.append("hand")

        if not available:
            break

        action = random.choice(available)

        try:
            if action == "camera":
                bot_state.camera_on = not bot_state.camera_on
                await ws.send(json.dumps({
                    "type":       "camera_state",
                    "isCameraOn": bot_state.camera_on,
                }))
                state_str = "ON 📷" if bot_state.camera_on else "OFF 📷"
                log("📷", C["magenta"], bot_id, name, f"Camera → {state_str}")
                await stats.inc("cameras")

            elif action == "mic":
                bot_state.is_muted = not bot_state.is_muted
                await ws.send(json.dumps({
                    "type":    "mute_state",
                    "isMuted": bot_state.is_muted,
                }))
                state_str = "MUTED 🔇" if bot_state.is_muted else "UNMUTED 🎤"
                log("🎤", C["magenta"], bot_id, name, f"Mic → {state_str}")
                await stats.inc("mutes")

            elif action == "hand":
                bot_state.hand_raised = not bot_state.hand_raised
                await ws.send(json.dumps({
                    "type":         "hand_raise",
                    "isHandRaised": bot_state.hand_raised,
                }))
                state_str = "RAISED ✋" if bot_state.hand_raised else "LOWERED"
                log("✋", C["magenta"], bot_id, name, f"Hand → {state_str}")
                await stats.inc("handraises")

        except Exception:
            break  # WebSocket likely closed — exit loop silently

# ──────────────────────────────────────────────────────────────────────────────
#  WEBSOCKET SESSION
# ──────────────────────────────────────────────────────────────────────────────
async def ws_session(
    ws_url:          str,
    bot_id:          int,
    name:            str,
    auto_leave_s,
    chat_enabled:    bool,
    chat_interval:   float,
    camera_enabled:  bool,
    mic_enabled:     bool,
    hand_enabled:    bool,
    action_interval: float,
    stop_event:      asyncio.Event,
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
            joined_at    = asyncio.get_event_loop().time()
            next_chat_at = joined_at + random.uniform(15, 30)
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

                    # Receive messages
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        msg = json.loads(raw)
                        mtype = msg.get("type")

                        if mtype == "session_status":
                            status = msg.get("status")

                            if status == "active" and not is_active:
                                is_active = True
                                log("🏠", C["cyan"], bot_id, name,
                                    f"In meeting — cam={'ON' if bot_state.camera_on else 'OFF'} "
                                    f"mic={'MUTED' if bot_state.is_muted else 'LIVE'}")

                                # Start action loop as a background task
                                action_task = asyncio.create_task(
                                    action_loop(
                                        ws              = ws,
                                        bot_id          = bot_id,
                                        name            = name,
                                        bot_state       = bot_state,
                                        action_interval = action_interval,
                                        camera_on       = camera_enabled,
                                        mic_on          = mic_enabled,
                                        hand_on         = hand_enabled,
                                        stop_event      = stop_event,
                                    )
                                )

                            elif status == "waiting":
                                log("⏳", C["yellow"], bot_id, name, "In waiting room")

                            elif status in ("denied", "kicked", "ended"):
                                log("🚫", C["red"], bot_id, name, f"Session {status}")
                                await stats.inc("active", -1)
                                await stats.inc("left")
                                return True

                    except asyncio.TimeoutError:
                        pass

                    except websockets.exceptions.ConnectionClosed:
                        log("🔌", C["yellow"], bot_id, name, "Connection closed unexpectedly")
                        await stats.inc("active", -1)
                        return False  # Retry

                    # Chat
                    if chat_enabled and is_active and now >= next_chat_at:
                        try:
                            message = random.choice(CHAT_MESSAGES)
                            await ws.send(json.dumps({"type": "chat", "message": message}))
                            log("💬", C["cyan"], bot_id, name, f'Sent: "{message}"')
                        except Exception:
                            pass
                        next_chat_at = now + random.uniform(
                            chat_interval * 0.8,
                            chat_interval * 1.2,
                        )

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
    max_retries, stop_event, session,
):
    name, email = await generate_identity()

    ws_token = await get_ws_token(session, frontend_url, room_id, name, email, bot_id)
    if not ws_token:
        await stats.inc("failed")
        return

    log("🌐", C["grey"], bot_id, name, "Token acquired — connecting…")
    await stats.inc("joined")

    ws_url  = f"wss://{signal_domain}/signal?roomId={room_id}&token={ws_token}&isMobile=false"
    attempt = 0

    while not stop_event.is_set() and attempt <= max_retries:
        intentional = await ws_session(
            ws_url          = ws_url,
            bot_id          = bot_id,
            name            = name,
            auto_leave_s    = auto_leave_s,
            chat_enabled    = chat_enabled,
            chat_interval   = chat_interval,
            camera_enabled  = camera_enabled,
            mic_enabled     = mic_enabled,
            hand_enabled    = hand_enabled,
            action_interval = action_interval,
            stop_event      = stop_event,
        )

        if intentional or stop_event.is_set():
            break

        attempt += 1
        await stats.inc("reconnects")

        if attempt > max_retries:
            log("❌", C["red"], bot_id, name, f"Max retries ({max_retries}) reached — giving up")
            await stats.inc("failed")
            break

        backoff = min(2 ** attempt, 32) + random.uniform(0, 2)
        log("🔄", C["yellow"], bot_id, name,
            f"Reconnecting in {backoff:.1f}s (attempt {attempt}/{max_retries})…")
        await asyncio.sleep(backoff)

        ws_token = await get_ws_token(session, frontend_url, room_id, name, email, bot_id)
        if not ws_token:
            log("❌", C["red"], bot_id, name, "Could not re-acquire token — giving up")
            await stats.inc("failed")
            break
        ws_url = f"wss://{signal_domain}/signal?roomId={room_id}&token={ws_token}&isMobile=false"

    log("🔒", C["grey"], bot_id, name, "Session ended")

# ──────────────────────────────────────────────────────────────────────────────
#  STATS PRINTER
# ──────────────────────────────────────────────────────────────────────────────
async def stats_printer(stop_event):
    while not stop_event.is_set():
        await asyncio.sleep(5)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"\n{C['grey']}[{ts}] 📊 {stats.summary()}{C['reset']}\n", flush=True)

# ──────────────────────────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────────────────────────
async def main(args):
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

    print(f"\n{C['white']}{'─'*65}{C['reset']}")
    print(f"{C['white']}  🚀 py_guest — Konn3ct Load Bot (Camera + Mic + Hand Raise){C['reset']}")
    print(f"{C['white']}{'─'*65}{C['reset']}")
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
    print(f"  Max retries   : {args.max_retries}")
    print(f"{C['white']}{'─'*65}{C['reset']}\n")

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
                    bot_id          = bot_id,
                    room_id         = args.room,
                    frontend_url    = args.frontend,
                    signal_domain   = args.signal,
                    auto_leave_s    = auto_leave_s,
                    chat_enabled    = not args.no_chat,
                    chat_interval   = args.chat_interval,
                    camera_enabled  = camera_enabled,
                    mic_enabled     = mic_enabled,
                    hand_enabled    = hand_enabled,
                    action_interval = args.action_interval,
                    max_retries     = args.max_retries,
                    stop_event      = stop_event,
                    session         = http_session,
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

    print(f"\n{C['white']}{'─'*65}{C['reset']}")
    print(f"  📊 Final: {stats.summary()}")
    print(f"{C['white']}{'─'*65}{C['reset']}\n")
    print(f"{C['green']}  ✔  All bots stopped. Goodbye!{C['reset']}\n", flush=True)

# ──────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="py_guest — Konn3ct Load Testing Bot")
    parser.add_argument("--room",            default=DEFAULT_ROOM,     help="Room ID")
    parser.add_argument("--bots",            type=int,   default=50,   help="Number of bots (default: 50)")
    parser.add_argument("--leave",           type=int,   default=0,    help="Auto-leave after N min (default: 0)")
    parser.add_argument("--stagger",         type=float, default=1.0,  help="Seconds between batches (default: 1.0)")
    parser.add_argument("--batch",           type=int,   default=3,    help="Bots per batch (default: 3)")
    parser.add_argument("--concurrency",     type=int,   default=100,  help="Max active bots (default: 100)")
    parser.add_argument("--chat-interval",   type=float, default=60,   help="Seconds between chats (default: 60)")
    parser.add_argument("--action-interval", type=float, default=30,   help="Seconds between actions (default: 30)")
    parser.add_argument("--max-retries",     type=int,   default=5,    help="Max reconnect attempts (default: 5)")
    parser.add_argument("--no-chat",         action="store_true",      help="Disable chat")
    parser.add_argument("--no-camera",       action="store_true",      help="Disable camera toggles")
    parser.add_argument("--no-mic",          action="store_true",      help="Disable mic toggles")
    parser.add_argument("--no-handraise",    action="store_true",      help="Disable hand raise")
    parser.add_argument("--frontend",        default=DEFAULT_FRONTEND, help="Frontend base URL")
    parser.add_argument("--signal",          default=DEFAULT_SIGNAL,   help="Signal server domain")
    args = parser.parse_args()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print(f"\n{C['yellow']}🛑  Interrupted — shutting down...{C['reset']}", flush=True)
