"""
py_guest.py — Konn3ct Load Testing Bot (Terminal / Headless Mode)
Simulates multiple attendees joining a Konn3ct meeting for platform stress testing.
No GUI required — runs entirely from the terminal. Ideal for Linux servers.

Dependencies:
    pip install faker selenium webdriver-manager

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
    --headless      Run Chrome in headless mode (default: headless ON for servers)
"""

import argparse
import threading
import queue
import time
import random
import datetime
import signal
import sys

from faker import Faker
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# ──────────────────────────────────────────────────────────────────────────────
#  SELECTORS — update these to match the real Konn3ct join page HTML
# ──────────────────────────────────────────────────────────────────────────────
SELECTORS = {
    "name_field":  (By.NAME,         "fullName"),
    "email_field": (By.NAME,         "email"),
    "join_button": (By.XPATH,        "//button[text()='Konn3ct']"),
    "chat_input":  (By.CSS_SELECTOR, "textarea[placeholder='Send a message to everyone']"),
    "chat_send":   (By.CSS_SELECTOR, "svg.h-6.w-6"),
}

PAGE_LOAD_TIMEOUT = 40
CHAT_MIN_INTERVAL = 30
CHAT_MAX_INTERVAL = 90

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
faker_gen         = Faker()
log_queue         = queue.Queue()
active_bots       = []
bots_lock         = threading.Lock()
stop_event        = threading.Event()

_used_identities  = set()
_identity_lock    = threading.Lock()


# ──────────────────────────────────────────────────────────────────────────────
#  LOGGER — prints to terminal with colour codes
# ──────────────────────────────────────────────────────────────────────────────
COLOURS = {
    "join":  "\033[92m",   # green
    "leave": "\033[91m",   # red
    "chat":  "\033[96m",   # cyan
    "warn":  "\033[93m",   # yellow
    "err":   "\033[91m",   # red
    "info":  "\033[90m",   # grey
    "reset": "\033[0m",
}

def log_print(msg):
    """Determine colour tag from message content and print to terminal."""
    if   "✅" in msg:                    colour = COLOURS["join"]
    elif "🚪" in msg or "closed" in msg: colour = COLOURS["leave"]
    elif "💬" in msg:                    colour = COLOURS["chat"]
    elif "❌" in msg:                    colour = COLOURS["err"]
    elif "⚠️" in msg:                    colour = COLOURS["warn"]
    else:                                colour = COLOURS["info"]
    print(f"{colour}{msg}{COLOURS['reset']}", flush=True)

def log_worker():
    """Background thread that drains the log queue and prints to terminal."""
    while True:
        try:
            msg = log_queue.get(timeout=1)
            if msg is None:
                break
            log_print(msg)
        except queue.Empty:
            continue


# ──────────────────────────────────────────────────────────────────────────────
#  IDENTITY GENERATOR
# ──────────────────────────────────────────────────────────────────────────────
def generate_identity():
    with _identity_lock:
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
#  BOT WORKER
# ──────────────────────────────────────────────────────────────────────────────
class BotWorker:
    def __init__(self, bot_id, meeting_url, auto_leave_seconds,
                 chat_enabled, headless):
        self.bot_id             = bot_id
        self.meeting_url        = meeting_url
        self.auto_leave_seconds = auto_leave_seconds
        self.chat_enabled       = chat_enabled
        self.headless           = headless
        self.display_name, self.email = generate_identity()
        self.driver    = None
        self.thread    = threading.Thread(target=self._run, daemon=True)
        self.joined_at = None

    def start(self):
        self.thread.start()

    def _log(self, icon, message):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        log_queue.put(
            f"[{ts}] {icon} Bot-{self.bot_id:03d} "
            f"({self.display_name} / {self.email}) — {message}"
        )

    def _build_driver(self):
        opts = Options()

        if self.headless:
            opts.add_argument("--headless=new")

        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1280,800")
        opts.add_argument("--mute-audio")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-popup-blocking")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--disable-extensions")
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )

        # Auto-deny camera/mic/notifications permissions
        prefs = {
            "profile.default_content_setting_values.media_stream_mic":    2,
            "profile.default_content_setting_values.media_stream_camera":  2,
            "profile.default_content_setting_values.notifications":        2,
            "profile.default_content_setting_values.geolocation":          2,
        }
        opts.add_experimental_option("prefs", prefs)
        opts.add_experimental_option("excludeSwitches", ["enable-logging"])
        opts.add_argument("--use-fake-ui-for-media-stream")
        opts.add_argument("--use-fake-device-for-media-stream")

        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)

    def _join_meeting(self):
        self.driver.get(self.meeting_url)
        time.sleep(3)

        wait = WebDriverWait(self.driver, PAGE_LOAD_TIMEOUT)

        # Name field — scroll into view, JS click, then type char by char
        name_input = wait.until(
            EC.presence_of_element_located(SELECTORS["name_field"])
        )
        self.driver.execute_script("arguments[0].scrollIntoView(true);", name_input)
        time.sleep(0.5)
        self.driver.execute_script("arguments[0].click();", name_input)
        time.sleep(0.3)
        name_input.send_keys(Keys.CONTROL + "a")
        name_input.send_keys(Keys.DELETE)
        time.sleep(0.2)
        for char in self.display_name:
            name_input.send_keys(char)
            time.sleep(random.uniform(0.05, 0.15))

        time.sleep(0.3)

        # Email field
        email_input = self.driver.find_element(*SELECTORS["email_field"])
        self.driver.execute_script("arguments[0].scrollIntoView(true);", email_input)
        time.sleep(0.3)
        self.driver.execute_script("arguments[0].click();", email_input)
        time.sleep(0.3)
        email_input.send_keys(Keys.CONTROL + "a")
        email_input.send_keys(Keys.DELETE)
        time.sleep(0.2)
        for char in self.email:
            email_input.send_keys(char)
            time.sleep(random.uniform(0.05, 0.15))

        time.sleep(0.5)

        # Join button
        join_btn = wait.until(
            EC.presence_of_element_located(SELECTORS["join_button"])
        )
        self.driver.execute_script("arguments[0].scrollIntoView(true);", join_btn)
        time.sleep(0.3)
        self.driver.execute_script("arguments[0].click();", join_btn)

    def _send_chat(self, message):
        try:
            wait = WebDriverWait(self.driver, 10)

            chatbox = wait.until(
                EC.presence_of_element_located(SELECTORS["chat_input"])
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", chatbox)
            time.sleep(0.3)
            self.driver.execute_script("arguments[0].click();", chatbox)
            time.sleep(0.3)

            chatbox.send_keys(Keys.CONTROL + "a")
            chatbox.send_keys(Keys.DELETE)
            time.sleep(0.2)
            for char in message:
                chatbox.send_keys(char)
                time.sleep(random.uniform(0.03, 0.08))

            time.sleep(0.3)
            chatbox.send_keys(Keys.RETURN)
            self._log("💬", f'Sent: "{message}"')

        except Exception as exc:
            self._log("⚠️", f"Chat failed: {exc}")

    def _run(self):
        try:
            self.driver = self._build_driver()
            self._log("🌐", "Browser launched")

            self._join_meeting()
            self.joined_at = time.time()
            self._log("✅", "Joined meeting")

            # Wait for meeting room to fully settle
            time.sleep(5)
            self._log("🏠", "Meeting room ready")

            leave_at     = (self.joined_at + self.auto_leave_seconds
                            if self.auto_leave_seconds else None)
            next_chat_at = time.time() + random.uniform(10, 20)

            while not stop_event.is_set():
                now = time.time()

                if leave_at and now >= leave_at:
                    self._log("🚪", "Auto-leaving (time limit reached)")
                    break

                if self.chat_enabled and now >= next_chat_at:
                    self._send_chat(random.choice(CHAT_MESSAGES))
                    next_chat_at = now + random.uniform(CHAT_MIN_INTERVAL, CHAT_MAX_INTERVAL)

                time.sleep(1)

        except TimeoutException:
            self._log("❌", "Timed out — page elements not found (check SELECTORS)")
        except WebDriverException as exc:
            self._log("❌", f"Browser error: {exc.msg[:100] if exc.msg else str(exc)}")
        except Exception as exc:
            self._log("❌", f"Unexpected error: {exc}")
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
            self._log("🔒", "Session closed")
            with bots_lock:
                if self in active_bots:
                    active_bots.remove(self)


# ──────────────────────────────────────────────────────────────────────────────
#  SIGNAL HANDLER — graceful Ctrl+C shutdown
# ──────────────────────────────────────────────────────────────────────────────
def handle_shutdown(sig, frame):
    print(f"\n{COLOURS['warn']}🛑  Ctrl+C detected — stopping all bots...{COLOURS['reset']}", flush=True)
    stop_event.set()


# ──────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="py_guest — Konn3ct Load Testing Bot"
    )
    parser.add_argument("--url",         required=True,      help="Meeting URL")
    parser.add_argument("--bots",        type=int, default=10, help="Number of bots (default: 10)")
    parser.add_argument("--leave",       type=int, default=0,  help="Auto-leave after N minutes, 0 = manual (default: 0)")
    parser.add_argument("--stagger-min", type=float, default=1.0, help="Min stagger delay in seconds (default: 1)")
    parser.add_argument("--stagger-max", type=float, default=4.0, help="Max stagger delay in seconds (default: 4)")
    parser.add_argument("--no-chat",     action="store_true", help="Disable chat simulation")
    parser.add_argument("--no-headless", action="store_true", help="Show Chrome windows (disables headless)")
    args = parser.parse_args()

    # Validate
    if not args.url.startswith("http"):
        print(f"{COLOURS['err']}❌  Invalid URL — must start with http/https{COLOURS['reset']}")
        sys.exit(1)

    headless      = not args.no_headless
    chat_enabled  = not args.no_chat
    auto_leave    = args.leave * 60 if args.leave > 0 else None
    smin          = args.stagger_min
    smax          = args.stagger_max

    # Register Ctrl+C handler
    signal.signal(signal.SIGINT, handle_shutdown)

    # Start log printer thread
    log_thread = threading.Thread(target=log_worker, daemon=True)
    log_thread.start()

    # Print session summary
    print(f"\n{COLOURS['info']}{'─'*65}")
    print(f"  🚀 py_guest — Konn3ct Load Testing Bot")
    print(f"{'─'*65}")
    print(f"  URL        : {args.url}")
    print(f"  Bots       : {args.bots}")
    print(f"  Stagger    : {smin}–{smax}s between each bot")
    print(f"  Auto-leave : {'manual (Ctrl+C to stop)' if not auto_leave else f'{args.leave} min'}")
    print(f"  Chat       : {'ON' if chat_enabled else 'OFF'}")
    print(f"  Headless   : {'ON' if headless else 'OFF'}")
    print(f"  Identities : faker name + @botmail.test email")
    print(f"{'─'*65}\n{COLOURS['reset']}")

    # Launch bots with stagger
    for i in range(1, args.bots + 1):
        if stop_event.is_set():
            break

        bot = BotWorker(
            bot_id=i,
            meeting_url=args.url,
            auto_leave_seconds=auto_leave,
            chat_enabled=chat_enabled,
            headless=headless,
        )
        with bots_lock:
            active_bots.append(bot)
        bot.start()

        if i < args.bots:
            delay = random.uniform(smin, smax)
            time.sleep(delay)

    print(f"{COLOURS['info']}  ✔  All {args.bots} bot(s) launched — press Ctrl+C to stop{COLOURS['reset']}\n", flush=True)

    # Keep main thread alive until stop
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        handle_shutdown(None, None)

    # Wait for all bots to finish
    print(f"{COLOURS['info']}  Waiting for bots to close...{COLOURS['reset']}", flush=True)
    with bots_lock:
        threads = [b.thread for b in active_bots]
    for t in threads:
        t.join(timeout=15)

    # Shut down log thread
    log_queue.put(None)
    log_thread.join(timeout=3)

    print(f"{COLOURS['info']}  ✔  All bots stopped. Goodbye!{COLOURS['reset']}", flush=True)


if __name__ == "__main__":
    main()