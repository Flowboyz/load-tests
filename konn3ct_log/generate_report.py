"""
generate_report.py — Builds a formatted Word report from a py_guest.py test run (Advanced Version).

Reads the JSON event log (.jsonl) written by py_guest.py during a load test,
aggregates the data (including personas, time-to-active latency, propagation latency, desyncs),
and produces a polished .docx report via build_docx_report.js.

Usage:
    python generate_report.py report_log.jsonl
    python generate_report.py report_log.jsonl --output my_report.docx
"""

import json
import sys
import argparse
import subprocess
import os
import datetime

# Force UTF-8 stdout/stderr for Windows terminal compatibility
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def load_events(path):
    events = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def percentile(lst, pct):
    if not lst:
        return 0.0
    lst_sorted = sorted(lst)
    idx = int(len(lst_sorted) * pct)
    return lst_sorted[min(idx, len(lst_sorted) - 1)]


def aggregate(events):
    config        = {}
    started_at    = None
    finished_at   = None
    final_stats   = {}
    timeline      = []   # list of (elapsed_seconds, active, joined, failed)
    failures      = []   # list of dicts: bot_id, name, email, reason, ts
    reconnects    = []   # list of dicts: bot_id, name, attempt, ts
    bot_durations = []   # list of duration_seconds for bots that completed normally
    total_bots_seen = set()

    # Advanced metrics aggregates
    persona_counts = {}
    time_to_active_values = []
    latencies_by_action = {}
    total_desyncs = 0
    desync_events = []
    abnormal_resolved = []

    for e in events:
        etype = e.get("event")

        if etype == "test_started":
            started_at = e["ts"]

        elif etype == "test_config":
            config = {k: v for k, v in e.items() if k not in ("event", "ts", "bot_id", "name", "email")}

        elif etype == "bot_joined":
            total_bots_seen.add(e.get("bot_id"))

        elif etype == "bot_failed":
            failures.append({
                "bot_id": e.get("bot_id"),
                "name":   e.get("name"),
                "email":  e.get("email"),
                "reason": e.get("reason", "unknown"),
                "ts":     e.get("ts"),
            })

        elif etype == "bot_reconnect_attempt":
            reconnects.append({
                "bot_id":  e.get("bot_id"),
                "name":    e.get("name"),
                "attempt": e.get("attempt"),
                "ts":      e.get("ts"),
            })

        elif etype == "bot_session_ended":
            dur = e.get("duration_seconds")
            if dur is not None:
                bot_durations.append(dur)

        elif etype == "stats_snapshot":
            timeline.append({
                "ts": e["ts"],
                "joined": e.get("joined", 0),
                "active": e.get("active", 0),
                "failed": e.get("failed", 0),
                "reconnects": e.get("reconnects", 0),
            })

        elif etype == "test_finished":
            finished_at = e["ts"]
            final_stats = {k: v for k, v in e.items() if k not in ("event", "ts", "bot_id", "name", "email")}

        # Advanced metrics handling
        elif etype == "persona_assigned":
            pers = e.get("persona", "unknown")
            persona_counts[pers] = persona_counts.get(pers, 0) + 1

        elif etype == "time_to_active":
            val = e.get("elapsed_ms")
            if val is not None:
                time_to_active_values.append(val)

        elif etype == "action_confirmed":
            action = e.get("action")
            elapsed = e.get("elapsed_ms")
            if action and elapsed is not None:
                if action not in latencies_by_action:
                    latencies_by_action[action] = []
                latencies_by_action[action].append(elapsed)

        elif etype == "desync_detected":
            total_desyncs += 1
            desync_events.append({
                "bot_id": e.get("bot_id"),
                "name": e.get("name"),
                "local_count": e.get("local_count", 0),
                "active_count": e.get("active_count", 0),
                "ts": e.get("ts"),
            })

        elif etype == "abnormal_action_resolved":
            abnormal_resolved.append({
                "bot_id": e.get("bot_id"),
                "name": e.get("name"),
                "action": e.get("action"),
                "outcome": e.get("outcome"),
                "status": e.get("status"),
                "details": e.get("details"),
                "ts": e.get("ts"),
            })

    # Compute elapsed seconds for timeline relative to start
    if started_at and timeline:
        t0 = datetime.datetime.fromisoformat(started_at)
        for point in timeline:
            t = datetime.datetime.fromisoformat(point["ts"])
            point["elapsed"] = round((t - t0).total_seconds())

    # Duration of whole test
    duration_str = "N/A"
    if started_at and finished_at:
        t0 = datetime.datetime.fromisoformat(started_at)
        t1 = datetime.datetime.fromisoformat(finished_at)
        total_seconds = (t1 - t0).total_seconds()
        mins, secs = divmod(int(total_seconds), 60)
        duration_str = f"{mins}m {secs}s"

    peak_active = max((p["active"] for p in timeline), default=final_stats.get("joined", 0))

    requested_bots = config.get("bots", len(total_bots_seen) + len(failures))
    joined_count   = final_stats.get("joined", len(total_bots_seen))
    failed_count   = final_stats.get("failed", len(failures))
    success_rate   = round((joined_count / requested_bots) * 100, 1) if requested_bots else 0.0

    avg_duration = round(sum(bot_durations) / len(bot_durations), 1) if bot_durations else 0.0

    abnormal_total = len(abnormal_resolved)
    abnormal_blocked = sum(1 for e in abnormal_resolved if e["status"] == "PASS")
    abnormal_allowed = sum(1 for e in abnormal_resolved if e["status"] == "FAIL")
    abnormal_pass_rate = round((abnormal_blocked / abnormal_total) * 100, 1) if abnormal_total else 100.0

    return {
        "config":          config,
        "started_at":      started_at,
        "finished_at":     finished_at,
        "duration_str":    duration_str,
        "requested_bots":  requested_bots,
        "joined_count":    joined_count,
        "failed_count":    failed_count,
        "success_rate":    success_rate,
        "peak_active":     peak_active,
        "final_stats":     final_stats,
        "timeline":        timeline,
        "failures":        failures,
        "reconnects":      reconnects,
        "avg_duration":    avg_duration,
        "total_reconnect_events": len(reconnects),
        # Advanced statistics
        "personas":        persona_counts,
        "desyncs_count":   total_desyncs,
        "desyncs":         desync_events[:20],  # cap list of events shown in report
        "time_to_active": {
            "avg": round(sum(time_to_active_values) / len(time_to_active_values), 1) if time_to_active_values else 0.0,
            "p95": round(percentile(time_to_active_values, 0.95), 1) if time_to_active_values else 0.0,
            "max": round(max(time_to_active_values), 1) if time_to_active_values else 0.0,
        },
        "latencies": {
            act: {
                "avg": round(sum(vals) / len(vals), 1),
                "p95": round(percentile(vals, 0.95), 1),
                "count": len(vals)
            } for act, vals in latencies_by_action.items()
        },
        "abnormal_stats": {
            "total": abnormal_total,
            "blocked": abnormal_blocked,
            "allowed": abnormal_allowed,
            "pass_rate": abnormal_pass_rate,
        },
        "abnormal_actions": abnormal_resolved,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate an advanced Word report from a py_guest.py test run")
    parser.add_argument("log_file", help="Path to the .jsonl report log written by py_guest.py")
    parser.add_argument("--output", default="load_test_report_advanced.docx", help="Output .docx filename")
    args = parser.parse_args()

    if not os.path.exists(args.log_file):
        print(f"❌ Log file not found: {args.log_file}")
        sys.exit(1)

    events = load_events(args.log_file)
    if not events:
        print(f"❌ Log file is empty: {args.log_file}")
        sys.exit(1)

    data = aggregate(events)

    # Write aggregated data to a temp JSON file for the Node docx-builder script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_path  = os.path.join(script_dir, "_report_data.json")
    with open(data_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    build_script = os.path.join(script_dir, "build_docx_report.js")

    print("📊 Aggregated test data:")
    print(f"   Requested bots : {data['requested_bots']}")
    print(f"   Joined         : {data['joined_count']}")
    print(f"   Failed         : {data['failed_count']}")
    print(f"   Success rate   : {data['success_rate']}%")
    print(f"   Peak active    : {data['peak_active']}")
    print(f"   Duration       : {data['duration_str']}")
    print(f"   State Desyncs  : {data['desyncs_count']}")
    if data['time_to_active']['avg'] > 0:
        print(f"   Time-to-Active : Avg={data['time_to_active']['avg']:.1f}ms, 95th={data['time_to_active']['p95']:.1f}ms")
    print()
    print("🛡️  Behavioural & Security Testing:")
    print(f"   Abnormal actions tried : {data['abnormal_stats']['total']}")
    print(f"   Correctly blocked      : {data['abnormal_stats']['blocked']}")
    print(f"   Incorrectly allowed    : {data['abnormal_stats']['allowed']}")
    print(f"   Security Pass Rate     : {data['abnormal_stats']['pass_rate']}%")
    print()
    print("📝 Building Word document...")

    result = subprocess.run(
        ["node", build_script, data_path, args.output],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print("❌ Report generation failed:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)

    print(result.stdout)
    print(f"✅ Report saved to: {args.output}")

    # Clean up temp file
    if os.path.exists(data_path):
        os.remove(data_path)


if __name__ == "__main__":
    main()
