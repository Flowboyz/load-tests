"""
py_guest_new.py — Lightweight Bot Joiner (Single Browser, Sequential Batches)

Designed to run 100+ bots on an 8-vCPU / 16GB RAM server.

Key differences from py_guest_1k.py:
    - ONE browser process (not 10-25 separate Chromium processes)
    - Bots join in small batches (5 at a time), waiting for each batch
      to fully connect before launching the next
    - After joining, each page is "lobotomized" — videos, animations,
      canvas elements, and media streams are killed to free CPU/RAM
    - No chat, no reactions — just join and stay
    - Aggressive resource blocking (images, fonts, media, analytics)

Usage:
    python py_guest_new.py --url "https://..." --bots 100
    python py_guest_new.py --url "https://..." --bots 50 --batch 3 --pause 20
    python py_guest_new.py --url "https://..." --bots 200 --leave 10

Dependencies:
    pip install faker playwright
    playwright install chromium
"""

import argparse
import asyncio
import random
import datetime
import signal
import sys
import os

from faker import Faker

# ──────────────────────────────────────────────────────────────────────────────
#  SELECTORS
# ──────────────────────────────────────────────────────────────────────────────
SEL = {
    "name_field":      '[name="fullName"]',
    "email_field":     '[name="email"]',
    "join_button":     "button:has-text('Join')",
    "reaction_toggle": 'button[aria-label="Open reactions"]',
}

PAGE_TIMEOUT = 120_000   # ms — generous for CPU-starved contexts

# ──────────────────────────────────────────────────────────────────────────────
#  COLOURS
# ──────────────────────────────────────────────────────────────────────────────
C = {
    "grn":   "\033[92m",
    "red":   "\033[91m",
    "cyn":   "\033[96m",
    "yel":   "\033[93m",
    "blu":   "\033[94m",
    "gry":   "\033[90m",
    "mag":   "\033[95m",
    "wht":   "\033[97m",
    "reset": "\033[0m",
}

def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def log(bot_id, icon, msg, colour="gry"):
    print(f"{C[colour]}[{ts()}] {icon} Bot-{bot_id:03d} — {msg}{C['reset']}", flush=True)

def syslog(icon, msg, colour="gry"):
    print(f"{C[colour]}[{ts()}] {icon} {msg}{C['reset']}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
#  IDENTITY GENERATOR
# ──────────────────────────────────────────────────────────────────────────────
faker_gen = Faker()
_used_emails = set()

REAL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"]

def generate_identity():
    for _ in range(500):
        first = faker_gen.first_name()
        last  = faker_gen.last_name()
        suffix = random.randint(10, 9999)
        domain = random.choice(REAL_DOMAINS)
        name  = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}{suffix}@{domain}"
        if email not in _used_emails:
            _used_emails.add(email)
            return name, email
    uid = random.randint(100_000, 999_999)
    return f"Guest {uid}", f"guest{uid}@gmail.com"


# ──────────────────────────────────────────────────────────────────────────────
#  LOBOTOMIZE JS — injected after joining to slash CPU/RAM usage
# ──────────────────────────────────────────────────────────────────────────────
LOBOTOMIZE_JS = """
() => {
    // 1. Stop and remove all <video> elements (biggest CPU saver)
    document.querySelectorAll('video').forEach(v => {
        v.pause();
        if (v.srcObject) {
            v.srcObject.getTracks().forEach(t => t.stop());
            v.srcObject = null;
        }
        v.src = '';
        v.load();
        v.remove();
    });

    // 2. Stop and remove all <audio> elements
    document.querySelectorAll('audio').forEach(a => {
        a.pause();
        if (a.srcObject) {
            a.srcObject.getTracks().forEach(t => t.stop());
            a.srcObject = null;
        }
        a.src = '';
        a.remove();
    });

    // 3. Remove all <canvas> elements
    document.querySelectorAll('canvas').forEach(c => c.remove());

    // 4. Kill CSS animations and transitions
    const killAnimStyle = document.createElement('style');
    killAnimStyle.textContent = `
        *, *::before, *::after {
            animation: none !important;
            animation-duration: 0s !important;
            transition: none !important;
            transition-duration: 0s !important;
        }
    `;
    document.head.appendChild(killAnimStyle);

    // 5. Override requestAnimationFrame to prevent rendering loops
    window.requestAnimationFrame = (cb) => setTimeout(cb, 30000);

    // 6. Kill observer-based layout thrashing
    window.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} };
    window.IntersectionObserver = class { observe(){} unobserve(){} disconnect(){} };
    window.MutationObserver = class { observe(){} disconnect(){} takeRecords(){ return []; } };

    // 7. Throttle setInterval to 30s minimum (kills polling loops)
    const origSetInterval = window.setInterval;
    window.setInterval = (fn, ms, ...args) => origSetInterval(fn, Math.max(ms, 30000), ...args);

    // 8. Remove heavy DOM nodes (participant video grid, etc.)
    document.querySelectorAll('[class*="video"], [class*="Video"], [class*="stream"], [class*="Stream"]').forEach(el => {
        el.innerHTML = '';
    });

    return 'lobotomized';
}
"""


# ──────────────────────────────────────────────────────────────────────────────
#  ANALYTICS / TRACKING DOMAINS TO BLOCK
# ──────────────────────────────────────────────────────────────────────────────
BLOCKED_DOMAINS = [
    "google-analytics.com", "googletagmanager.com", "mixpanel.com",
    "sentry.io", "hotjar.com", "segment.io", "segment.com",
    "intercom.io", "facebook.net", "doubleclick.net",
    "fullstory.com", "amplitude.com", "clarity.ms",
]


# ──────────────────────────────────────────────────────────────────────────────
#  BOT COROUTINE
# ──────────────────────────────────────────────────────────────────────────────
async def run_bot(browser, bot_id, meeting_url, stop_event, join_signal):
    """
    Opens a lightweight browser context, joins the meeting, then lobotomizes
    the page to minimize resource usage. Sets join_signal when done joining
    (success or failure) so the orchestrator knows when to launch the next batch.
    """
    name, email = generate_identity()
    context = None
    page = None
    joined = False

    try:
        # ── Create ultra-lightweight context ──────────────────────────────────
        context = await browser.new_context(
            viewport={"width": 640, "height": 480},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            permissions=["microphone", "camera"],
            ignore_https_errors=True,
        )

        page = await context.new_page()

        # ── Block heavy resources ─────────────────────────────────────────────
        async def block_heavy(route, request):
            rtype = request.resource_type
            url = request.url

            # Block images, fonts, media files entirely
            if rtype in ("image", "font", "media"):
                await route.abort()
                return

            # Block analytics/tracking scripts
            if any(d in url for d in BLOCKED_DOMAINS):
                await route.abort()
                return

            # Block media file extensions
            if any(url.endswith(ext) for ext in (".mp4", ".webm", ".ogg", ".mp3", ".wav", ".png", ".jpg", ".gif", ".svg", ".woff", ".woff2", ".ttf")):
                await route.abort()
                return

            await route.continue_()

        await page.route("**/*", block_heavy)

        # ── Navigate to meeting ───────────────────────────────────────────────
        log(bot_id, "🌐", f"Navigating… ({name})", "gry")

        await page.goto(
            meeting_url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )
        await asyncio.sleep(random.uniform(3, 5))

        # ── Dismiss overlays ──────────────────────────────────────────────────
        await page.evaluate("""
            () => {
                document.querySelectorAll(
                    '[aria-hidden="true"][data-state="open"], .backdrop-blur-sm'
                ).forEach(el => el.remove());
            }
        """)
        await asyncio.sleep(0.5)

        # ── Fill name ─────────────────────────────────────────────────────────
        name_el = page.locator(SEL["name_field"])
        await name_el.wait_for(state="visible", timeout=PAGE_TIMEOUT)
        await name_el.click()
        await name_el.fill(name)
        await asyncio.sleep(0.5)

        # Verify name was filled correctly
        actual_name = await name_el.input_value()
        if actual_name != name:
            log(bot_id, "⚠️", f"Name mismatch, retrying (got '{actual_name}')", "yel")
            await name_el.click()
            await name_el.press("Control+a")
            await name_el.type(name, delay=30)
            await asyncio.sleep(0.3)

        # ── Fill email ────────────────────────────────────────────────────────
        email_el = page.locator(SEL["email_field"])
        await email_el.wait_for(state="visible", timeout=PAGE_TIMEOUT)
        await email_el.click()
        await email_el.fill(email)
        await asyncio.sleep(0.5)

        # Verify email
        actual_email = await email_el.input_value()
        if actual_email != email:
            log(bot_id, "⚠️", f"Email mismatch, retrying", "yel")
            await email_el.click()
            await email_el.press("Control+a")
            await email_el.type(email, delay=30)
            await asyncio.sleep(0.3)

        # ── Click join ────────────────────────────────────────────────────────
        join_el = page.locator(SEL["join_button"])
        await join_el.wait_for(state="visible", timeout=PAGE_TIMEOUT)
        await asyncio.sleep(0.5)
        await join_el.click(force=True)

        log(bot_id, "🌐", "Join clicked — waiting for room…", "gry")

        # ── Wait for meeting room ─────────────────────────────────────────────
        rxn_toggle = page.locator(SEL["reaction_toggle"])
        connect_start = asyncio.get_event_loop().time()

        while not stop_event.is_set():
            try:
                if await rxn_toggle.is_visible():
                    log(bot_id, "✅", f"JOINED — {name} ({email})", "grn")
                    joined = True
                    break
            except Exception:
                pass

            now = asyncio.get_event_loop().time()
            elapsed = now - connect_start

            # Check for error states
            try:
                body_text = (await page.inner_text("body")).lower()

                if any(kw in body_text for kw in ["session expired", "session has expired"]):
                    raise Exception("Session expired (page too slow)")

                if any(kw in body_text for kw in ["meeting is full", "meeting full", "room is full"]):
                    raise Exception("Meeting room is full")

                if any(kw in body_text for kw in ["invalid meeting", "link is invalid", "oops"]):
                    raise Exception("Invalid meeting link")
            except Exception as check_exc:
                if "Session expired" in str(check_exc) or "full" in str(check_exc) or "Invalid" in str(check_exc):
                    raise check_exc
                # inner_text can fail under load — ignore

            if elapsed > 180:
                raise Exception("Connection timed out (180s)")

            if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                log(bot_id, "🔄", f"Still connecting… ({int(elapsed)}s)", "yel")

            await asyncio.sleep(3)

        # ── Signal that joining is complete ────────────────────────────────────
        join_signal.set()

        if not joined:
            return

        # ── Lobotomize the page to save CPU/RAM ───────────────────────────────
        await asyncio.sleep(3)
        try:
            result = await page.evaluate(LOBOTOMIZE_JS)
            log(bot_id, "💤", "Page lobotomized (videos/animations killed)", "gry")
        except Exception:
            pass

        # ── Stay in the meeting until stop signal ─────────────────────────────
        while not stop_event.is_set():
            await asyncio.sleep(10)

    except asyncio.CancelledError:
        log(bot_id, "🚪", "Cancelled", "yel")
    except Exception as exc:
        log(bot_id, "❌", str(exc), "red")
    finally:
        # Always signal so the orchestrator doesn't hang
        if not join_signal.is_set():
            join_signal.set()

        # Cleanup
        try:
            if page:
                await page.close()
        except Exception:
            pass
        try:
            if context:
                await context.close()
        except Exception:
            pass

        if joined:
            log(bot_id, "🔒", "Context closed", "gry")


# ──────────────────────────────────────────────────────────────────────────────
#  ORCHESTRATOR
# ──────────────────────────────────────────────────────────────────────────────
async def main_async(args):
    from playwright.async_api import async_playwright

    stop_event = asyncio.Event()

    # Handle Ctrl+C
    loop = asyncio.get_event_loop()
    def _on_signal(sig, frame):
        print(f"\n{C['yel']}🛑  Ctrl+C — stopping all bots…{C['reset']}", flush=True)
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    meeting_url = args.url

    # URL rewrite for sandbox proxy
    if "konnectsandbox.convergenceondemand.com/conferencing/join/" in meeting_url:
        meeting_url = meeting_url.replace(
            "konnectsandbox.convergenceondemand.com/conferencing/join/",
            "meetingapp.convergenceondemand.com/join/"
        )

    auto_leave_sec = args.leave * 60 if args.leave > 0 else None

    # ── Print plan ────────────────────────────────────────────────────────────
    print(f"\n{C['wht']}{'═'*60}")
    print(f"  🚀 py_guest_new — Lightweight Bot Joiner")
    print(f"{'═'*60}{C['reset']}")
    print(f"  URL         : {meeting_url}")
    print(f"  Bots        : {args.bots}")
    print(f"  Batch size  : {args.batch} bots at a time")
    print(f"  Batch pause : {args.pause}s between batches")
    print(f"  Stagger     : {args.stagger}s between bots in a batch")
    print(f"  Auto-leave  : {'manual (Ctrl+C)' if not auto_leave_sec else f'{args.leave} min'}")
    print(f"  Architecture: 1 browser → {args.bots} contexts (sequential batches)")
    est_ram = args.bots * 50 / 1024
    print(f"  Est. RAM    : ~{est_ram:.1f} GB")
    print(f"{C['wht']}{'═'*60}\n{C['reset']}")

    # ── Create scratch dir for error screenshots ──────────────────────────────
    os.makedirs("scratch", exist_ok=True)

    async with async_playwright() as pw:
        # ── Launch ONE browser ────────────────────────────────────────────────
        browser = await pw.chromium.launch(
            headless=True,
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
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--no-first-run",
                # Memory reduction
                "--disable-software-rasterizer",
                "--disable-canvas-aa",
                "--disable-2d-canvas-clip-aa",
                "--disable-gl-drawing-for-tests",
                "--disable-features=TranslateUI,WebRtcHideLocalIpsWithMdns",
                "--disable-ipc-flooding-protection",
                "--js-flags=--max-old-space-size=128",
                # Reduce WebRTC overhead
                "--disable-webrtc-hw-encoding",
                "--disable-webrtc-hw-decoding",
                "--force-fieldtrials=WebRTC-CpuOveruseDetection/Disabled/",
            ],
        )

        syslog("📦", "Browser launched — single process mode", "blu")

        all_tasks = []
        joined_count = 0
        failed_count = 0
        total_batches = (args.bots + args.batch - 1) // args.batch

        # ── Launch bots in batches ────────────────────────────────────────────
        for batch_num in range(total_batches):
            if stop_event.is_set():
                break

            batch_start = batch_num * args.batch + 1
            batch_end   = min(batch_start + args.batch - 1, args.bots)
            batch_size  = batch_end - batch_start + 1

            syslog("📦", f"Batch {batch_num+1}/{total_batches} — "
                   f"Bot-{batch_start:03d} to Bot-{batch_end:03d} "
                   f"({batch_size} bots)", "blu")

            batch_signals = []

            for bot_id in range(batch_start, batch_end + 1):
                if stop_event.is_set():
                    break

                join_signal = asyncio.Event()
                batch_signals.append(join_signal)

                task = asyncio.create_task(
                    run_bot(browser, bot_id, meeting_url, stop_event, join_signal)
                )
                all_tasks.append(task)

                # Stagger between bots within the batch
                if bot_id < batch_end:
                    await asyncio.sleep(args.stagger)

            # ── Wait for this batch to finish joining ─────────────────────────
            # Give them generous time (up to 120s) to connect
            if batch_signals and not stop_event.is_set():
                syslog("⏳", f"Waiting for batch {batch_num+1} to connect…", "gry")
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*[s.wait() for s in batch_signals]),
                        timeout=120.0
                    )
                except asyncio.TimeoutError:
                    syslog("⚠️", f"Batch {batch_num+1} timed out — some bots may not have joined", "yel")

            # Count results so far
            done_count = sum(1 for s in batch_signals if s.is_set())
            syslog("📊", f"Batch {batch_num+1} done — "
                   f"{done_count}/{batch_size} responded", "gry")

            # ── Pause between batches ─────────────────────────────────────────
            is_last = (batch_num + 1) >= total_batches
            if not is_last and not stop_event.is_set():
                syslog("⏳", f"Pausing {args.pause}s before next batch…", "gry")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=args.pause)
                except asyncio.TimeoutError:
                    pass  # Normal — pause completed

        # ── All launched ──────────────────────────────────────────────────────
        syslog("✔", f"All {args.bots} bot(s) launched — press Ctrl+C to stop", "grn")

        # ── Auto-leave timer ──────────────────────────────────────────────────
        if auto_leave_sec:
            syslog("⏱", f"Auto-leave in {args.leave} minutes", "gry")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=auto_leave_sec)
            except asyncio.TimeoutError:
                syslog("🚪", "Auto-leave time reached", "yel")
                stop_event.set()
        else:
            await stop_event.wait()

        # ── Graceful shutdown ─────────────────────────────────────────────────
        syslog("🛑", "Shutting down all bots…", "yel")
        stop_event.set()

        for task in all_tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*all_tasks, return_exceptions=True)
        await browser.close()

    syslog("✔", "All bots stopped. Goodbye!", "gry")


# ──────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="py_guest_new — Lightweight Konn3ct Bot Joiner"
    )
    parser.add_argument("--url",      required=True,            help="Meeting URL")
    parser.add_argument("--bots",     type=int,   default=100,  help="Total bots (default: 100)")
    parser.add_argument("--batch",    type=int,   default=5,    help="Bots per batch (default: 5)")
    parser.add_argument("--stagger",  type=float, default=4.0,  help="Seconds between bots in a batch (default: 4)")
    parser.add_argument("--pause",    type=float, default=30.0, help="Seconds between batches (default: 30)")
    parser.add_argument("--leave",    type=int,   default=0,    help="Auto-leave after N minutes (default: 0 = manual)")
    args = parser.parse_args()

    if not args.url.startswith("http"):
        print(f"{C['red']}❌  URL must start with http/https{C['reset']}")
        sys.exit(1)

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print(f"\n{C['yel']}🛑  Interrupted — goodbye!{C['reset']}")


if __name__ == "__main__":
    main()
