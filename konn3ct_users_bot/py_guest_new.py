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

# Fix Windows console encoding for Unicode characters (emoji, box-drawing, etc.)
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

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

    // 6. Kill ONLY visual observers (ResizeObserver, IntersectionObserver)
    // ⚠️ DO NOT kill MutationObserver — the meeting app may use it for
    //    WebSocket state management and connection keepalive
    window.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} };
    window.IntersectionObserver = class { observe(){} unobserve(){} disconnect(){} };

    // ⚠️ DO NOT throttle setInterval or setTimeout — the meeting app uses
    //    these for WebSocket ping/pong heartbeats. Throttling them will cause
    //    the server to think the client disconnected and kick them out.

    // 7. Remove heavy DOM nodes (participant video grid tiles)
    //    but keep the container alive so the app doesn't crash
    document.querySelectorAll('[class*="video"], [class*="Video"], [class*="stream"], [class*="Stream"]').forEach(el => {
        // Only clear children, don't remove the element itself
        while (el.firstChild) el.removeChild(el.firstChild);
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

        # ── Dismiss ALL overlays aggressively ─────────────────────────────────
        # The Konn3ct app shows a Radix UI alertdialog for camera/mic permissions
        # that blocks ALL pointer events on the form behind it. We need to
        # remove this dialog AND its backdrop overlay.
        DISMISS_OVERLAYS_JS = """
            () => {
                let removed = 0;

                // 1. Remove Radix alert dialogs (camera/mic permission popup)
                document.querySelectorAll('[role="alertdialog"]').forEach(el => {
                    el.remove();
                    removed++;
                });

                // 2. Remove Radix regular dialogs
                document.querySelectorAll('[role="dialog"][data-state="open"]').forEach(el => {
                    el.remove();
                    removed++;
                });

                // 3. Remove any data-state="open" overlays with z-50 positioning
                document.querySelectorAll('[data-state="open"].fixed').forEach(el => {
                    el.remove();
                    removed++;
                });

                // 4. Remove backdrop blur overlays
                document.querySelectorAll('.backdrop-blur-sm, .backdrop-blur').forEach(el => {
                    el.remove();
                    removed++;
                });

                // 5. Remove any aria-hidden overlays
                document.querySelectorAll('[aria-hidden="true"][data-state="open"]').forEach(el => {
                    el.remove();
                    removed++;
                });

                // 6. Remove any fixed/absolute overlays with high z-index that could block
                document.querySelectorAll('div[data-radix-portal]').forEach(el => {
                    el.remove();
                    removed++;
                });

                return removed;
            }
        """

        # Try dismissing overlays multiple times (they can reappear)
        for dismiss_attempt in range(3):
            removed = await page.evaluate(DISMISS_OVERLAYS_JS)
            if removed > 0:
                log(bot_id, "🧹", f"Removed {removed} overlay(s) (attempt {dismiss_attempt+1})", "gry")
            await asyncio.sleep(1)

        # ── Fill form using JavaScript (bypasses pointer event interception) ──
        # Using page.evaluate() to set values directly avoids the Radix dialog
        # blocking Playwright's click/fill actions via pointer event interception.
        await page.locator(SEL["name_field"]).wait_for(state="visible", timeout=PAGE_TIMEOUT)

        await page.evaluate("""
            (data) => {
                // Helper to trigger React's onChange by setting value via native setter
                function setNativeValue(element, value) {
                    const valueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    valueSetter.call(element, value);
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                }

                const nameEl = document.querySelector('[name="fullName"]');
                const emailEl = document.querySelector('[name="email"]');

                if (nameEl) {
                    nameEl.focus();
                    setNativeValue(nameEl, data.name);
                }
                if (emailEl) {
                    emailEl.focus();
                    setNativeValue(emailEl, data.email);
                }
            }
        """, {"name": name, "email": email})
        await asyncio.sleep(1)

        # Verify the values were set correctly
        actual_name = await page.locator(SEL["name_field"]).input_value()
        actual_email = await page.locator(SEL["email_field"]).input_value()

        if actual_name != name or actual_email != email:
            log(bot_id, "⚠️", f"JS fill incomplete (name='{actual_name}', email='{actual_email}'), retrying with type()", "yel")
            # Fallback: use force clicks + type character by character
            await page.evaluate(DISMISS_OVERLAYS_JS)
            await asyncio.sleep(0.5)

            name_loc = page.locator(SEL["name_field"])
            await name_loc.click(force=True)
            await name_loc.fill(name, force=True)
            await asyncio.sleep(0.3)

            email_loc = page.locator(SEL["email_field"])
            await email_loc.click(force=True)
            await email_loc.fill(email, force=True)
            await asyncio.sleep(0.3)

        log(bot_id, "📝", f"Form filled — {name} / {email}", "gry")

        # ── Dismiss overlays again before clicking Join ───────────────────────
        await page.evaluate(DISMISS_OVERLAYS_JS)
        await asyncio.sleep(0.5)

        # ── Click join ────────────────────────────────────────────────────────
        # Use JavaScript click as primary (immune to overlays), with Playwright force-click as fallback
        clicked = await page.evaluate("""
            () => {
                // Try multiple selectors for the join button
                const selectors = [
                    "button:has-text('Join')",
                    'button[type="submit"]',
                    'button:contains("Join")',
                ];

                // Find the button by checking all buttons on the page
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    const text = btn.textContent.trim().toLowerCase();
                    if (text.includes('join') && !btn.disabled) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }
        """)

        if not clicked:
            # Fallback to Playwright's force click
            join_el = page.locator(SEL["join_button"])
            await join_el.wait_for(state="visible", timeout=PAGE_TIMEOUT)
            await join_el.click(force=True)

        log(bot_id, "🌐", "Join clicked — waiting for room…", "gry")

        # ── Wait for meeting room ─────────────────────────────────────────────
        # DETECTION STRATEGY: The join form (name/email fields) disappears
        # once we enter the meeting room. This is universal across all Konn3ct
        # versions — we don't need to guess meeting room element selectors.
        connect_start = asyncio.get_event_loop().time()
        join_form = page.locator(SEL["name_field"])

        # Also check for multiple possible meeting room indicators as fallback
        meeting_indicators = [
            'button[aria-label="Open reactions"]',
            'button[aria-label*="mute" i]',
            'button[aria-label*="Mute" i]',
            'button[aria-label*="microphone" i]',
            'button[aria-label*="camera" i]',
            'button[aria-label*="leave" i]',
            'button[aria-label*="Leave" i]',
            'button[aria-label*="end" i]',
            '[data-testid="leave-button"]',
            '[data-testid="mute-button"]',
        ]

        while not stop_event.is_set():
            now = asyncio.get_event_loop().time()
            elapsed = now - connect_start

            try:
                # PRIMARY: Join form has disappeared = we're in the meeting
                form_visible = await join_form.is_visible()
                if not form_visible and elapsed > 5:
                    # Double-check it's really gone (not just a page transition flicker)
                    await asyncio.sleep(2)
                    still_visible = await join_form.is_visible()
                    if not still_visible:
                        log(bot_id, "✅", f"JOINED — {name} ({email})", "grn")
                        joined = True
                        break
            except Exception:
                pass

            # FALLBACK: Check for any meeting room element
            try:
                for selector in meeting_indicators:
                    el = page.locator(selector).first
                    if await el.is_visible():
                        log(bot_id, "✅", f"JOINED — {name} ({email})", "grn")
                        joined = True
                        break
                if joined:
                    break
            except Exception:
                pass

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
#  BROWSER LAUNCH HELPER
# ──────────────────────────────────────────────────────────────────────────────
CHROME_ARGS = [
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
]


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
    per_browser = args.per_browser
    num_browsers = (args.bots + per_browser - 1) // per_browser

    # ── Print plan ────────────────────────────────────────────────────────────
    print(f"\n{C['wht']}{'═'*60}")
    print(f"  🚀 py_guest_new — Lightweight Bot Joiner")
    print(f"{'═'*60}{C['reset']}")
    print(f"  URL             : {meeting_url}")
    print(f"  Bots            : {args.bots}")
    print(f"  Bots per browser: {per_browser}")
    print(f"  Browser instances: {num_browsers}")
    print(f"  Stagger         : {args.stagger}s between bots")
    print(f"  Browser pause   : {args.pause}s between new browsers")
    print(f"  Auto-leave      : {'manual (Ctrl+C)' if not auto_leave_sec else f'{args.leave} min'}")
    est_ram = args.bots * 50 / 1024
    print(f"  Est. RAM        : ~{est_ram:.1f} GB")
    print(f"{C['wht']}{'═'*60}\n{C['reset']}")

    # ── Create scratch dir for error screenshots ──────────────────────────────
    os.makedirs("scratch", exist_ok=True)

    async with async_playwright() as pw:
        all_browsers = []
        all_tasks = []
        bot_counter = 0

        # ── Launch browsers, each with up to per_browser bots ─────────────────
        for browser_num in range(num_browsers):
            if stop_event.is_set():
                break

            # How many bots for this browser?
            bots_remaining = args.bots - bot_counter
            bots_this_browser = min(per_browser, bots_remaining)

            syslog("🌐", f"Launching Browser-{browser_num+1}/{num_browsers} "
                   f"(bots {bot_counter+1}–{bot_counter+bots_this_browser})", "blu")

            browser = await pw.chromium.launch(headless=True, args=CHROME_ARGS)
            all_browsers.append(browser)

            syslog("📦", f"Browser-{browser_num+1} ready — "
                   f"loading {bots_this_browser} bots", "blu")

            # Launch bots for this browser one at a time
            browser_signals = []

            for i in range(bots_this_browser):
                if stop_event.is_set():
                    break

                bot_counter += 1
                bot_id = bot_counter

                join_signal = asyncio.Event()
                browser_signals.append(join_signal)

                task = asyncio.create_task(
                    run_bot(browser, bot_id, meeting_url, stop_event, join_signal)
                )
                all_tasks.append(task)

                # Stagger between bots
                if i < bots_this_browser - 1:
                    await asyncio.sleep(args.stagger)

            # Wait for all bots in this browser to finish joining
            if browser_signals and not stop_event.is_set():
                syslog("⏳", f"Waiting for Browser-{browser_num+1} bots to connect…", "gry")
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*[s.wait() for s in browser_signals]),
                        timeout=180.0
                    )
                except asyncio.TimeoutError:
                    syslog("⚠️", f"Browser-{browser_num+1} timed out — "
                           f"some bots may not have joined", "yel")

            done_count = sum(1 for s in browser_signals if s.is_set())
            syslog("📊", f"Browser-{browser_num+1} done — "
                   f"{done_count}/{bots_this_browser} responded | "
                   f"Total: {bot_counter}/{args.bots}", "grn")

            # Pause before launching next browser
            is_last = (browser_num + 1) >= num_browsers
            if not is_last and not stop_event.is_set():
                syslog("⏳", f"Pausing {args.pause}s before next browser…", "gry")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=args.pause)
                except asyncio.TimeoutError:
                    pass

        # ── All launched ──────────────────────────────────────────────────────
        syslog("✔", f"All {bot_counter} bot(s) launched across "
               f"{len(all_browsers)} browser(s) — press Ctrl+C to stop", "grn")

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

        for b in all_browsers:
            try:
                await b.close()
            except Exception:
                pass

    syslog("✔", "All bots stopped. Goodbye!", "gry")


# ──────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="py_guest_new — Lightweight Konn3ct Bot Joiner"
    )
    parser.add_argument("--url",          required=True,            help="Meeting URL")
    parser.add_argument("--bots",         type=int,   default=100,  help="Total bots (default: 100)")
    parser.add_argument("--per-browser",  type=int,   default=20,   help="Max bots per browser process (default: 20)")
    parser.add_argument("--stagger",      type=float, default=5.0,  help="Seconds between bots (default: 5)")
    parser.add_argument("--pause",        type=float, default=10.0, help="Seconds between new browsers (default: 10)")
    parser.add_argument("--leave",        type=int,   default=0,    help="Auto-leave after N minutes (default: 0 = manual)")
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
