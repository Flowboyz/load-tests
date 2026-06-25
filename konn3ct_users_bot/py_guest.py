"""
py_guest.py — Konn3ct Load Testing Bot (Playwright / Single-Browser Mode)
Simulates multiple attendees joining a Konn3ct meeting for platform stress testing.
Uses ONE browser process with isolated contexts per bot — massively lower RAM/CPU.

Dependencies:
    pip install faker playwright
    playwright install chromium

Usage:
    python py_guest.py --url "https://app.konn3ct.com/meeting/..." --bots 10
    python py_guest.py --url "https://..." --bots 50 --leave 5 --no-chat
    python py_guest.py --url "https://..." --bots 20 --stagger-min 1 --stagger-max 4

Arguments:
    --url           Meeting URL (required)
    --bots          Number of bots to launch (default: 10)
    --leave         Auto-leave after N minutes, 0 = stay until Ctrl+C (default: 0)
    --stagger-min   Minimum seconds between each bot joining (default: 1)
    --stagger-max   Maximum seconds between each bot joining (default: 4)
    --no-chat       Disable chat simulation (default: chat is ON)
    --no-headless   Show browser window (default: headless ON)
"""

import argparse
import asyncio
import random
import datetime
import signal
import sys

from faker import Faker

# ──────────────────────────────────────────────────────────────────────────────
#  SELECTORS  (exact selectors from original code — unchanged)
# ──────────────────────────────────────────────────────────────────────────────
SEL = {
    "name_field":    '[name="fullName"]',
    "email_field":   '[name="email"]',
    "join_button":   "//button[text()='Join Now']",          # XPath
    "chat_toggle":   'div:has(button[aria-label*="reactions"]) + button',
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

PAGE_LOAD_TIMEOUT  = 90_000   # ms — raised from 40s; slow networks need headroom
CHAT_MIN_INTERVAL  = 30       # seconds
CHAT_MAX_INTERVAL  = 90       # seconds
CHAT_READ_INTERVAL = 15       # seconds

# Batch settings — controls how many bots launch concurrently.
# Launching too many at once saturates the network and causes goto timeouts.
# Default: batches of 20, with a 10s pause between batches so earlier
# bots finish their page load before the next wave hits the server.
BATCH_SIZE         = 20       # max bots launching at the same time
BATCH_PAUSE        = 10       # seconds to wait between batches

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
#  SHARED STATE
# ──────────────────────────────────────────────────────────────────────────────
faker_gen           = Faker()
stop_event          = asyncio.Event()
active_tasks: list  = []

_used_identities: set = set()
_identity_lock        = asyncio.Lock()

# ──────────────────────────────────────────────────────────────────────────────
#  COLOURS
# ──────────────────────────────────────────────────────────────────────────────
COLOURS = {
    "join":  "\033[92m",
    "leave": "\033[91m",
    "chat":  "\033[96m",
    "warn":  "\033[93m",
    "err":   "\033[91m",
    "info":  "\033[90m",
    "reset": "\033[0m",
}

def log_print(msg: str):
    if   "✅" in msg:                    c = COLOURS["join"]
    elif "🚪" in msg or "closed" in msg: c = COLOURS["leave"]
    elif "💬" in msg or "📩" in msg:     c = COLOURS["chat"]
    elif "❌" in msg:                    c = COLOURS["err"]
    elif "⚠️" in msg:                    c = COLOURS["warn"]
    else:                                c = COLOURS["info"]
    print(f"{c}{msg}{COLOURS['reset']}", flush=True)

def log(bot_id: int, name: str, email: str, icon: str, message: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    log_print(f"[{ts}] {icon} Bot-{bot_id:03d} ({name} / {email}) — {message}")


# ──────────────────────────────────────────────────────────────────────────────
#  IDENTITY GENERATOR  (async-safe lock)
# ──────────────────────────────────────────────────────────────────────────────
async def generate_identity():
    async with _identity_lock:
        for _ in range(200):
            first  = faker_gen.first_name()
            last   = faker_gen.last_name()
            suffix = random.randint(100, 9999)
            name   = f"{first} {last} [Bot]"
            email  = f"{first.lower()}.{last.lower()}{suffix}@botmail.test"
            if email not in _used_identities:
                _used_identities.add(email)
                return name, email
        uid = random.randint(1_000_000, 9_999_999)
        return f"Bot User {uid} [Bot]", f"bot{uid}@botmail.test"


# ──────────────────────────────────────────────────────────────────────────────
#  CHAT HELPERS
# ──────────────────────────────────────────────────────────────────────────────
async def _send_chat(page, bot_id, name, email):
    message = random.choice(CHAT_MESSAGES)
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
        await chatbox.click(force=True)
        await asyncio.sleep(0.3)
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Delete")
        await asyncio.sleep(0.2)
        await chatbox.type(message, delay=random.uniform(30, 80))
        await asyncio.sleep(0.3)
        
        send_btn = page.locator(SEL["chat_send"])
        await send_btn.click(force=True)
        log(bot_id, name, email, "💬", f'Sent: "{message}"')

        # Close chat panel if we opened it, to keep the toolbar clear
        if opened_by_me:
            await asyncio.sleep(0.5)
            close_btn = page.locator(SEL["chat_close"])
            await close_btn.evaluate("node => node.click()")
            await chatbox.wait_for(state="hidden", timeout=10_000)
    except Exception as exc:
        log(bot_id, name, email, "⚠️", f"Chat send failed: {exc}")

async def _send_reaction(page, bot_id, name, email):
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
        log(bot_id, name, email, "😀", f"Reacted: {emoji_sel.split('\"')[1]}")

        # Close reactions menu to prevent it from overlaying elements
        await asyncio.sleep(0.5)
        close_btn = page.locator('button[aria-label="Close reactions"]')
        if await close_btn.is_visible():
            await close_btn.evaluate("node => node.click()")
    except Exception as exc:
        log(bot_id, name, email, "⚠️", f"Reaction failed: {exc}")


async def _read_chat(page, bot_id, name, email):
    """Bot-001 only: snapshot visible chat messages and print last 5."""
    try:
        elements = await page.query_selector_all(SEL["chat_messages"])
        if not elements:
            log(bot_id, name, email, "📭", "Chat reader: no messages found (check selector)")
            return

        texts = []
        for el in elements:
            t = (await el.inner_text()).strip()
            if t:
                texts.append(t)

        if texts:
            log(bot_id, name, email, "📨", f"Chat snapshot ({len(texts)} msg(s) visible):")
            for m in texts[-5:]:
                short = m[:120] + ("…" if len(m) > 120 else "")
                log_print(f"          📩  {short}")
    except Exception as exc:
        log(bot_id, name, email, "⚠️", f"Chat read failed: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
#  BOT COROUTINE — one per context, all share the same single browser process
# ──────────────────────────────────────────────────────────────────────────────
async def run_bot(browser, bot_id, meeting_url, auto_leave_seconds, chat_enabled):
    name, email = await generate_identity()

    # ── Create an isolated browser context (own cookies, storage, session) ────
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        # Grant microphone permission upfront so the browser never shows the
        # native permission popup — that popup's backdrop overlay blocks all
        # clicks on the join form behind it
        permissions=["microphone", "camera"],
        ignore_https_errors=True,
    )

    # Open the page for this bot context
    page = await context.new_page()

    # Block heavy media to save bandwidth and CPU per context
    await page.route(
        "**/*.{mp4,webm,ogg,mp3,wav}",
        lambda route: route.abort()
    )

    try:
        log(bot_id, name, email, "🌐", "Context created — navigating to meeting")

        # ── Navigate ──────────────────────────────────────────────────────────
        await page.goto(meeting_url, wait_until="domcontentloaded",
                        timeout=PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(3)

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

        # ── Fill name field ───────────────────────────────────────────────────
        # Use page.locator() — returns a Locator which supports triple_click()
        # wait_for_selector() returns ElementHandle which does NOT have triple_click
        name_input = page.locator(SEL["name_field"])
        await name_input.wait_for(state="visible", timeout=PAGE_LOAD_TIMEOUT)
        await name_input.scroll_into_view_if_needed()
        await name_input.click(click_count=3, force=True)    # select all — works on all Playwright versions
        await name_input.type(name, delay=random.uniform(50, 120))

        await asyncio.sleep(0.3)

        # ── Fill email field ──────────────────────────────────────────────────
        email_input = page.locator(SEL["email_field"])
        await email_input.wait_for(state="visible", timeout=PAGE_LOAD_TIMEOUT)
        await email_input.scroll_into_view_if_needed()
        await email_input.click(click_count=3, force=True)   # select all — works on all Playwright versions
        await email_input.type(email, delay=random.uniform(50, 120))

        await asyncio.sleep(0.5)

        # ── Click join button (XPath) ─────────────────────────────────────────
        join_btn = page.locator(f"xpath={SEL['join_button']}")
        await join_btn.wait_for(state="visible", timeout=PAGE_LOAD_TIMEOUT)
        await join_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
        await join_btn.click(force=True)

        log(bot_id, name, email, "🌐", "Join clicked — connecting...")

        # ── Wait for room or lobby state to resolve ───────────────────────────
        in_lobby = False
        lobby_logged = False
        connect_start = asyncio.get_event_loop().time()
        last_status_log = connect_start
        rxn_toggle = page.locator(SEL["reaction_toggle"])
        
        while not stop_event.is_set():
            if await rxn_toggle.is_visible():
                if in_lobby:
                    log(bot_id, name, email, "✅", "Admitted to meeting room!")
                else:
                    log(bot_id, name, email, "✅", "Joined meeting room successfully")
                break
                
            body_text = (await page.inner_text("body")).lower()
            
            # Check for waiting/lobby room
            if any(kw in body_text for kw in ["waiting", "lobby", "please wait", "admit you", "moderator", "waiting room"]):
                if not lobby_logged:
                    log(bot_id, name, email, "⏳", "Stuck in virtual lobby (waiting for host to admit)")
                    lobby_logged = True
                in_lobby = True
            
            # Check for meeting full
            elif any(kw in body_text for kw in ["meeting is full", "meeting full", "room is full"]):
                log(bot_id, name, email, "❌", "Failed to join: Meeting room is full!")
                break
                
            # Check for invalid link
            elif any(kw in body_text for kw in ["invalid meeting", "link is invalid", "oops!"]):
                log(bot_id, name, email, "❌", "Failed to join: Invalid meeting link!")
                break
            
            # Periodically print status if stuck in connecting/loading state
            now = asyncio.get_event_loop().time()
            if now - last_status_log > 15:
                if in_lobby:
                    log(bot_id, name, email, "⏳", "Still waiting in lobby...")
                else:
                    snippet = body_text[:60].replace('\n', ' ')
                    log(bot_id, name, email, "🔄", f"Still connecting... (Page snippet: '{snippet}')")
                last_status_log = now
                
            # Safety timeout (90 seconds max waiting to connect)
            if now - connect_start > 90:
                log(bot_id, name, email, "❌", "Connection timed out (90s limit reached)")
                break
            
            await asyncio.sleep(2)

        # Wait for meeting room to settle
        await asyncio.sleep(3)
        log(bot_id, name, email, "🏠", "Meeting room ready")

        # ── Main bot loop ─────────────────────────────────────────────────────
        # Set leave_at HERE (after room settles) not at join-click time.
        # If set earlier, slow page loads eat into the timer and produce a
        # negative timeout — causing the bot to leave the instant it joins.
        loop_start       = asyncio.get_event_loop().time()
        leave_at         = loop_start + auto_leave_seconds if auto_leave_seconds else None
        next_chat_at     = loop_start + random.uniform(10, 20)
        next_reaction_at = loop_start + random.uniform(15, 30)
        next_read_at     = loop_start + CHAT_READ_INTERVAL

        while not stop_event.is_set():
            now = asyncio.get_event_loop().time()

            # Auto-leave check
            if leave_at and now >= leave_at:
                log(bot_id, name, email, "🚪", "Auto-leaving (time limit reached)")
                break

            # Send chat message
            if chat_enabled and now >= next_chat_at:
                await _send_chat(page, bot_id, name, email)
                next_chat_at = now + random.uniform(CHAT_MIN_INTERVAL, CHAT_MAX_INTERVAL)

            # Send emoji reaction
            if chat_enabled and now >= next_reaction_at:
                await _send_reaction(page, bot_id, name, email)
                next_reaction_at = now + random.uniform(REACTION_MIN_INTERVAL, REACTION_MAX_INTERVAL)

            # Read chat — only Bot-001 does this
            if bot_id == 1 and now >= next_read_at:
                await _read_chat(page, bot_id, name, email)
                next_read_at = now + CHAT_READ_INTERVAL

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        log(bot_id, name, email, "🚪", "Task cancelled — shutting down")
    except Exception as exc:
        log(bot_id, name, email, "❌", f"Error: {exc}")
    finally:
        try:
            await page.close()
            await context.close()
        except Exception:
            pass
        log(bot_id, name, email, "🔒", "Context closed")


# ──────────────────────────────────────────────────────────────────────────────
#  MAIN — launch one browser, then N async context tasks with stagger
# ──────────────────────────────────────────────────────────────────────────────
async def main_async(args):
    from playwright.async_api import async_playwright

    headless     = not args.no_headless
    chat_enabled = not args.no_chat
    auto_leave   = args.leave * 60 if args.leave > 0 else None
    smin         = args.stagger_min
    smax         = args.stagger_max

    print(f"\n{COLOURS['info']}{'─'*65}")
    print(f"  🚀 py_guest — Konn3ct Load Testing Bot  [Playwright Mode]")
    print(f"{'─'*65}")
    print(f"  URL        : {args.url}")
    print(f"  Bots       : {args.bots}")
    print(f"  Engine     : ONE browser process + {args.bots} isolated contexts")
    print(f"  Stagger    : {smin}–{smax}s between each bot")
    print(f"  Auto-leave : {'manual (Ctrl+C to stop)' if not auto_leave else f'{args.leave} min'}")
    print(f"  Chat       : {'ON' if chat_enabled else 'OFF'}")
    print(f"  Headless   : {'ON' if headless else 'OFF'}")
    print(f"  Identities : faker name [Bot] + @botmail.test email")
    print(f"{'─'*65}\n{COLOURS['reset']}")

    async with async_playwright() as pw:

        # ── Launch ONE shared Chromium browser ────────────────────────────────
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
            ],
        )

        total_batches = (args.bots + BATCH_SIZE - 1) // BATCH_SIZE
        log_print(
            f"{COLOURS['info']}  🟢 Single browser launched — "
            f"{args.bots} bot(s) in {total_batches} batch(es) of {BATCH_SIZE}{COLOURS['reset']}"
        )

        # ── Batch-stagger launch ──────────────────────────────────────────────
        # Bots launch in groups of BATCH_SIZE. Within each batch there is still
        # a per-bot stagger (smin–smax). Between batches we pause BATCH_PAUSE
        # seconds so the previous wave finishes loading before the next starts.
        bot_counter = 1
        for batch_num in range(1, total_batches + 1):
            if stop_event.is_set():
                break

            batch_start = bot_counter
            batch_end   = min(bot_counter + BATCH_SIZE - 1, args.bots)
            log_print(
                f"{COLOURS['info']}  📦 Batch {batch_num}/{total_batches} — "
                f"launching Bot-{batch_start:03d} to Bot-{batch_end:03d}{COLOURS['reset']}"
            )

            for i in range(batch_start, batch_end + 1):
                if stop_event.is_set():
                    break

                task = asyncio.create_task(
                    run_bot(
                        browser=browser,
                        bot_id=i,
                        meeting_url=args.url,
                        auto_leave_seconds=auto_leave,
                        chat_enabled=chat_enabled,
                    )
                )
                active_tasks.append(task)

                # Per-bot stagger within the batch
                if i < batch_end:
                    await asyncio.sleep(random.uniform(smin, smax))

            bot_counter = batch_end + 1

            # Pause between batches so network isn't hammered
            if batch_num < total_batches and not stop_event.is_set():
                log_print(
                    f"{COLOURS['info']}  ⏳ Batch {batch_num} launched — "
                    f"waiting {BATCH_PAUSE}s before next batch...{COLOURS['reset']}"
                )
                await asyncio.sleep(BATCH_PAUSE)

        log_print(
            f"{COLOURS['info']}  ✔  All {args.bots} bot(s) launched — "
            f"press Ctrl+C to stop{COLOURS['reset']}\n"
        )

        # ── Block until Ctrl+C or all bots naturally finish ───────────────────
        # asyncio.gather() returns a Future, not a coroutine — wrap in a plain
        # async def so create_task gets an actual coroutine to schedule
        async def _wait_all():
            await asyncio.gather(*active_tasks, return_exceptions=True)

        done_watcher = asyncio.create_task(_wait_all())
        stop_watcher = asyncio.create_task(stop_event.wait())

        await asyncio.wait(
            [done_watcher, stop_watcher],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel whichever watcher is still pending
        for w in [done_watcher, stop_watcher]:
            if not w.done():
                w.cancel()

        # ── Graceful shutdown ─────────────────────────────────────────────────
        log_print(f"{COLOURS['warn']}  Shutting down all bot contexts...{COLOURS['reset']}")

        # Cancel all bot tasks first
        for task in active_tasks:
            if not task.done():
                task.cancel()

        # Wait for every bot to fully clean up its context before closing browser
        # This prevents TargetClosedError from the browser disappearing mid-cleanup
        await asyncio.gather(*active_tasks, return_exceptions=True)

        # Now safe to close the shared browser
        await browser.close()

    log_print(f"{COLOURS['info']}  ✔  All bots stopped. Goodbye!{COLOURS['reset']}")


# ──────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="py_guest — Konn3ct Load Testing Bot (Playwright)"
    )
    parser.add_argument("--url",         required=True,          help="Meeting URL")
    parser.add_argument("--bots",        type=int,   default=10,  help="Number of bots (default: 10)")
    parser.add_argument("--leave",       type=int,   default=0,   help="Auto-leave after N minutes, 0 = manual")
    parser.add_argument("--stagger-min", type=float, default=1.0, help="Min stagger delay in seconds (default: 1)")
    parser.add_argument("--stagger-max", type=float, default=4.0, help="Max stagger delay in seconds (default: 4)")
    parser.add_argument("--no-chat",     action="store_true",     help="Disable chat simulation")
    parser.add_argument("--no-headless", action="store_true",     help="Show browser window")
    args = parser.parse_args()

    if not args.url.startswith("http"):
        print(f"{COLOURS['err']}❌  Invalid URL — must start with http/https{COLOURS['reset']}")
        sys.exit(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Wire Ctrl+C into the async stop_event
    def _on_signal(sig, frame):
        print(
            f"\n{COLOURS['warn']}🛑  Ctrl+C detected — stopping all bots...{COLOURS['reset']}",
            flush=True
        )
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        loop.run_until_complete(main_async(args))
    finally:
        loop.close()


if __name__ == "__main__":
    main()