"""
py_guest_single.py — Single Bot Joiner

Joins exactly ONE bot to the Konn3ct meeting.
Run this script multiple times to join multiple bots independently.

Usage:
    python py_guest_single.py --url "https://..."
    python py_guest_single.py --url "https://..." --leave 10

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

# Fix Windows console encoding for Unicode characters
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
}

PAGE_TIMEOUT = 120_000

# ──────────────────────────────────────────────────────────────────────────────
#  COLOURS & LOGGING
# ──────────────────────────────────────────────────────────────────────────────
C = {
    "grn":   "\033[92m",
    "red":   "\033[91m",
    "yel":   "\033[93m",
    "blu":   "\033[94m",
    "gry":   "\033[90m",
    "wht":   "\033[97m",
    "reset": "\033[0m",
}

def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def log(icon, msg, colour="gry"):
    print(f"{C[colour]}[{ts()}] {icon} SingleBot — {msg}{C['reset']}", flush=True)

# ──────────────────────────────────────────────────────────────────────────────
#  IDENTITY GENERATOR
# ──────────────────────────────────────────────────────────────────────────────
faker_gen = Faker()
REAL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"]

def generate_identity():
    first = faker_gen.first_name()
    last  = faker_gen.last_name()
    suffix = random.randint(10, 9999)
    domain = random.choice(REAL_DOMAINS)
    name  = f"{first} {last}"
    email = f"{first.lower()}.{last.lower()}{suffix}@{domain}"
    return name, email

# ──────────────────────────────────────────────────────────────────────────────
#  LOBOTOMIZE JS
# ──────────────────────────────────────────────────────────────────────────────
LOBOTOMIZE_JS = """
() => {
    document.querySelectorAll('video').forEach(v => {
        v.pause();
        if (v.srcObject) {
            v.srcObject.getTracks().forEach(t => t.stop());
            v.srcObject = null;
        }
        v.src = ''; v.load(); v.remove();
    });
    document.querySelectorAll('audio').forEach(a => {
        a.pause();
        if (a.srcObject) {
            a.srcObject.getTracks().forEach(t => t.stop());
            a.srcObject = null;
        }
        a.src = ''; a.remove();
    });
    document.querySelectorAll('canvas').forEach(c => c.remove());
    
    const killAnimStyle = document.createElement('style');
    killAnimStyle.textContent = `*, *::before, *::after { animation: none !important; transition: none !important; }`;
    document.head.appendChild(killAnimStyle);

    window.requestAnimationFrame = (cb) => setTimeout(cb, 30000);
    window.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} };
    window.IntersectionObserver = class { observe(){} unobserve(){} disconnect(){} };

    document.querySelectorAll('[class*="video"], [class*="Video"], [class*="stream"], [class*="Stream"]').forEach(el => {
        while (el.firstChild) el.removeChild(el.firstChild);
    });
    return 'lobotomized';
}
"""

BLOCKED_DOMAINS = [
    "google-analytics.com", "googletagmanager.com", "mixpanel.com",
    "sentry.io", "hotjar.com", "segment.io", "segment.com",
    "intercom.io", "facebook.net", "doubleclick.net",
    "fullstory.com", "amplitude.com", "clarity.ms",
]

CHROME_ARGS = [
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--mute-audio",
    "--disable-blink-features=AutomationControlled", "--disable-notifications",
    "--disable-popup-blocking", "--disable-extensions",
    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    "--disable-background-networking", "--disable-default-apps", "--disable-sync",
    "--no-first-run", "--disable-software-rasterizer", "--disable-canvas-aa",
    "--disable-2d-canvas-clip-aa", "--disable-gl-drawing-for-tests",
    "--disable-features=TranslateUI,WebRtcHideLocalIpsWithMdns",
    "--disable-ipc-flooding-protection", "--js-flags=--max-old-space-size=128",
    "--disable-webrtc-hw-encoding", "--disable-webrtc-hw-decoding",
    "--force-fieldtrials=WebRTC-CpuOveruseDetection/Disabled/",
]

# ──────────────────────────────────────────────────────────────────────────────
#  BOT COROUTINE
# ──────────────────────────────────────────────────────────────────────────────
async def run_single_bot(meeting_url, auto_leave_sec):
    from playwright.async_api import async_playwright

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    def _on_signal(sig, frame):
        log("🛑", "Ctrl+C — stopping bot…", "yel")
        loop.call_soon_threadsafe(stop_event.set)
    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    if "konnectsandbox.convergenceondemand.com/conferencing/join/" in meeting_url:
        meeting_url = meeting_url.replace(
            "konnectsandbox.convergenceondemand.com/conferencing/join/",
            "meetingapp.convergenceondemand.com/join/"
        )

    print(f"\n{C['wht']}{'═'*60}")
    print(f"  🚀 py_guest_single — Single Bot Joiner")
    print(f"{'═'*60}{C['reset']}")
    print(f"  URL       : {meeting_url}")
    print(f"  Auto-leave: {'manual (Ctrl+C)' if not auto_leave_sec else f'{auto_leave_sec//60} min'}")
    print(f"{C['wht']}{'═'*60}\n{C['reset']}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=CHROME_ARGS)
        log("📦", "Browser launched", "blu")
        
        name, email = generate_identity()
        joined = False

        try:
            context = await browser.new_context(
                viewport={"width": 640, "height": 480},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                permissions=["microphone", "camera"],
                ignore_https_errors=True,
            )
            page = await context.new_page()

            async def block_heavy(route, request):
                if request.resource_type in ("image", "font", "media") or \
                   any(d in request.url for d in BLOCKED_DOMAINS) or \
                   any(request.url.endswith(ext) for ext in (".mp4", ".webm", ".ogg", ".mp3", ".wav", ".png", ".jpg", ".gif", ".svg", ".woff", ".woff2", ".ttf")):
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*", block_heavy)

            log("🌐", f"Navigating… ({name})", "gry")
            await page.goto(meeting_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            await asyncio.sleep(random.uniform(2, 4))

            DISMISS_OVERLAYS_JS = """
                () => {
                    let removed = 0;
                    document.querySelectorAll('[role="alertdialog"], [role="dialog"][data-state="open"], [data-state="open"].fixed, .backdrop-blur-sm, .backdrop-blur, [aria-hidden="true"][data-state="open"], div[data-radix-portal]').forEach(el => {
                        el.remove(); removed++;
                    });
                    return removed;
                }
            """
            for _ in range(3):
                removed = await page.evaluate(DISMISS_OVERLAYS_JS)
                if removed > 0: log("🧹", f"Removed {removed} overlay(s)", "gry")
                await asyncio.sleep(1)

            await page.locator(SEL["name_field"]).wait_for(state="visible", timeout=PAGE_TIMEOUT)
            await page.evaluate("""
                (data) => {
                    function setNativeValue(element, value) {
                        const valueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        valueSetter.call(element, value);
                        element.dispatchEvent(new Event('input', { bubbles: true }));
                        element.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    const nameEl = document.querySelector('[name="fullName"]');
                    const emailEl = document.querySelector('[name="email"]');
                    if (nameEl) { nameEl.focus(); setNativeValue(nameEl, data.name); }
                    if (emailEl) { emailEl.focus(); setNativeValue(emailEl, data.email); }
                }
            """, {"name": name, "email": email})
            await asyncio.sleep(1)

            actual_name = await page.locator(SEL["name_field"]).input_value()
            if actual_name != name:
                await page.evaluate(DISMISS_OVERLAYS_JS)
                await page.locator(SEL["name_field"]).fill(name, force=True)
                await page.locator(SEL["email_field"]).fill(email, force=True)
                await asyncio.sleep(0.5)

            log("📝", f"Form filled — {name} / {email}", "gry")
            await page.evaluate(DISMISS_OVERLAYS_JS)
            await asyncio.sleep(0.5)

            clicked = await page.evaluate("""
                () => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        if (btn.textContent.trim().toLowerCase().includes('join') && !btn.disabled) {
                            btn.click(); return true;
                        }
                    }
                    return false;
                }
            """)
            if not clicked:
                await page.locator(SEL["join_button"]).click(force=True)

            log("🌐", "Join clicked — waiting for room…", "gry")

            connect_start = asyncio.get_event_loop().time()
            join_form = page.locator(SEL["name_field"])

            while not stop_event.is_set():
                elapsed = asyncio.get_event_loop().time() - connect_start
                try:
                    if not await join_form.is_visible() and elapsed > 5:
                        await asyncio.sleep(2)
                        if not await join_form.is_visible():
                            log("✅", f"JOINED — {name} ({email})", "grn")
                            joined = True
                            break
                except Exception: pass

                if elapsed > 180:
                    raise Exception("Connection timed out (180s)")
                if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                    log("🔄", f"Still connecting… ({int(elapsed)}s)", "yel")
                await asyncio.sleep(3)

            if joined:
                await asyncio.sleep(3)
                try:
                    await page.evaluate(LOBOTOMIZE_JS)
                    log("💤", "Page lobotomized (videos/animations killed)", "gry")
                except: pass

                if auto_leave_sec:
                    log("⏱", f"Auto-leave in {auto_leave_sec//60} minutes", "gry")
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=auto_leave_sec)
                    except asyncio.TimeoutError:
                        log("🚪", "Auto-leave time reached", "yel")
                else:
                    await stop_event.wait()

        except asyncio.CancelledError:
            log("🚪", "Cancelled", "yel")
        except Exception as exc:
            log("❌", str(exc), "red")
        finally:
            log("🛑", "Shutting down bot…", "yel")
            try:
                if browser: await browser.close()
            except: pass
            log("✔", "Bot stopped. Goodbye!", "gry")


def main():
    parser = argparse.ArgumentParser(description="py_guest_single — Single Bot Joiner")
    parser.add_argument("--url",   required=True, help="Meeting URL")
    parser.add_argument("--leave", type=int, default=0, help="Auto-leave after N minutes (default: 0 = manual)")
    args = parser.parse_args()

    if not args.url.startswith("http"):
        print(f"{C['red']}❌  URL must start with http/https{C['reset']}")
        sys.exit(1)

    auto_leave_sec = args.leave * 60 if args.leave > 0 else None
    try:
        asyncio.run(run_single_bot(args.url, auto_leave_sec))
    except KeyboardInterrupt:
        print(f"\n{C['yel']}🛑  Interrupted — goodbye!{C['reset']}")

if __name__ == "__main__":
    main()
