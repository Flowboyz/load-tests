"""
py_guest_1k.py — Konn3ct Load Testing Bot (1000+ Users / Process-Pool Mode)
Simulates 1000+ guests joining a Konn3ct meeting.

Architecture:
    Orchestrator (this file)
        └── N worker processes, each running:
                └── 1 Chromium browser
                        └── CONTEXTS_PER_WORKER isolated contexts (bots)

Why not one browser with 1000 contexts?
    - Chromium crashes above ~150–200 contexts in a single process
    - 1000 contexts × ~25MB each = 25GB RAM in one process
    - Network saturation causes mass goto-timeouts

This design spreads load across OS processes so:
    - Each browser handles a safe 40–50 contexts max
    - A crash in one worker doesn't affect others
    - The orchestrator auto-restarts dead workers
    - Total RAM scales linearly and predictably

Dependencies:
    pip install faker playwright
    playwright install chromium

Usage:
    python py_guest_1k.py --url "https://konn3ct.com/join/..." --bots 1000
    python py_guest_1k.py --url "https://..." --bots 500  --leave 30
    python py_guest_1k.py --url "https://..." --bots 1000 --workers 25 --contexts 40
    python py_guest_1k.py --url "https://..." --bots 200  --no-chat --stagger-min 2

Arguments:
    --url               Meeting URL (required)
    --bots              Total number of bots  (default: 1000)
    --workers           Worker processes to spawn (default: auto = ceil(bots/contexts))
    --contexts          Contexts per worker browser (default: 40, max recommended: 50)
    --leave             Auto-leave after N minutes, 0 = manual Ctrl+C (default: 0)
    --stagger-min       Min seconds between each bot joining within a worker (default: 1)
    --stagger-max       Max seconds between each bot joining within a worker (default: 3)
    --batch-pause       Seconds between worker batch waves (default: 15)
    --no-chat           Disable chat messages
    --no-headless       Show browser windows (not recommended for 1000 bots)

Scaling guide:
    Bots    Workers  Contexts  Approx RAM   Approx CPU cores needed
    100     3        40        ~3 GB        2
    500     13       40        ~13 GB       4–6
    1000    25       40        ~25 GB       8–12
    2000    50       40        ~50 GB       16+
"""

import argparse
import asyncio
import datetime
import math
import multiprocessing
import os
import random
import signal
import sys
import time
from multiprocessing import Process, Queue, Event as MpEvent

from faker import Faker

# ──────────────────────────────────────────────────────────────────────────────
#  SHARED CONFIG  (read by both orchestrator and workers)
# ──────────────────────────────────────────────────────────────────────────────
SEL = {
    "name_field":    '[name="fullName"]',
    "email_field":   '[name="email"]',
    "join_button":   "button:has-text('Join')",
    "chat_toggle":   'button:has(svg path[d^="M6.4 5.6"])',
    "chat_input":    "textarea[placeholder='Send a message to everyone']",
    "chat_send":     'textarea[placeholder="Send a message to everyone"] + div.flex.items-center.gap-4 > svg',
    "chat_messages": "[data-testid='chat-message'], .chat-message, .message-item",
    "reaction_toggle": 'button[aria-label="Open reactions"]',
    "chat_close":     'button.absolute.right-4.top-4',
}

REACTION_SELECTORS = [
    'button[aria-label="Thumbs up"]',
    'button[aria-label="Thumbs down"]',
    'button[aria-label="Angry"]',
    'button[aria-label="Clap"]',
    'button[aria-label="Laugh"]',
    'button[aria-label="Smile"]',
]

REACTION_MIN_INTERVAL = 20  # seconds
REACTION_MAX_INTERVAL = 60  # seconds

PAGE_LOAD_TIMEOUT  = 90_000   # ms
CHAT_MIN_INTERVAL  = 45       # seconds  (spread out more at scale)
CHAT_MAX_INTERVAL  = 120      # seconds
CHAT_READ_INTERVAL = 20       # seconds  (only worker-1 bot-1 reads)

CHAT_MESSAGES = [
    "Hello everyone! 👋",
    "Great session so far!",
    "Can everyone hear me?",
    "Looking forward to this.",
    "Thanks for having me!",
    "This platform is really smooth.",
    "Just joined — excited to be here.",
    "Any questions from the audience?",
    "Really enjoying the content.",
    "Testing, testing… 1 2 3",
    "Love the interface on this platform.",
    "Great to connect with everyone.",
    "This is super helpful, thanks!",
    "Audio and video are crystal clear.",
]

# ──────────────────────────────────────────────────────────────────────────────
#  COLOURS  (safe to use in both main and worker processes)
# ──────────────────────────────────────────────────────────────────────────────
C = {
    "grn":   "\033[92m",
    "red":   "\033[91m",
    "cyn":   "\033[96m",
    "yel":   "\033[93m",
    "blu":   "\033[94m",
    "gry":   "\033[90m",
    "mag":   "\033[95m",
    "reset": "\033[0m",
}

def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def olog(worker_id: int, bot_id: int, name: str, icon: str, msg: str):
    """Worker-safe log — writes directly to stdout (no shared queue needed)."""
    if   "✅" in icon: col = C["grn"]
    elif "❌" in icon: col = C["red"]
    elif "💬" in icon: col = C["cyn"]
    elif "⚠️" in icon: col = C["yel"]
    elif "🚪" in icon: col = C["red"]
    elif "📦" in icon: col = C["blu"]
    else:              col = C["gry"]
    line = f"[{ts()}] {icon} W{worker_id:02d}/Bot-{bot_id:04d} ({name}) — {msg}"
    print(f"{col}{line}{C['reset']}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
#  IDENTITY GENERATOR  (each worker has its own Faker; no cross-process lock)
# ──────────────────────────────────────────────────────────────────────────────
def make_identity_generator(worker_id: int):
    """
    Returns a generator function unique to this worker.
    Worker ID is baked into the email to guarantee global uniqueness
    without needing shared memory.
    """
    faker  = Faker()
    used   = set()
    Faker.seed(worker_id * 99991)   # deterministic but different per worker

    def generate():
        for _ in range(500):
            first  = faker.first_name()
            last   = faker.last_name()
            suffix = random.randint(1000, 99999)
            name   = f"{first} {last} [Bot]"
            email  = f"{first.lower()}.{last.lower()}.w{worker_id}.{suffix}@botmail.test"
            if email not in used:
                used.add(email)
                return name, email
        uid = random.randint(10_000_000, 99_999_999)
        return f"Bot User {uid} [Bot]", f"bot.w{worker_id}.{uid}@botmail.test"

    return generate


# ──────────────────────────────────────────────────────────────────────────────
#  BOT COROUTINE  (runs inside a worker process event loop)
# ──────────────────────────────────────────────────────────────────────────────
async def run_bot(
    browser,
    worker_id:          int,
    bot_id:             int,       # global bot number
    local_id:           int,       # index within this worker (1-based)
    meeting_url:        str,
    auto_leave_seconds,
    chat_enabled:       bool,
    stop_ev:            asyncio.Event,
    generate_identity,
):
    name, email = generate_identity()

    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        # Grant mic/camera upfront — prevents the browser's native
        # permission popup whose backdrop overlay blocks the join form
        permissions=["microphone", "camera"],
        ignore_https_errors=True,
    )

    page = await context.new_page()

    # Block media files — saves bandwidth and GPU per context
    await page.route("**/*.{mp4,webm,ogg,mp3,wav}", lambda r: r.abort())

    try:
        olog(worker_id, bot_id, name, "🌐", "Navigating…")

        await page.goto(
            meeting_url,
            wait_until="domcontentloaded",
            timeout=PAGE_LOAD_TIMEOUT,
        )
        await asyncio.sleep(random.uniform(2, 4))

        # ── Dismiss any overlay blocking the form ─────────────────────────────
        # The mic/camera permission popup creates a backdrop (z-50 blur overlay)
        # that intercepts all pointer events on the join form behind it.
        # Granting permissions at context level stops the popup, but we also
        # force-hide any leftover overlay via JS just in case.
        await page.evaluate("""
            () => {
                document.querySelectorAll(
                    '[aria-hidden="true"][data-state="open"], .backdrop-blur-sm'
                ).forEach(el => el.remove());
            }
        """)
        await asyncio.sleep(0.5)

        # ── Name field ────────────────────────────────────────────────────────
        name_el = page.locator(SEL["name_field"])
        await name_el.wait_for(state="visible", timeout=PAGE_LOAD_TIMEOUT)
        await name_el.scroll_into_view_if_needed()
        await name_el.fill(name)
        await asyncio.sleep(0.3)

        # ── Email field ───────────────────────────────────────────────────────
        email_el = page.locator(SEL["email_field"])
        await email_el.wait_for(state="visible", timeout=PAGE_LOAD_TIMEOUT)
        await email_el.scroll_into_view_if_needed()
        await email_el.fill(email)
        await asyncio.sleep(0.5)

        # ── Join button ───────────────────────────────────────────────────────
        join_el = page.locator(SEL['join_button'])
        await join_el.wait_for(state="visible", timeout=PAGE_LOAD_TIMEOUT)
        await join_el.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
        
        if await join_el.is_disabled():
            raise Exception("Join button is disabled by the server (20+ participant limit reached on sandbox/trial license)")
            
        await join_el.click(force=True)

        olog(worker_id, bot_id, name, "🌐", "Join clicked — connecting...")

        # ── Wait for room or lobby state to resolve ───────────────────────────
        in_lobby = False
        lobby_logged = False
        connect_start = asyncio.get_event_loop().time()
        last_status_log = connect_start
        rxn_toggle = page.locator(SEL["reaction_toggle"])
        
        while not stop_ev.is_set():
            if await rxn_toggle.is_visible():
                if in_lobby:
                    olog(worker_id, bot_id, name, "✅", "Admitted to meeting room!")
                else:
                    olog(worker_id, bot_id, name, "✅", "Joined meeting room successfully")
                break
                
            body_text = (await page.inner_text("body")).lower()
            
            # Check for waiting/lobby room
            if any(kw in body_text for kw in ["waiting", "lobby", "please wait", "admit you", "moderator", "waiting room"]):
                if not lobby_logged:
                    olog(worker_id, bot_id, name, "⏳", "Stuck in virtual lobby (waiting for host to admit)")
                    lobby_logged = True
                in_lobby = True
            
            # Check for meeting full / license limit reached
            elif any(kw in body_text for kw in ["meeting is full", "meeting full", "room is full", "session expired", "session has expired"]):
                raise Exception("Failed to join: Meeting is full / License limit reached (30 participant ceiling)")
                
            # Check for invalid link
            elif any(kw in body_text for kw in ["invalid meeting", "link is invalid", "oops! invalid", "oops! meeting link"]):
                raise Exception("Failed to join: Invalid meeting link!")
            
            # Periodically print status if stuck in connecting/loading state
            now = asyncio.get_event_loop().time()
            if now - last_status_log > 15:
                if in_lobby:
                    olog(worker_id, bot_id, name, "⏳", "Still waiting in lobby...")
                else:
                    snippet = body_text[:60].replace('\n', ' ')
                    olog(worker_id, bot_id, name, "🔄", f"Still connecting... (Page snippet: '{snippet}')")
                last_status_log = now
                
            # Safety timeout (90 seconds max waiting to connect)
            if now - connect_start > 90:
                raise Exception("Connection timed out (90s limit reached)")
            
            await asyncio.sleep(2)

        await asyncio.sleep(3)   # let the room settle
        olog(worker_id, bot_id, name, "🏠", "Room ready")

        # ── Main loop ─────────────────────────────────────────────────────────
        loop_start       = asyncio.get_event_loop().time()
        leave_at         = loop_start + auto_leave_seconds if auto_leave_seconds else None
        next_chat_at     = loop_start + random.uniform(15, 40)
        next_reaction_at = loop_start + random.uniform(20, 45)
        next_read_at     = loop_start + CHAT_READ_INTERVAL

        while not stop_ev.is_set():
            now = asyncio.get_event_loop().time()

            if leave_at and now >= leave_at:
                olog(worker_id, bot_id, name, "🚪", "Auto-leave triggered")
                break

            if chat_enabled and now >= next_chat_at:
                await _send_chat(page, worker_id, bot_id, name)
                next_chat_at = now + random.uniform(CHAT_MIN_INTERVAL, CHAT_MAX_INTERVAL)

            # Send emoji reaction
            if chat_enabled and now >= next_reaction_at:
                await _send_reaction(page, worker_id, bot_id, name)
                next_reaction_at = now + random.uniform(REACTION_MIN_INTERVAL, REACTION_MAX_INTERVAL)

            # Only the very first bot in worker-1 reads chat
            if chat_enabled and worker_id == 1 and local_id == 1 and now >= next_read_at:
                await _read_chat(page, worker_id, bot_id, name)
                next_read_at = now + CHAT_READ_INTERVAL

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        olog(worker_id, bot_id, name, "🚪", "Cancelled")
    except Exception as exc:
        olog(worker_id, bot_id, name, "❌", f"{exc}")
        try:
            screenshot_path = f"scratch/error_worker_{worker_id:02d}_bot_{bot_id:04d}.png"
            await page.screenshot(path=screenshot_path)
            olog(worker_id, bot_id, name, "📸", f"Saved error screenshot to {screenshot_path}")
        except Exception as screenshot_exc:
            olog(worker_id, bot_id, name, "⚠️", f"Failed to take screenshot: {screenshot_exc}")
    finally:
        try:
            await page.close()
            await context.close()
        except Exception:
            pass
        olog(worker_id, bot_id, name, "🔒", "Context closed")


# ──────────────────────────────────────────────────────────────────────────────
#  CHAT HELPERS
# ──────────────────────────────────────────────────────────────────────────────
async def _send_chat(page, worker_id, bot_id, name):
    msg = random.choice(CHAT_MESSAGES)
    try:
        chatbox = page.locator(SEL["chat_input"])
        opened_by_me = False
        if not await chatbox.is_visible():
            toggle = page.locator(SEL["chat_toggle"])
            await toggle.wait_for(state="visible", timeout=10_000)
            await toggle.click(force=True)
            await chatbox.wait_for(state="visible", timeout=10_000)
            opened_by_me = True

        await chatbox.scroll_into_view_if_needed()
        await chatbox.fill(msg)
        await asyncio.sleep(0.3)
        
        send_btn = page.locator(SEL["chat_send"])
        await send_btn.click(force=True)
        olog(worker_id, bot_id, name, "💬", f'"{msg}"')

        # Close chat panel if we opened it, to keep the toolbar clear
        if opened_by_me:
            await asyncio.sleep(0.5)
            close_btn = page.locator(SEL["chat_close"])
            await close_btn.evaluate("node => node.click()")
            await chatbox.wait_for(state="hidden", timeout=10_000)
    except Exception as exc:
        olog(worker_id, bot_id, name, "⚠️", f"Chat send failed: {exc}")

async def _send_reaction(page, worker_id, bot_id, name):
    try:
        # If chat sidebar is open, close it first so it doesn't block the reactions button
        chatbox = page.locator(SEL["chat_input"])
        if await chatbox.is_visible():
            close_btn = page.locator(SEL["chat_close"])
            await close_btn.evaluate("node => node.click()")
            await chatbox.wait_for(state="hidden", timeout=10_000)

        rxn_toggle = page.locator(SEL["reaction_toggle"])
        await rxn_toggle.wait_for(state="visible", timeout=10_000)
        await rxn_toggle.click(force=True)
        await asyncio.sleep(0.3)
        
        emoji_sel = random.choice(REACTION_SELECTORS)
        emoji_btn = page.locator(emoji_sel)
        await emoji_btn.wait_for(state="visible", timeout=5_000)
        await emoji_btn.click(force=True)
        olog(worker_id, bot_id, name, "😀", f"Reacted: {emoji_sel.split('\"')[1]}")

        # Close reactions menu to prevent it from overlaying elements
        await asyncio.sleep(0.5)
        close_btn = page.locator('button[aria-label="Close reactions"]')
        if await close_btn.is_visible():
            await close_btn.evaluate("node => node.click()")
    except Exception as exc:
        olog(worker_id, bot_id, name, "⚠️", f"Reaction failed: {exc}")


async def _read_chat(page, worker_id, bot_id, name):
    try:
        elements = await page.query_selector_all(SEL["chat_messages"])
        if not elements:
            olog(worker_id, bot_id, name, "📭", "No chat messages (check selector)")
            return
        texts = [t for el in elements if (t := (await el.inner_text()).strip())]
        if texts:
            olog(worker_id, bot_id, name, "📨", f"{len(texts)} chat message(s):")
            for m in texts[-5:]:
                short = m[:120] + ("…" if len(m) > 120 else "")
                print(f"{C['cyn']}          📩  {short}{C['reset']}", flush=True)
    except Exception as exc:
        olog(worker_id, bot_id, name, "⚠️", f"Chat read failed: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
#  WORKER  (runs in its own OS process)
# ──────────────────────────────────────────────────────────────────────────────
def worker_main(
    worker_id:      int,
    bot_ids:        list,        # list of global bot IDs this worker owns
    meeting_url:    str,
    auto_leave_sec,
    chat_enabled:   bool,
    stagger_min:    float,
    stagger_max:    float,
    headless:       bool,
    shutdown_flag,               # multiprocessing.Event
):
    """Entry point for each worker process — runs its own asyncio event loop."""

    async def _run():
        from playwright.async_api import async_playwright

        stop_ev       = asyncio.Event()
        generate_id   = make_identity_generator(worker_id)
        active: list  = []

        # Mirror shutdown_flag into async stop_ev by polling
        async def _poll_shutdown():
            while not shutdown_flag.is_set():
                await asyncio.sleep(0.5)
            stop_ev.set()

        asyncio.create_task(_poll_shutdown())

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--mute-audio",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-notifications",
                    "--disable-popup-blocking",
                    "--disable-extensions",
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    # Extra flags for stability at high context counts
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--no-first-run",
                ],
            )

            print(
                f"{C['blu']}[{ts()}] 📦 Worker-{worker_id:02d} browser up "
                f"— {len(bot_ids)} bot(s){C['reset']}",
                flush=True,
            )

            # Stagger-launch contexts within this worker
            for local_idx, bot_id in enumerate(bot_ids, start=1):
                if stop_ev.is_set():
                    break

                task = asyncio.create_task(
                    run_bot(
                        browser=browser,
                        worker_id=worker_id,
                        bot_id=bot_id,
                        local_id=local_idx,
                        meeting_url=meeting_url,
                        auto_leave_seconds=auto_leave_sec,
                        chat_enabled=chat_enabled,
                        stop_ev=stop_ev,
                        generate_identity=generate_id,
                    )
                )
                active.append(task)

                if local_idx < len(bot_ids):
                    await asyncio.sleep(random.uniform(stagger_min, stagger_max))

            # Wait until stop signal or all bots naturally finish
            async def _wait_bots():
                await asyncio.gather(*active, return_exceptions=True)

            done_t = asyncio.create_task(_wait_bots())
            stop_t = asyncio.create_task(stop_ev.wait())
            await asyncio.wait([done_t, stop_t], return_when=asyncio.FIRST_COMPLETED)

            # Graceful shutdown
            for t in active:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            await browser.close()

    asyncio.run(_run())


# ──────────────────────────────────────────────────────────────────────────────
#  ORCHESTRATOR
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="py_guest_1k — Konn3ct 1000+ Bot Orchestrator"
    )
    parser.add_argument("--url",          required=True,           help="Meeting URL")
    parser.add_argument("--bots",         type=int,   default=1000, help="Total bots (default: 1000)")
    parser.add_argument("--workers",      type=int,   default=0,    help="Worker processes (default: auto)")
    parser.add_argument("--contexts",     type=int,   default=40,   help="Contexts per worker (default: 40, max: 50)")
    parser.add_argument("--leave",        type=int,   default=0,    help="Auto-leave after N minutes (default: 0 = manual)")
    parser.add_argument("--stagger-min",  type=float, default=1.0,  help="Min stagger between bots in a worker (default: 1)")
    parser.add_argument("--stagger-max",  type=float, default=3.0,  help="Max stagger between bots in a worker (default: 3)")
    parser.add_argument("--batch-pause",  type=float, default=15.0, help="Seconds between worker waves (default: 15)")
    parser.add_argument("--wave-size",    type=int,   default=2,    help="Number of workers to launch per wave (default: 2)")
    parser.add_argument("--no-chat",      action="store_true",      help="Disable chat simulation")
    parser.add_argument("--no-headless",  action="store_true",      help="Show browser windows")
    args = parser.parse_args()

    if not args.url.startswith("http"):
        print(f"{C['red']}❌  URL must start with http/https{C['reset']}")
        sys.exit(1)

    contexts_per_worker = min(args.contexts, 50)   # hard cap at 50
    total_bots          = args.bots
    num_workers         = args.workers or math.ceil(total_bots / contexts_per_worker)
    auto_leave_sec      = args.leave * 60 if args.leave > 0 else None
    headless            = not args.no_headless
    chat_enabled        = not args.no_chat
    batch_pause         = args.batch_pause

    # Distribute bot IDs across workers as evenly as possible
    all_bot_ids = list(range(1, total_bots + 1))
    worker_slices = []
    for i in range(num_workers):
        chunk = all_bot_ids[i::num_workers]
        if chunk:
            worker_slices.append(chunk)
    actual_workers = len(worker_slices)

    # ── Print plan ────────────────────────────────────────────────────────────
    print(f"\n{C['gry']}{'─'*68}")
    print(f"  🚀 py_guest_1k — Konn3ct Load Bot  [Process-Pool Mode]")
    print(f"{'─'*68}")
    print(f"  URL             : {args.url}")
    print(f"  Total bots      : {total_bots:,}")
    print(f"  Worker processes: {actual_workers}  ({contexts_per_worker} contexts each)")
    print(f"  Architecture    : {actual_workers} OS processes × 1 browser × {contexts_per_worker} contexts")
    print(f"  Stagger         : {args.stagger_min}–{args.stagger_max}s between bots per worker")
    print(f"  Worker wave     : {args.wave_size} workers per wave, {batch_pause}s pause between waves")
    print(f"  Auto-leave      : {'manual (Ctrl+C)' if not auto_leave_sec else f'{args.leave} min'}")
    print(f"  Chat            : {'ON' if chat_enabled else 'OFF'}")
    print(f"  Headless        : {'ON' if headless else 'OFF'}")
    est_ram_gb = actual_workers * contexts_per_worker * 25 / 1024
    print(f"  Est. RAM usage  : ~{est_ram_gb:.1f} GB")
    print(f"{'─'*68}\n{C['reset']}")

    # ── Shared shutdown event ─────────────────────────────────────────────────
    shutdown_flag = MpEvent()

    def _on_sigint(sig, frame):
        print(f"\n{C['yel']}🛑  Ctrl+C — stopping all workers...{C['reset']}", flush=True)
        shutdown_flag.set()

    signal.signal(signal.SIGINT,  _on_sigint)
    signal.signal(signal.SIGTERM, _on_sigint)

    # ── Launch workers in waves ─────────────────────────────────────────────
    # Launching all workers simultaneously would hammer the network/server.
    # Instead we start N workers, wait batch_pause, then N more, etc.
    WAVE_SIZE   = args.wave_size
    all_procs   = []

    for wave_start in range(0, actual_workers, WAVE_SIZE):
        if shutdown_flag.is_set():
            break

        wave_workers = worker_slices[wave_start: wave_start + WAVE_SIZE]
        wave_num     = wave_start // WAVE_SIZE + 1
        total_waves  = math.ceil(actual_workers / WAVE_SIZE)

        print(
            f"{C['blu']}[{ts()}] 🌊 Wave {wave_num}/{total_waves} — "
            f"starting Worker-{wave_start+1:02d} to "
            f"Worker-{wave_start+len(wave_workers):02d}{C['reset']}",
            flush=True,
        )

        for idx, bot_ids in enumerate(wave_workers):
            worker_id = wave_start + idx + 1
            p = Process(
                target=worker_main,
                args=(
                    worker_id,
                    bot_ids,
                    args.url,
                    auto_leave_sec,
                    chat_enabled,
                    args.stagger_min,
                    args.stagger_max,
                    headless,
                    shutdown_flag,
                ),
                daemon=True,
                name=f"BotWorker-{worker_id:02d}",
            )
            p.start()
            all_procs.append(p)

        # Pause between waves (skip after last wave)
        is_last_wave = (wave_start + WAVE_SIZE) >= actual_workers
        if not is_last_wave and not shutdown_flag.is_set():
            print(
                f"{C['gry']}[{ts()}] ⏳ Wave {wave_num} launched — "
                f"waiting {batch_pause:.0f}s before next wave...{C['reset']}",
                flush=True,
            )
            # Use interruptible sleep so Ctrl+C is responsive
            deadline = time.time() + batch_pause
            while time.time() < deadline and not shutdown_flag.is_set():
                time.sleep(0.5)

    print(
        f"{C['grn']}[{ts()}] ✔  All {actual_workers} worker(s) launched — "
        f"press Ctrl+C to stop{C['reset']}\n",
        flush=True,
    )

    # ── Wait for all workers or shutdown signal ────────────────────────────────
    try:
        while any(p.is_alive() for p in all_procs):
            if shutdown_flag.is_set():
                break
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_flag.set()

    # ── Final cleanup ─────────────────────────────────────────────────────────
    if shutdown_flag.is_set():
        print(f"{C['yel']}[{ts()}] Waiting for workers to clean up...{C['reset']}", flush=True)

    for p in all_procs:
        p.join(timeout=15)
        if p.is_alive():
            print(f"{C['yel']}[{ts()}] Force-killing {p.name}{C['reset']}", flush=True)
            p.terminate()
            p.join(timeout=5)

    alive = sum(1 for p in all_procs if p.is_alive())
    if alive:
        for p in all_procs:
            if p.is_alive():
                p.kill()

    print(f"{C['gry']}[{ts()}] ✔  All workers stopped. Goodbye!{C['reset']}", flush=True)


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()