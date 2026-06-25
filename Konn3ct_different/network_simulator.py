# network_simulator.py — Simulates network condition profiles and packet degradation

import random
import asyncio
import time

NETWORK_PROFILES = {
    "ethernet": {
        "bandwidth_mbps": 100.0,
        "latency_ms": 5.0,
        "packet_loss": 0.001,  # 0.1%
        "jitter_ms": 2.0
    },
    "wi-fi": {
        "bandwidth_mbps": 50.0,
        "latency_ms": 10.0,
        "packet_loss": 0.005,  # 0.5%
        "jitter_ms": 5.0
    },
    "5g": {
        "bandwidth_mbps": 100.0,
        "latency_ms": 15.0,
        "packet_loss": 0.003,  # 0.3%
        "jitter_ms": 5.0
    },
    "4g": {
        "bandwidth_mbps": 20.0,
        "latency_ms": 40.0,
        "packet_loss": 0.01,   # 1.0%
        "jitter_ms": 10.0
    },
    "3g": {
        "bandwidth_mbps": 2.0,
        "latency_ms": 200.0,
        "packet_loss": 0.03,   # 3.0%
        "jitter_ms": 30.0
    },
    "poor": {
        "bandwidth_mbps": 0.5,
        "latency_ms": 500.0,
        "packet_loss": 0.05,   # 5.0%
        "jitter_ms": 50.0
    }
}

class NetworkSimulator:
    def __init__(self, profile_name="ethernet", degradation_enabled=False, degradation_interval=300):
        self.profile_name = profile_name.lower()
        if self.profile_name not in NETWORK_PROFILES:
            self.profile_name = "ethernet"
            
        self.degradation_enabled = degradation_enabled
        self.degradation_interval = degradation_interval
        self.start_time = time.time()
        self._load_profile(self.profile_name)

    def _load_profile(self, name):
        profile = NETWORK_PROFILES.get(name, NETWORK_PROFILES["ethernet"])
        self._bandwidth_mbps = profile["bandwidth_mbps"]
        self._latency_ms = profile["latency_ms"]
        self._packet_loss = profile["packet_loss"]
        self._jitter_ms = profile["jitter_ms"]

    @property
    def bandwidth_mbps(self):
        self._check_degradation()
        return self._bandwidth_mbps

    @property
    def latency_ms(self):
        self._check_degradation()
        return self._latency_ms

    @property
    def packet_loss(self):
        self._check_degradation()
        return self._packet_loss

    @property
    def jitter_ms(self):
        self._check_degradation()
        return self._jitter_ms

    def _check_degradation(self):
        """
        Dynamically worsens the network conditions over time if degradation is enabled.
        Worsens by one profile level every degradation_interval seconds.
        """
        if not self.degradation_enabled:
            return
            
        elapsed = time.time() - self.start_time
        steps = int(elapsed / self.degradation_interval)
        if steps == 0:
            return

        # Order of profiles from best to worst
        order = ["ethernet", "wi-fi", "5g", "4g", "3g", "poor"]
        try:
            curr_idx = order.index(self.profile_name)
            new_idx = min(curr_idx + steps, len(order) - 1)
            self._load_profile(order[new_idx])
        except ValueError:
            pass

    def apply_conditions(self, data):
        """
        Takes data packets or events and applies network delay/jitter simulation.
        Can be used to wrap data transmission.
        """
        self._check_degradation()
        # Returns latency + jitter delay in seconds
        jitter = random.uniform(-self.jitter_ms, self.jitter_ms)
        delay_ms = max(0.0, self.latency_ms + jitter)
        return delay_ms / 1000.0

    def should_drop_packet(self):
        """
        Determines whether a packet should be dropped based on packet loss probability.
        """
        self._check_degradation()
        return random.random() < self.packet_loss

    async def simulate_send(self, ws, payload_str):
        """
        Simulates sending a message through a WebSocket with latency, jitter, and packet loss.
        """
        if self.should_drop_packet():
            # Packet dropped - simulate silent failure or disconnect
            return False
            
        delay = self.apply_conditions(payload_str)
        if delay > 0:
            await asyncio.sleep(delay)
            
        await ws.send(payload_str)
        return True
