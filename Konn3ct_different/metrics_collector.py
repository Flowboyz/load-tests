# metrics_collector.py — Advanced Metrics Collection and Aggregation

import asyncio

class MetricsCollector:
    def __init__(self):
        self.lock = asyncio.Lock()
        
        # Structure: browser -> list of metrics dictionaries
        self.webrtc_stats = {}
        
        # Structure: action_type -> browser -> list of latencies/statuses
        self.action_stats = {}
        
        # Structure: browser -> {"joined": x, "failed": y, "latencies": []}
        self.join_stats = {}

    async def record_join(self, browser, success, join_time_ms=None):
        async with self.lock:
            if browser not in self.join_stats:
                self.join_stats[browser] = {"joined": 0, "failed": 0, "join_times": []}
            if success:
                self.join_stats[browser]["joined"] += 1
                if join_time_ms is not None:
                    self.join_stats[browser]["join_times"].append(join_time_ms)
            else:
                self.join_stats[browser]["failed"] += 1

    async def record_webrtc(self, browser, ice_time_ms, dtls_time_ms, packet_loss, jitter_ms, bitrate_kbps, codec, resolution, rtt_ms=None):
        async with self.lock:
            if browser not in self.webrtc_stats:
                self.webrtc_stats[browser] = []
            self.webrtc_stats[browser].append({
                "ice_time": ice_time_ms,
                "dtls_time": dtls_time_ms,
                "packet_loss": packet_loss,
                "jitter": jitter_ms,
                "bitrate": bitrate_kbps,
                "codec": codec,
                "resolution": resolution,
                "rtt": rtt_ms
            })

    async def record_action(self, action_type, browser, status, latency_ms=None):
        async with self.lock:
            if action_type not in self.action_stats:
                self.action_stats[action_type] = {}
            if browser not in self.action_stats[action_type]:
                self.action_stats[action_type][browser] = {"success": 0, "failed": 0, "latencies": []}
                
            if status == "confirmed":
                self.action_stats[action_type][browser]["success"] += 1
                if latency_ms is not None:
                    self.action_stats[action_type][browser]["latencies"].append(latency_ms)
            else:
                self.action_stats[action_type][browser]["failed"] += 1

    def get_summary(self):
        """
        Returns structured statistics ready to be written to final report files.
        """
        summary = {
            "join_performance": {},
            "webrtc_performance": {},
            "action_performance": {}
        }
        
        # 1. Join Performance by Browser
        for browser, stats in self.join_stats.items():
            times = stats["join_times"]
            avg_time = sum(times) / len(times) if times else 0.0
            total = stats["joined"] + stats["failed"]
            success_pct = (stats["joined"] / total * 100) if total > 0 else 0.0
            summary["join_performance"][browser] = {
                "joined": stats["joined"],
                "failed": stats["failed"],
                "success_rate": success_pct,
                "avg_join_time": avg_time
            }
            
        # 2. WebRTC Performance by Browser
        for browser, entries in self.webrtc_stats.items():
            if not entries:
                continue
            ice_times = [e["ice_time"] for e in entries if e["ice_time"] is not None]
            dtls_times = [e["dtls_time"] for e in entries if e["dtls_time"] is not None]
            losses = [e["packet_loss"] for e in entries if e["packet_loss"] is not None]
            jitters = [e["jitter"] for e in entries if e["jitter"] is not None]
            bitrates = [e["bitrate"] for e in entries if e["bitrate"] is not None]
            rtts = [e["rtt"] for e in entries if e.get("rtt") is not None]
            codecs = list(set([e["codec"] for e in entries if e["codec"]]))
            resolutions = list(set([e["resolution"] for e in entries if e["resolution"]]))
            
            summary["webrtc_performance"][browser] = {
                "avg_ice_time": sum(ice_times) / len(ice_times) if ice_times else 0.0,
                "avg_dtls_time": sum(dtls_times) / len(dtls_times) if dtls_times else 0.0,
                "avg_packet_loss": sum(losses) / len(losses) if losses else 0.0,
                "avg_jitter": sum(jitters) / len(jitters) if jitters else 0.0,
                "avg_bitrate": sum(bitrates) / len(bitrates) if bitrates else 0.0,
                "avg_rtt": sum(rtts) / len(rtts) if rtts else 0.0,
                "codecs_used": codecs,
                "resolutions": resolutions
            }
            
        # 3. Action Performance by Action Type and Browser
        for action, browser_stats in self.action_stats.items():
            summary["action_performance"][action] = {}
            for browser, stats in browser_stats.items():
                lats = stats["latencies"]
                avg_lat = sum(lats) / len(lats) if lats else 0.0
                total = stats["success"] + stats["failed"]
                success_pct = (stats["success"] / total * 100) if total > 0 else 0.0
                summary["action_performance"][action][browser] = {
                    "success": stats["success"],
                    "failed": stats["failed"],
                    "success_rate": success_pct,
                    "avg_latency": avg_lat
                }
                
        return summary
