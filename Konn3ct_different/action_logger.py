# action_logger.py — Detailed Console and File Action Logging

import sys
import datetime
import json
import asyncio

# Force UTF-8 stdout/stderr for Windows terminal compatibility
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

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

class ActionLogger:
    def __init__(self, log_path=None):
        self.log_path = log_path
        self.lock = asyncio.Lock()
        self.start_time = datetime.datetime.utcnow()
        if self.log_path:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "event": "test_started",
                    "ts": self.start_time.isoformat() + "Z",
                }) + "\n")

    def log(self, icon, colour_name, bot_id, name, msg, fingerprint=None):
        """
        Console log with browser/device context details.
        """
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        colour = C.get(colour_name, C["reset"])
        
        # Build context details if available
        context_str = ""
        if fingerprint:
            bname = fingerprint.get("browser_name", "Unknown")
            bver = fingerprint.get("browser_version", "")
            dtype = fingerprint.get("device_type", "desktop").capitalize()
            os_type = fingerprint.get("os_type", "windows").capitalize()
            context_str = f"{C['grey']}[{bname} {bver} | {dtype} | {os_type}]{C['reset']} "

        print(
            f"{C['grey']}[{ts}]{C['reset']} "
            f"{colour}{icon} Bot-{bot_id:04d}{C['reset']} "
            f"{C['grey']}({name}){C['reset']} — "
            f"{context_str}{msg}",
            flush=True,
        )

    async def log_action(self, bot_id, bot_name, email, action_type, action_value, status, latency_ms=None, fingerprint=None, **extra):
        """
        Logs a structured action event to console and records it in the JSONL log file.
        """
        # Determine icon and color based on action type
        icon = "⚙️"
        colour = "magenta"
        
        if action_type == "camera":
            icon = "📷"
            colour = "magenta"
        elif action_type == "mic":
            icon = "🎤"
            colour = "magenta"
        elif action_type == "hand":
            icon = "✋"
            colour = "magenta"
        elif action_type == "chat":
            icon = "💬"
            colour = "cyan"
        elif action_type == "screen_share":
            icon = "🖥️"
            colour = "cyan"
        elif action_type == "webrtc_connection":
            icon = "🌐"
            colour = "green" if status == "confirmed" else "red"

        # Format message based on status
        if status == "sent":
            msg = f"Sent {action_type} → {action_value} (awaiting confirmation…)"
        elif status == "acknowledged":
            lat_str = f", ack: {latency_ms:.1f}ms" if latency_ms else ""
            msg = f"{action_type.capitalize()} → {action_value} (✅ acknowledged{lat_str})"
            colour = "green"
        elif status == "broadcasted":
            lat_str = f", broadcast: {latency_ms:.1f}ms" if latency_ms else ""
            msg = f"{action_type.capitalize()} → {action_value} (📡 broadcasted{lat_str})"
            colour = "green"
        elif status == "observed":
            lat_str = f" (propagation: {latency_ms:.1f}ms)" if latency_ms else ""
            msg = f"Observed {action_type} → {action_value}{lat_str}"
            colour = "blue"
            icon = "👀"
        elif status.startswith("observed:"):
            lat_str = f" (propagation: {latency_ms:.1f}ms)" if latency_ms else ""
            msg = f"Observed: {status.split(':', 1)[1]} performed {action_type} → {action_value}{lat_str}"
            colour = "blue"
            icon = "👀"
        elif status == "rendered":
            lat_str = f" (rendered: {latency_ms:.1f}ms)" if latency_ms else ""
            msg = f"Rendered: {action_type} → {action_value}{lat_str}"
            colour = "green"
            icon = "🖥️"
        elif status in ("timed_out", "timed-out", "timeout"):
            stage = extra.get("timeout_stage", "unknown")
            msg = f"TIMEOUT: {action_type} → {action_value} at stage '{stage}'"
            colour = "red"
            icon = "⚠️"
        elif status == "unsupported":
            reason = extra.get("unsupported_reason", "unknown")
            msg = f"UNSUPPORTED: {action_type} on this browser/OS. Reason: {reason}"
            colour = "yellow"
            icon = "🚫"
        else:
            msg = f"Action {action_type} failed: {action_value}"
            colour = "red"
            icon = "❌"

        self.log(icon, colour, bot_id, bot_name, msg, fingerprint)
        
        # Write to file
        if self.log_path:
            await self.record_event(
                event_type="action_logged",
                bot_id=bot_id,
                name=bot_name,
                email=email,
                action_type=action_type,
                action_value=action_value,
                status=status,
                latency_ms=latency_ms,
                fingerprint=fingerprint,
                **extra
            )

    async def record_event(self, event_type, bot_id=None, name=None, email=None, **extra):
        if not self.log_path:
            return
        entry = {
            "event": event_type,
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "bot_id": bot_id,
            "name": name,
            "email": email,
            **extra
        }
        async with self.lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
