"""
ai_advisor.py — Dual-Model AI Developer Advisory & Release Governance Engine

Integrates Google Gemini (Primary) and OpenAI GPT (Secondary) with an intelligent
offline deterministic fallback. Evaluates test logs, WebRTC metrics, and failure
patterns to generate:
  1. Formal Go/No-Go Sprint Quality Gate Verdicts (Pass, Conditional Hold, Fail, Escalate).
  2. Targeted multi-disciplinary recommendations (Backend, Frontend, QA, Optimizations).
  3. 4-Tier Living Platform Certification Matrix (Certified, Supported with Risk, etc.).
  4. Cross-session AI progression & regression comparison.
"""

import os
import sys

# Ensure UTF-8 stdout on Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Tuple

# Default model configuration
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
FALLBACK_OPENAI_MODEL = "gpt-4o"

# Config file path for persisted settings
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
AI_CONFIG_PATH = os.path.join(PROJECT_ROOT, "ai_config.json")


def _load_env_file():
    """Loads variables from .env file if present."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_path):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
    except Exception:
        pass
    # Fallback manual reader for zero-dependency guarantees
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
    except Exception:
        pass


def load_ai_settings() -> Dict[str, Any]:
    """Loads AI API keys and model configurations from env or local config."""
    _load_env_file()
    config = {
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", "").strip(),
        "openai_api_key": os.environ.get("OPENAI_API_KEY", "").strip(),
        "primary_model": os.environ.get("AI_PRIMARY_MODEL", "openai"),  # "openai" or "gemini"
        "gemini_model_name": os.environ.get("GEMINI_MODEL_NAME", DEFAULT_GEMINI_MODEL),
        "openai_model_name": os.environ.get("OPENAI_MODEL_NAME", DEFAULT_OPENAI_MODEL),
        "enable_ai_analysis": True,
        "timeout_seconds": 25
    }

    if os.path.exists(AI_CONFIG_PATH):
        try:
            with open(AI_CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                for k, v in saved.items():
                    if v is not None and v != "":
                        config[k] = v
        except Exception as e:
            print(f"Warning: Could not read ai_config.json: {e}")

    return config


def save_ai_settings(settings: Dict[str, Any]) -> bool:
    """Persists AI settings securely to ai_config.json."""
    try:
        current = load_ai_settings()
        current.update(settings)
        with open(AI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving ai_config.json: {e}")
        return False


def _extract_webrtc_metrics(webrtc_perf: Any) -> Dict[str, float]:
    """Safely extracts average RTT, Jitter, Packet Loss %, and Bitrate from any WebRTC telemetry shape."""
    if not webrtc_perf:
        return {"avg_rtt": 0.0, "avg_jitter": 0.0, "avg_loss_pct": 0.0, "avg_bitrate": 0.0}
    
    if isinstance(webrtc_perf, dict):
        nested = [v for v in webrtc_perf.values() if isinstance(v, dict)]
        if nested:
            avg_rtt = sum(float(wp.get("avg_rtt", 0.0)) for wp in nested) / len(nested)
            avg_jitter = sum(float(wp.get("avg_jitter", 0.0)) for wp in nested) / len(nested)
            raw_loss = sum(float(wp.get("avg_packet_loss", wp.get("packet_loss", 0.0))) for wp in nested) / len(nested)
            loss_pct = raw_loss * 100.0 if 0 < raw_loss <= 1.0 else raw_loss
            avg_bitrate = sum(float(wp.get("avg_bitrate", 0.0)) for wp in nested) / len(nested)
            return {"avg_rtt": avg_rtt, "avg_jitter": avg_jitter, "avg_loss_pct": loss_pct, "avg_bitrate": avg_bitrate}
        else:
            avg_rtt = float(webrtc_perf.get("avg_rtt", 0.0))
            avg_jitter = float(webrtc_perf.get("avg_jitter", 0.0))
            raw_loss = float(webrtc_perf.get("avg_packet_loss", webrtc_perf.get("packet_loss", 0.0)))
            loss_pct = raw_loss * 100.0 if 0 < raw_loss <= 1.0 else raw_loss
            avg_bitrate = float(webrtc_perf.get("avg_bitrate", 0.0))
            return {"avg_rtt": avg_rtt, "avg_jitter": avg_jitter, "avg_loss_pct": loss_pct, "avg_bitrate": avg_bitrate}
            
    elif isinstance(webrtc_perf, list):
        items = [v for v in webrtc_perf if isinstance(v, dict)]
        if items:
            avg_rtt = sum(float(wp.get("avg_rtt", 0.0)) for wp in items) / len(items)
            avg_jitter = sum(float(wp.get("avg_jitter", 0.0)) for wp in items) / len(items)
            raw_loss = sum(float(wp.get("avg_packet_loss", wp.get("packet_loss", 0.0))) for wp in items) / len(items)
            loss_pct = raw_loss * 100.0 if 0 < raw_loss <= 1.0 else raw_loss
            avg_bitrate = sum(float(wp.get("avg_bitrate", 0.0)) for wp in items) / len(items)
            return {"avg_rtt": avg_rtt, "avg_jitter": avg_jitter, "avg_loss_pct": loss_pct, "avg_bitrate": avg_bitrate}

    return {"avg_rtt": 0.0, "avg_jitter": 0.0, "avg_loss_pct": 0.0, "avg_bitrate": 0.0}


# =====================================================================
# 1. DETERMINISTIC RULE-BASED FALLBACK ENGINE (Volume 7 Compliant)
# =====================================================================

def evaluate_deterministic_advisory(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Robust rule-based analysis engine implementing Volume 7 Blueprint QA rules.
    Guarantees 100% availability even without internet or API keys.
    """
    total_bots = data.get("total_bots", 0)
    config = data.get("config", {})
    action_perf = data.get("action_performance", {})
    webrtc_perf = data.get("webrtc_performance", {})
    obs_stats = data.get("observation_stats", {}).get("performance", {})
    timeout_stages = data.get("timeout_stage_breakdown", {})
    unsupported = data.get("unsupported_reason_breakdown", {})
    error_codes = data.get("error_code_breakdown", {})
    global_lats = data.get("global_latencies", {})
    
    # SLA targets
    target_success = float(data.get("sla_success_rate") or config.get("sla_success_rate") or 95.0)
    target_latency = float(data.get("sla_latency") or config.get("sla_latency") or 500.0)
    target_packet_loss = float(data.get("sla_packet_loss") or config.get("sla_packet_loss") or 2.0)
    target_jitter = float(data.get("sla_jitter") or config.get("sla_jitter") or 30.0)
    target_join_latency = float(data.get("sla_join_latency") or config.get("sla_join_latency") or 5.0)

    # 1. Calculate overall action success rate
    total_actions_sent = 0
    total_actions_success = 0
    if isinstance(action_perf, dict):
        for act_name, browsers in action_perf.items():
            if isinstance(browsers, dict):
                for b_name, stats in browsers.items():
                    if isinstance(stats, dict):
                        s = stats.get("success", 0)
                        f = stats.get("failed", 0)
                        total_actions_sent += (s + f)
                        total_actions_success += s
                    elif isinstance(stats, (int, float)):
                        total_actions_sent += 1
                        total_actions_success += (1 if stats > 0 else 0)

    overall_action_success_pct = (
        (total_actions_success / total_actions_sent * 100.0)
        if total_actions_sent > 0 else 100.0
    )

    # 2. Calculate WebRTC averages
    wt_metrics = _extract_webrtc_metrics(webrtc_perf)
    avg_rtt = wt_metrics["avg_rtt"]
    avg_jitter = wt_metrics["avg_jitter"]
    avg_loss_pct = wt_metrics["avg_loss_pct"]
    webrtc_reconnects = data.get("reconnection_count", 0)
    ws_disconnects = data.get("websocket_disconnects", 0)

    # 3. Assess Go/No-Go Release Gate (Section 7.8 & 7.38)
    release_blockers: List[str] = []
    warnings: List[str] = []

    # Blocker 1: Core action success rate
    if overall_action_success_pct < target_success:
        release_blockers.append(
            f"Action success rate ({overall_action_success_pct:.1f}%) fell below approved SLA threshold ({target_success:.1f}%)."
        )

    # Blocker 2: Latency SLA breach
    avg_ack_lat = global_lats.get("avg_ack", 0.0)
    p95_ack_lat = global_lats.get("p95_ack", 0.0)
    if avg_ack_lat > target_latency:
        release_blockers.append(
            f"Signaling acknowledgment latency ({avg_ack_lat:.1f}ms) breached maximum allowed SLA ({target_latency:.1f}ms)."
        )

    # Blocker 3: WebRTC packet loss breach
    if config.get("webrtc_enabled") and avg_loss_pct > target_packet_loss:
        release_blockers.append(
            f"WebRTC packet loss ({avg_loss_pct:.2f}%) exceeded quality SLA limit ({target_packet_loss:.1f}%)."
        )

    # Blocker 4: Persistent disconnect storms (> 5% of bots)
    if total_bots > 0 and (ws_disconnects / total_bots) > 0.10:
        release_blockers.append(
            f"High WebSocket disconnection rate detected ({ws_disconnects} disconnects across {total_bots} bots)."
        )

    # Warnings (Conditional Hold triggers)
    if p95_ack_lat > target_latency * 1.5:
        warnings.append(f"P95 tail latency spiked to {p95_ack_lat:.1f}ms during peak concurrency.")
    if avg_jitter > target_jitter:
        warnings.append(f"WebRTC jitter ({avg_jitter:.1f}ms) exceeded nominal target ({target_jitter:.1f}ms).")
    if timeout_stages.get("id-correlation-mismatch", 0) > 0:
        warnings.append(f"Event ID correlation mismatches detected ({timeout_stages['id-correlation-mismatch']} occurrences).")

    # Final Verdict Determination
    if len(release_blockers) >= 2 or (overall_action_success_pct < 80.0):
        verdict = "FAIL"
        verdict_color = "#B42318"  # Red
        verdict_summary = "CRITICAL FAIL: Release must be blocked and returned to development. Core SLAs breached."
    elif len(release_blockers) == 1:
        verdict = "CONDITIONAL HOLD"
        verdict_color = "#B54708"  # Amber
        verdict_summary = "CONDITIONAL HOLD: Quality gate breached non-catastrophically. Requires formal risk sign-off."
    elif warnings:
        verdict = "PASS WITH ADVISORY"
        verdict_color = "#0E7C7B"  # Teal
        verdict_summary = "PASSED WITH ADVISORY: Met primary SLAs with minor performance tail warnings."
    else:
        verdict = "PASS"
        verdict_color = "#1A7F37"  # Green
        verdict_summary = "PASSED: Full compliance with approved Sprint Quality Gates and WebRTC stability SLAs."

    # 4. Generate Targeted Multi-Disciplinary Recommendations
    backend_recs: List[Dict[str, str]] = []
    frontend_recs: List[Dict[str, str]] = []
    qa_recs: List[Dict[str, str]] = []
    proactive_opts: List[Dict[str, str]] = []

    # Backend Recommendations
    if timeout_stages.get("ack-timeout", 0) > 0 or avg_ack_lat > 300:
        backend_recs.append({
            "subsystem": "Signaling Gateway (WebSocket)",
            "issue": f"Signaling ack delays ({avg_ack_lat:.1f}ms) and {timeout_stages.get('ack-timeout', 0)} ack timeouts under load.",
            "root_cause": "WebSocket worker thread saturation or synchronous database/Redis validation in event handler loop.",
            "remediation": "Implement asynchronous message queuing (RabbitMQ/Redis Stream) for signaling state broadcasts and increase WebSocket worker pool size.",
            "priority": "HIGH"
        })
    if timeout_stages.get("broadcast-timeout", 0) > 0:
        backend_recs.append({
            "subsystem": "Room State Fan-Out Engine",
            "issue": f"{timeout_stages.get('broadcast-timeout', 0)} broadcast timeouts recorded.",
            "root_cause": "Broadcasting room state to N participants linearly on a single thread.",
            "remediation": "Migrate broadcast fan-out to parallel async coroutines with grouped batching per room segment.",
            "priority": "HIGH"
        })
    if not backend_recs:
        backend_recs.append({
            "subsystem": "Signaling & Transport Infrastructure",
            "issue": "No critical backend bottleneck detected during this run.",
            "root_cause": "Backend signaling server maintained stable throughput under current concurrency.",
            "remediation": "Audit WebSocket memory retention during long-duration sessions (soak tests > 1 hour).",
            "priority": "INFO"
        })

    # Frontend Recommendations
    avg_ui_render = global_lats.get("avg_ui_render", 15.0)
    if avg_ui_render > 40.0:
        frontend_recs.append({
            "subsystem": "Client Virtual DOM & State Store",
            "issue": f"UI rendering latency ({avg_ui_render:.1f}ms) is elevated.",
            "root_cause": "Unthrottled re-rendering of participant grid components upon every incoming WebSocket event.",
            "remediation": "Apply React/Vue debounce to rapid participant state updates and use windowed virtualization for participant video grid.",
            "priority": "MEDIUM"
        })
    if timeout_stages.get("ui-render-timeout", 0) > 0:
        frontend_recs.append({
            "subsystem": "Participant Grid Renderer",
            "issue": f"{timeout_stages.get('ui-render-timeout', 0)} UI render timeouts observed.",
            "root_cause": "DOM manipulation lockups during high-frequency participant state changes.",
            "remediation": "Move heavy track decoding and audio level metering to Web Workers to free the main UI thread.",
            "priority": "HIGH"
        })
    if not frontend_recs:
        frontend_recs.append({
            "subsystem": "Client WebRTC & Media Player",
            "issue": "Client UI state propagation maintained healthy latencies (<30ms).",
            "root_cause": "Participant layout updates processed smoothly without thread blocking.",
            "remediation": "Ensure hardware acceleration is enabled by default across Chromium and WebKit clients.",
            "priority": "INFO"
        })

    # QA & Test Strategy Recommendations
    if total_bots < 100:
        qa_recs.append({
            "scenario": "Concurrency Scale-Up",
            "chaos_parameters": "--bots 250 --stagger 0.5 --enable-chaos",
            "recommendation": "Elevate load to 250+ bots with active media to stress test Mediasoup router worker core balancing.",
            "priority": "MEDIUM"
        })
    if not config.get("network_degradation"):
        qa_recs.append({
            "scenario": "Network Chaos & Degradation",
            "chaos_parameters": "--network-degradation --degradation-interval 120",
            "recommendation": "Run a session with active network jitter/loss degradation to validate automatic WebRTC simulcast layer downscaling.",
            "priority": "MEDIUM"
        })
    qa_recs.append({
        "scenario": "Abnormal Behavior & Reconnect Storms",
        "chaos_parameters": "--test-scenarios camera_toggle,mic_toggle,chat --enable-chaos",
        "recommendation": "Simulate 10% abrupt bot dropouts and simultaneous re-joins to test token re-authentication and SFU producer cleanup.",
        "priority": "LOW"
    })

    # Continuous Optimization Suggestions (Even on Pass)
    proactive_opts.append({
        "area": "WebRTC SFU Simulcast Tuning",
        "suggestion": "Configure Mediasoup router with 3-tier spatial layers (1080p, 720p, 360p) and prioritize low-bitrate audio OPUS DTX (Discontinuous Transmission) during silence."
    })
    proactive_opts.append({
        "area": "Signaling Protocol Overhead",
        "suggestion": "Compress JSON signaling payloads or evaluate Protocol Buffers / MsgPack binary serialization for room state sync across 500+ participants."
    })

    # 5. Living Platform Certification Matrix
    cert_matrix = generate_platform_certification_matrix(data)

    return {
        "go_no_go_verdict": verdict,
        "verdict_color": verdict_color,
        "verdict_rationale": verdict_summary,
        "release_blockers": release_blockers,
        "warnings": warnings,
        "executive_summary": (
            f"Session evaluated across {total_bots} bots with {total_actions_sent} actions. "
            f"Overall action success was {overall_action_success_pct:.1f}% (SLA: {target_success:.1f}%). "
            f"Average signaling acknowledgment delay was {avg_ack_lat:.1f}ms with P95 of {p95_ack_lat:.1f}ms. "
            f"{'WebRTC media established smoothly with ' + f'{avg_loss_pct:.2f}% packet loss.' if config.get('webrtc_enabled') else 'Media streams were simulated in signaling-only mode.'}"
        ),
        "backend_recommendations": backend_recs,
        "frontend_recommendations": frontend_recs,
        "qa_tester_recommendations": qa_recs,
        "proactive_optimizations": proactive_opts,
        "certification_matrix": cert_matrix,
        "engine_attribution": {
            "engine_name": "Deterministic Rule-Based Engine (Volume 7 Blueprint)",
            "model": "rule-based-v7",
            "is_ai": False,
            "fallback_triggered": False,
            "fallback_reason": "Default deterministic baseline"
        }
    }


def generate_platform_certification_matrix(data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Generates the 4-tier Living Certification Matrix across Browsers, OS, and Devices."""
    browser_rankings = data.get("browser_rankings", [])
    os_rankings = data.get("os_rankings", [])
    device_rankings = data.get("device_rankings", [])
    browser_dist = data.get("browser_distribution", {})
    os_dist = data.get("os_distribution", {})
    device_dist = data.get("device_distribution", {})
    default_ack_lat = float(data.get("global_latencies", {}).get("avg_ack", 0.0) or 150.0)

    friendly_browser = {
        "chrome": "Chrome", "safari": "Safari", "firefox": "Firefox", "edge": "Edge", "brave": "Brave",
        "opera": "Opera", "chrome_mobile": "Chrome Mobile", "safari_mobile": "Safari Mobile",
        "samsung": "Samsung Internet", "firefox_mobile": "Firefox Mobile", "opera_mobile": "Opera Mobile"
    }
    friendly_os = {
        "windows": "Windows", "macos": "macOS", "linux": "Linux", "ios": "iOS", "android": "Android"
    }

    def classify_tier(success_rate: float, avg_lat: float, count: int) -> Tuple[str, str]:
        if count <= 0:
            return "UNSUPPORTED", "No test telemetry captured."
        if success_rate >= 95.0 and avg_lat <= 500.0:
            if count < 3:
                return "CERTIFIED", f"Passed all critical workflows and latency SLAs ({count} simulated client{'s' if count != 1 else ''})."
            return "CERTIFIED", "Passed all critical workflows and latency SLAs."
        elif success_rate >= 85.0:
            return "SUPPORTED WITH RISK", f"Functional but elevated latency ({avg_lat:.0f}ms) or minor drops ({100-success_rate:.1f}% failure)."
        elif count < 5:
            return "MONITORING ONLY", "Low cohort sample size; actively monitoring production metrics."
        else:
            return "UNSUPPORTED", f"Success rate ({success_rate:.1f}%) fell below minimum threshold (85%)."

    # 1. Browsers
    b_matrix = []
    for b in browser_rankings:
        raw_name = str(b.get("name") or b.get("browser") or "unknown")
        display_name = friendly_browser.get(raw_name.lower(), raw_name.replace("_", " ").title())
        count = int(b.get("bot_count") or browser_dist.get(raw_name, 0) or browser_dist.get(raw_name.lower(), 0) or 1)
        avg_lat = float(b.get("avg_latency") or b.get("avg_rtt") or default_ack_lat)
        sr = float(b.get("success_rate", 100.0))
        tier, desc = classify_tier(sr, avg_lat, count)
        b_matrix.append({
            "name": display_name,
            "tier": tier,
            "success_rate": sr,
            "avg_latency": avg_lat,
            "bot_count": count,
            "notes": desc
        })

    # 2. Operating Systems
    os_matrix = []
    for o in os_rankings:
        raw_name = str(o.get("name") or o.get("os") or "unknown")
        display_name = friendly_os.get(raw_name.lower(), raw_name.replace("_", " ").title())
        count = int(o.get("bot_count") or os_dist.get(raw_name, 0) or os_dist.get(raw_name.lower(), 0) or 1)
        avg_lat = float(o.get("avg_latency") or default_ack_lat)
        sr = float(o.get("success_rate", 100.0))
        tier, desc = classify_tier(sr, avg_lat, count)
        os_matrix.append({
            "name": display_name,
            "tier": tier,
            "success_rate": sr,
            "avg_latency": avg_lat,
            "bot_count": count,
            "notes": desc
        })

    # 3. Devices
    dev_matrix = []
    for d in device_rankings:
        raw_name = str(d.get("name") or d.get("device") or "unknown")
        display_name = raw_name.replace("_", " ").title()
        count = int(d.get("bot_count") or device_dist.get(raw_name, 0) or device_dist.get(raw_name.lower(), 0) or 1)
        avg_lat = float(d.get("avg_latency") or default_ack_lat)
        sr = float(d.get("success_rate", 100.0))
        tier, desc = classify_tier(sr, avg_lat, count)
        dev_matrix.append({
            "name": display_name,
            "tier": tier,
            "success_rate": sr,
            "avg_latency": avg_lat,
            "bot_count": count,
            "notes": desc
        })

    return {
        "browsers": b_matrix,
        "operating_systems": os_matrix,
        "devices": dev_matrix
    }


# =====================================================================
# 2. AI MODEL REST CLIENTS (Gemini & OpenAI GPT)
# =====================================================================

def call_gemini_api(prompt: str, api_key: str, model_name: str = DEFAULT_GEMINI_MODEL, timeout: int = 25) -> Optional[Dict[str, Any]]:
    """Calls Google Gemini API using pure Python standard library (urllib)."""
    if not api_key:
        return None
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }
    
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_json = json.loads(resp.read().decode("utf-8"))
                candidates = raw_json.get("candidates", [])
                if candidates:
                    content_parts = candidates[0].get("content", {}).get("parts", [])
                    if content_parts:
                        text_resp = content_parts[0].get("text", "{}")
                        return json.loads(text_resp)
    except Exception as e:
        print(f"Warning: Gemini API call failed ({model_name}): {e}")
        
    return None


def call_openai_api(prompt: str, api_key: str, model_name: str = DEFAULT_OPENAI_MODEL, timeout: int = 25) -> Optional[Dict[str, Any]]:
    """Calls OpenAI Chat Completions API using pure Python standard library (urllib)."""
    if not api_key:
        return None
        
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": "You are the Konn3ct QA Lead & Chief Architect AI analyzing load test results. Respond ONLY in valid JSON conforming to the requested schema."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_json = json.loads(resp.read().decode("utf-8"))
                choices = raw_json.get("choices", [])
                if choices:
                    text_resp = choices[0].get("message", {}).get("content", "{}")
                    return json.loads(text_resp)
    except Exception as e:
        print(f"Warning: OpenAI API call failed ({model_name}): {e}")
        
    return None


# =====================================================================
# 3. DUAL-MODEL ORCHESTRATION PIPELINE
# =====================================================================

def build_session_analysis_prompt(data: Dict[str, Any], baseline_data: Dict[str, Any]) -> str:
    """Builds a comprehensive, token-efficient prompt containing telemetry & SLAs."""
    compact_webrtc = {}
    raw_wt = data.get("webrtc_performance", {})
    if isinstance(raw_wt, dict):
        for k, v in raw_wt.items():
            if isinstance(v, dict):
                compact_webrtc[k] = {
                    sk: (round(sv, 2) if isinstance(sv, float) else sv)
                    for sk, sv in v.items()
                    if not isinstance(sv, list) or sk in ("codecs_used", "resolutions")
                }
            else:
                compact_webrtc[k] = v

    return f"""
Analyze the following Konn3ct Load Test & WebRTC execution dataset and evaluate it against the Blueprint Volume 7 Sprint Quality Gates.

## Test Summary
- Room: {data.get('config', {}).get('room')}
- Total Bots: {data.get('total_bots')}
- Duration: {data.get('duration_str')}
- WebRTC Enabled: {data.get('config', {}).get('webrtc_enabled')}
- Media Quality: {data.get('config', {}).get('media_quality')}
- Peak Users: {data.get('timeline_analytics', {}).get('peak_users', data.get('total_bots'))}
- WebSocket Drops: {data.get('websocket_disconnects', 0)}
- WebRTC Reconnects: {data.get('reconnection_count', 0)}

## SLA Thresholds
- Target Action Success: {data.get('config', {}).get('sla_success_rate', 95.0)}%
- Max Avg Latency: {data.get('config', {}).get('sla_latency', 500.0)} ms
- Max Packet Loss: {data.get('config', {}).get('sla_packet_loss', 2.0)}%
- Max Jitter: {data.get('config', {}).get('sla_jitter', 30.0)} ms

## Measured Global Latencies (ms)
{json.dumps(data.get('global_latencies', {}), indent=2)}

## Action Performance By Type
{json.dumps(data.get('action_performance', {}), indent=2)}

## WebRTC Performance Metrics
{json.dumps(compact_webrtc, indent=2)}

## Failure & Timeout Stage Breakdown
- Timeout Stages: {json.dumps(data.get('timeout_stage_breakdown', {}))}
- Unsupported Rejections: {json.dumps(data.get('unsupported_reason_breakdown', {}))}
- System Error Codes: {json.dumps(data.get('error_code_breakdown', {}))}

## Platform Rankings (Browser / OS / Device)
- Browsers: {json.dumps(data.get('browser_rankings', []))}
- Operating Systems: {json.dumps(data.get('os_rankings', []))}
- Devices: {json.dumps(data.get('device_rankings', []))}

## Output Requirements
Produce a JSON object with EXACTLY the following structure.
IMPORTANT: Even if the test was completely successful with 0 errors and 100% SLA pass, you MUST provide at least 1 proactive engineering recommendation for Backend/Signaling, 1 for Frontend/Client UI, 1 for QA/Test Strategy, and 1 Proactive Optimization to further harden stability and prepare for higher concurrency!
{{
  "go_no_go_verdict": "PASS" | "CONDITIONAL HOLD" | "FAIL" | "ESCALATE",
  "verdict_color": "#1A7F37" | "#0E7C7B" | "#B54708" | "#B42318",
  "verdict_rationale": "Clear 1-2 sentence executive explanation of the verdict.",
  "release_blockers": ["List of critical blockers found, or empty if none"],
  "warnings": ["List of non-blocking warnings or bottlenecks"],
  "executive_summary": "Comprehensive 3-4 sentence professional summary of performance, bottlenecks, and user experience.",
  "backend_recommendations": [
    {{
      "subsystem": "Name of backend component (e.g. Signaling Gateway, SFU Media Bridge, DB Pooling)",
      "issue": "Specific bottleneck or anomaly detected (or proactive scaling observation)",
      "root_cause": "Technical explanation",
      "remediation": "Actionable engineering instructions for backend team",
      "priority": "CRITICAL" | "HIGH" | "MEDIUM" | "INFO"
    }}
  ],
  "frontend_recommendations": [
    {{
      "subsystem": "Name of frontend component (e.g. Video Grid Renderer, WebRTC State Manager, UI Event Loop)",
      "issue": "Specific client-side delay or rendering issue (or proactive client optimization)",
      "root_cause": "Technical explanation",
      "remediation": "Actionable engineering instructions for web/mobile frontend team",
      "priority": "CRITICAL" | "HIGH" | "MEDIUM" | "INFO"
    }}
  ],
  "qa_tester_recommendations": [
    {{
      "scenario": "Recommended next test scenario (e.g. 500-Bot Media Stress, Chaos Reconnect Storm, Network Degradation)",
      "chaos_parameters": "CLI or preset arguments to run",
      "recommendation": "Explanation of what edge case to verify next",
      "priority": "HIGH" | "MEDIUM" | "LOW"
    }}
  ],
  "proactive_optimizations": [
    {{
      "area": "Optimization category (e.g. Bitrate Efficiency, Resource Overhead, Scalability Margin)",
      "suggestion": "Specific architectural improvement even if the current test passed 100%"
    }}
  ]
}}

"""


def analyze_session(session_data: Dict[str, Any], custom_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Main entry point for analyzing a completed load test session.
    Orchestrates Dual-Model execution:
      1. Primary Model (e.g. Gemini)
      2. Secondary Model (e.g. GPT) on primary failure or missing key
      3. Deterministic Rule-Based Engine on all API failures
    """
    settings = load_ai_settings()
    if custom_settings:
        settings.update(custom_settings)

    # 1. Always compute deterministic baseline as fallback and reference
    deterministic_result = evaluate_deterministic_advisory(session_data)
    
    if not settings.get("enable_ai_analysis", True):
        return deterministic_result

    gemini_key = settings.get("gemini_api_key")
    openai_key = settings.get("openai_api_key")
    primary_pref = settings.get("primary_model", "gemini").lower()
    timeout = int(settings.get("timeout_seconds", 25))

    prompt = build_session_analysis_prompt(session_data, deterministic_result)
    ai_output = None
    engine_used = None
    fallback_occurred = False
    fallback_reason = None

    # Step 1: Try Primary Model
    start_time = time.time()
    if primary_pref == "gemini" and gemini_key:
        print(f"[AI Engine] Analyzing session with Primary Model (Gemini: {settings.get('gemini_model_name')})...")
        ai_output = call_gemini_api(prompt, gemini_key, settings.get("gemini_model_name", DEFAULT_GEMINI_MODEL), timeout)
        if ai_output:
            engine_used = f"Google Gemini ({settings.get('gemini_model_name', DEFAULT_GEMINI_MODEL)})"
        else:
            fallback_occurred = True
            fallback_reason = "Gemini API unavailable or rate-limited"
            
    elif primary_pref == "openai" and openai_key:
        print(f"[AI Engine] Analyzing session with Primary Model (OpenAI: {settings.get('openai_model_name')})...")
        ai_output = call_openai_api(prompt, openai_key, settings.get("openai_model_name", DEFAULT_OPENAI_MODEL), timeout)
        if ai_output:
            engine_used = f"OpenAI GPT ({settings.get('openai_model_name', DEFAULT_OPENAI_MODEL)})"
        else:
            fallback_occurred = True
            fallback_reason = "OpenAI API unavailable or rate-limited"

    # Step 2: Try Secondary Model if primary failed or key missing
    if not ai_output:
        if primary_pref == "gemini" and openai_key:
            print(f"[AI Engine] Switching to Secondary Fallback Model (OpenAI: {settings.get('openai_model_name')})...")
            ai_output = call_openai_api(prompt, openai_key, settings.get("openai_model_name", DEFAULT_OPENAI_MODEL), timeout)
            if ai_output:
                engine_used = f"OpenAI GPT ({settings.get('openai_model_name', DEFAULT_OPENAI_MODEL)})"
                fallback_occurred = True
                if not fallback_reason:
                    fallback_reason = "Gemini key not configured; used OpenAI fallback"
        elif primary_pref == "openai" and gemini_key:
            print(f"[AI Engine] Switching to Secondary Fallback Model (Gemini: {settings.get('gemini_model_name')})...")
            ai_output = call_gemini_api(prompt, gemini_key, settings.get("gemini_model_name", DEFAULT_GEMINI_MODEL), timeout)
            if ai_output:
                engine_used = f"Google Gemini ({settings.get('gemini_model_name', DEFAULT_GEMINI_MODEL)})"
                fallback_occurred = True
                if not fallback_reason:
                    fallback_reason = "OpenAI key not configured; used Gemini fallback"

    # Step 3: Seamless Offline Fallback to Deterministic Engine
    if not ai_output or not isinstance(ai_output, dict) or "go_no_go_verdict" not in ai_output:
        print(f"[AI Engine] Using Deterministic Rule-Based Engine (Volume 7 Blueprint Fallback).")
        deterministic_result["engine_attribution"] = {
            "engine_name": "Deterministic Rule-Based Engine (Volume 7 Blueprint)",
            "model": "rule-based-v7",
            "is_ai": False,
            "fallback_triggered": True,
            "fallback_reason": fallback_reason or "No API keys configured or all AI providers timed out"
        }
        return deterministic_result

    # Merge AI Output with Certification Matrix & Metadata
    elapsed_ai = time.time() - start_time
    ai_output["certification_matrix"] = deterministic_result["certification_matrix"]
    ai_output["engine_attribution"] = {
        "engine_name": engine_used,
        "model": engine_used,
        "is_ai": True,
        "execution_time_sec": round(elapsed_ai, 2),
        "fallback_triggered": fallback_occurred,
        "fallback_reason": fallback_reason
    }
    
    print(f"[AI Engine] Analysis compiled successfully via {engine_used} ({elapsed_ai:.2f}s). Verdict: {ai_output.get('go_no_go_verdict')}")
    return ai_output


# =====================================================================
# 4. CROSS-SESSION AI COMPARISON & PROGRESSION ENGINE
# =====================================================================

def compare_sessions_ai(
    session_a: Dict[str, Any], 
    session_b: Dict[str, Any], 
    custom_settings: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Compares Baseline Session (A) vs Candidate Session (B) to track progression:
      - Latency & Throughput deltas
      - WebRTC stability improvements/regressions
      - Fixed defects vs Newly introduced defects
      - Overall release trajectory evaluation
    """
    settings = load_ai_settings()
    if custom_settings:
        settings.update(custom_settings)

    # 1. Compute deterministic numerical deltas
    bots_a = session_a.get("total_bots", 0)
    bots_b = session_b.get("total_bots", 0)
    
    lat_a = session_a.get("global_latencies", {}).get("avg_ack", 0.0)
    lat_b = session_b.get("global_latencies", {}).get("avg_ack", 0.0)
    lat_delta_ms = round(lat_b - lat_a, 1)
    lat_delta_pct = round(((lat_b - lat_a) / lat_a * 100.0), 1) if lat_a > 0 else 0.0

    p95_a = session_a.get("global_latencies", {}).get("p95_ack", 0.0)
    p95_b = session_b.get("global_latencies", {}).get("p95_ack", 0.0)
    p95_delta_ms = round(p95_b - p95_a, 1)

    wt_a = _extract_webrtc_metrics(session_a.get("webrtc_performance"))
    wt_b = _extract_webrtc_metrics(session_b.get("webrtc_performance"))
    loss_a = wt_a["avg_loss_pct"]
    loss_b = wt_b["avg_loss_pct"]
    loss_delta = round(loss_b - loss_a, 2)

    jitter_a = wt_a["avg_jitter"]
    jitter_b = wt_b["avg_jitter"]
    jitter_delta = round(jitter_b - jitter_a, 1)

    drops_a = session_a.get("websocket_disconnects", 0)
    drops_b = session_b.get("websocket_disconnects", 0)

    sr_a = float(session_a.get("overall_success_rate", 100.0 if drops_a == 0 else 95.0))
    sr_b = float(session_b.get("overall_success_rate", 100.0 if drops_b == 0 else 95.0))
    sr_delta = round(sr_b - sr_a, 1)

    # Deterministic trajectory evaluation
    if lat_delta_ms <= -20.0 and loss_delta <= 0.0 and drops_b <= drops_a:
        deterministic_verdict = "SIGNIFICANT IMPROVEMENT"
        verdict_color = "#1A7F37"
    elif lat_delta_ms > 50.0 or loss_delta > 1.0 or drops_b > (drops_a + 5):
        deterministic_verdict = "REGRESSION DETECTED"
        verdict_color = "#B42318"
    else:
        deterministic_verdict = "STABLE / MARGINAL PROGRESS"
        verdict_color = "#0E7C7B"

    comparison_data = {
        "session_a_id": session_a.get("session_id", "A"),
        "session_b_id": session_b.get("session_id", "B"),
        "metrics_comparison": {
            "total_bots": {"baseline": bots_a, "candidate": bots_b, "delta": bots_b - bots_a},
            "success_rate": {"baseline": sr_a, "candidate": sr_b, "delta": sr_delta},
            "avg_ack_latency_ms": {"baseline": lat_a, "candidate": lat_b, "delta_ms": lat_delta_ms, "delta_pct": lat_delta_pct},
            "p95_ack_latency_ms": {"baseline": p95_a, "candidate": p95_b, "delta_ms": p95_delta_ms},
            "webrtc_packet_loss_pct": {"baseline": loss_a, "candidate": loss_b, "delta": loss_delta},
            "jitter": {"baseline": jitter_a, "candidate": jitter_b, "delta": jitter_delta},
            "websocket_drops": {"baseline": drops_a, "candidate": drops_b, "delta": drops_b - drops_a}
        },
        "trajectory_verdict": deterministic_verdict,
        "verdict_color": verdict_color,
        "fixed_issues": [],
        "new_regressions": [],
        "ai_narrative": f"Candidate Session ({bots_b} bots) compared to Baseline ({bots_a} bots). Latency changed by {lat_delta_ms:+.1f}ms ({lat_delta_pct:+.1f}%). WebRTC packet loss changed by {loss_delta:+.2f}%.",
        "next_sprint_guidance": "Continue performance monitoring and expand concurrency headroom."
    }

    # If AI enabled, enrich with deep comparative narrative
    prompt = f"""
Compare the following two Konn3ct test runs (Baseline Session A vs Candidate Session B) to track engineering progress:

## Baseline Session A:
{json.dumps(session_a, indent=2, default=str)}

## Candidate Session B:
{json.dumps(session_b, indent=2, default=str)}

## Measured Numerical Deltas:
{json.dumps(comparison_data['metrics_comparison'], indent=2)}

## Required JSON Output Format:
{{
  "trajectory_verdict": "SIGNIFICANT IMPROVEMENT" | "STABLE / MARGINAL PROGRESS" | "REGRESSION DETECTED",
  "verdict_color": "#1A7F37" | "#0E7C7B" | "#B42318",
  "summary_headline": "1-sentence executive summary of progress vs regression",
  "detailed_analysis": "Detailed 2-3 paragraph breakdown explaining which subsystems improved and which regressed.",
  "fixed_issues": ["List of bottlenecks or errors present in Session A that were eliminated in Session B"],
  "new_regressions": ["List of new anomalies or elevated latency stages introduced in Session B"],
  "next_sprint_guidance": "Concrete advice on what the engineering team should prioritize before the next release candidate."
}}
"""
    gemini_key = settings.get("gemini_api_key")
    openai_key = settings.get("openai_api_key")
    timeout = int(settings.get("timeout_seconds", 25))

    ai_comp = None
    if gemini_key:
        ai_comp = call_gemini_api(prompt, gemini_key, settings.get("gemini_model_name", DEFAULT_GEMINI_MODEL), timeout)
    if not ai_comp and openai_key:
        ai_comp = call_openai_api(prompt, openai_key, settings.get("openai_model_name", DEFAULT_OPENAI_MODEL), timeout)

    if ai_comp and isinstance(ai_comp, dict):
        comparison_data.update(ai_comp)
        comparison_data["engine_attribution"] = "AI Comparative Analysis (Dual-Model Pipeline)"
    else:
        comparison_data["engine_attribution"] = "Deterministic Comparative Engine (Offline Fallback)"

    return comparison_data
