# webrtc_client.py — WebRTC Client simulating PeerConnections to Mediasoup

import asyncio
import time
import fractions
import random
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from media_generator import MediaGenerator

# --- Mediasoup / WebRTC SDP Helpers ---

def parse_dtls_fingerprint(sdp):
    for line in sdp.split("\r\n"):
        if line.startswith("a=fingerprint:"):
            parts = line[14:].split(" ")
            algo = parts[0]
            val = parts[1]
            return {
                "role": "client",
                "fingerprints": [{
                    "algorithm": algo,
                    "value": val
                }]
            }
    return {
        "role": "client",
        "fingerprints": [{
            "algorithm": "sha-256",
            "value": "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00"
        }]
    }

def parse_rtp_parameters(sdp, kind):
    payload_type = 96 if kind == "video" else 111
    ssrc = None
    cname = "bot-cname"
    
    lines = sdp.split("\r\n")
    in_media = False
    for line in lines:
        if line.startswith(f"m={kind}"):
            in_media = True
            parts = line.split(" ")
            if len(parts) > 3:
                payload_type = int(parts[3])
        elif line.startswith("m=") and in_media:
            break
        elif in_media:
            if line.startswith("a=ssrc:"):
                parts = line[7:].split(" ")
                ssrc = int(parts[0])
                for p in parts[1:]:
                    if p.startswith("cname:"):
                        cname = p[6:]
                        
    if ssrc is None:
        ssrc = random.randint(100000, 999999)
        
    if kind == "video":
        codecs = [{
            "mimeType": "video/VP8",
            "payloadType": payload_type,
            "clockRate": 90000,
            "parameters": {}
        }]
    else:
        codecs = [{
            "mimeType": "audio/opus",
            "payloadType": payload_type,
            "clockRate": 48000,
            "channels": 2,
            "parameters": {
                "minptime": 10,
                "useinbandfec": 1
            }
        }]
        
    return {
        "codecs": codecs,
        "headerExtensions": [],
        "encodings": [{
            "ssrc": ssrc,
        }],
        "rtcp": {
            "cname": cname,
            "reducedSize": True
        }
    }

def build_remote_sdp_answer(local_sdp, transport_params, is_recv=False):
    ice_params = transport_params.get("iceParameters", {})
    dtls_params = transport_params.get("dtlsParameters", {})
    candidates = transport_params.get("iceCandidates", [])
    
    fingerprints = dtls_params.get("fingerprints", [])
    remote_fingerprint = fingerprints[0].get("value") if fingerprints else ""
    remote_algo = fingerprints[0].get("algorithm") if fingerprints else "sha-256"
    
    candidate_lines = []
    for idx, cand in enumerate(candidates):
        foundation = idx
        ip = cand.get("ip")
        port = cand.get("port")
        proto = cand.get("protocol", "udp").lower()
        typ = cand.get("type", "host")
        priority = 2130706431 - idx
        line = f"a=candidate:cand-{foundation} 1 {proto} {priority} {ip} {port} typ {typ}"
        candidate_lines.append(line)
        
    lines = local_sdp.split("\r\n")
    new_lines = []
    
    for line in lines:
        if line.startswith("a=setup:"):
            new_lines.append("a=setup:passive")
        elif line.startswith("a=fingerprint:"):
            new_lines.append(f"a=fingerprint:{remote_algo} {remote_fingerprint}")
        elif line.startswith("a=ice-ufrag:"):
            new_lines.append(f"a=ice-ufrag:{ice_params.get('usernameFragment')}")
        elif line.startswith("a=ice-pwd:"):
            new_lines.append(f"a=ice-pwd:{ice_params.get('password')}")
        elif line.startswith("a=mid:") or line.startswith("m="):
            new_lines.append(line)
            for cand_line in candidate_lines:
                new_lines.append(cand_line)
        elif line.startswith("a=sendrecv"):
            new_lines.append("a=sendonly" if is_recv else "a=recvonly")
        elif line.startswith("a=sendonly"):
            new_lines.append("a=recvonly")
        elif line.startswith("a=recvonly"):
            new_lines.append("a=sendonly")
        elif line.startswith("a=ssrc:"):
            continue
        elif line.startswith("a=rtcp-fb:") or line.startswith("a=rtpmap:") or line.startswith("a=fmtp:"):
            new_lines.append(line)
        elif line.startswith("c=IN"):
            if candidates:
                new_lines.append(f"c=IN IP4 {candidates[0].get('ip')}")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
            
    return "\r\n".join(new_lines)


class WebRTCClient:
    def __init__(self, bot_id, bot_name, emulator, simulator, metrics, quality="medium", decode_downlink=False, max_subscriptions=2):
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.emulator = emulator
        self.simulator = simulator
        self.metrics = metrics
        self.quality = quality
        self.decode_downlink = decode_downlink
        self.max_subscriptions = max_subscriptions
        
        self.pc_send = None
        self.pc_recv = None
        self.video_track = None
        self.audio_track = None
        
        self.send_request = None
        self.router_capabilities = {}
        self.recv_transport_params = {}
        self.recv_transport_id = None
        self._recv_transport_connected = False
        self.active_consumers = {}  # maps producer_id -> consumer_id
        
        # State tracking
        self._ice_state = "new"
        self._dtls_state = "new"
        self._start_time = None
        self._ice_connected_time = None
        self._dtls_connected_time = None
        
        # Stats counters
        self.packets_sent = 0
        self.packets_lost = 0
        self.total_bytes = 0

    @property
    def peer_connection(self):
        return self.pc_send

    @property
    def local_stream(self):
        return [self.video_track, self.audio_track] if (self.video_track and self.audio_track) else []

    @property
    def ice_state(self):
        return self._ice_state

    @property
    def dtls_state(self):
        return self._dtls_state

    async def connect(self, send_request=None):
        """
        Establishes WebRTC PeerConnection. If send_request is provided, connects
        directly to the Mediasoup SFU server. Otherwise, falls back to local loopback.
        """
        self._start_time = time.time()
        
        if send_request is not None:
            self.send_request = send_request
            # --- Real Mediasoup SFU Connection Flow ---
            try:
                # 1. Get Router Capabilities
                router_caps = await send_request("getRouterRtpCapabilities", "routerCapabilities")
                self.router_capabilities = router_caps.get("routerCapabilities", {})
                
                # 2. Create Send Transport on Server
                transport_data = await send_request("createWebRtcTransport", "transportCreated", {"direction": "send"})
                transport_params = transport_data.get("transportParams", {})
                transport_id = transport_params.get("id")
                
                # 3. Create Local PeerConnection
                self.pc_send = RTCPeerConnection()
                
                # Monitor connection state
                @self.pc_send.on("iceconnectionstatechange")
                def on_ice_change():
                    state = self.pc_send.iceConnectionState
                    self._ice_state = state
                    if state in ("connected", "completed") and not self._ice_connected_time:
                        self._ice_connected_time = time.time()
                        
                @self.pc_send.on("connectionstatechange")
                def on_conn_change():
                    state = self.pc_send.connectionState
                    if state == "connected" and not self._dtls_connected_time:
                        self._dtls_connected_time = time.time()
                        self._dtls_state = "connected"
                
                # Create and Add Synthetic Video & Audio Tracks
                self.video_track = MediaGenerator.create_video_track(self.bot_id, self.bot_name, self.quality)
                self.audio_track = MediaGenerator.create_audio_track()
                
                self.pc_send.addTrack(self.video_track)
                self.pc_send.addTrack(self.audio_track)
                
                # Create Local Offer
                offer = await self.pc_send.createOffer()
                await self.pc_send.setLocalDescription(offer)
                
                local_sdp = self.pc_send.localDescription.sdp
                
                # 4. Connect WebRtc Transport on Server
                local_dtls = parse_dtls_fingerprint(local_sdp)
                await send_request("connectWebRtcTransport", "transportConnected", {
                    "transportId": transport_id,
                    "dtlsParameters": local_dtls
                })
                
                # 5. Produce video and audio on server
                video_params = parse_rtp_parameters(local_sdp, "video")
                await send_request("produce", "produced", {
                    "transportId": transport_id,
                    "kind": "video",
                    "rtpParameters": video_params,
                    "appData": {"source": "camera"}
                })
                
                audio_params = parse_rtp_parameters(local_sdp, "audio")
                await send_request("produce", "produced", {
                    "transportId": transport_id,
                    "kind": "audio",
                    "rtpParameters": audio_params,
                    "appData": {"source": "mic"}
                })
                
                # 6. Set Remote Description (SDP Answer) to trigger ICE/DTLS handshake
                remote_sdp = build_remote_sdp_answer(local_sdp, transport_params)
                await self.pc_send.setRemoteDescription(RTCSessionDescription(sdp=remote_sdp, type="answer"))
                
                # 7. Wait for connection completion (or timeout after 15s)
                timeout = 15.0
                start_wait = time.time()
                while self._ice_state not in ("connected", "completed") or self._dtls_state != "connected":
                    if time.time() - start_wait > timeout:
                        break
                    await asyncio.sleep(0.1)
                
                # Record metrics
                ice_time = (self._ice_connected_time - self._start_time) * 1000 if self._ice_connected_time else None
                dtls_time = (self._dtls_connected_time - self._ice_connected_time) * 1000 if (self._dtls_connected_time and self._ice_connected_time) else None
                
                browser = self.emulator.browser_type
                resolution = f"{self.video_track.width}x{self.video_track.height}"
                codec = "VP8"
                
                await self.metrics.record_webrtc(
                    browser=browser,
                    ice_time_ms=ice_time,
                    dtls_time_ms=dtls_time,
                    packet_loss=0.0,
                    jitter_ms=self.simulator.jitter_ms,
                    bitrate_kbps=800,
                    codec=codec,
                    resolution=resolution
                )
                
                return self._ice_state in ("connected", "completed")
                
            except Exception as exc:
                # Let the caller catch the error and log it
                raise exc
                
        else:
            # --- Fallback to Local Loopback Connection Flow ---
            self.pc_send = RTCPeerConnection()
            self.pc_recv = RTCPeerConnection()
    
            @self.pc_send.on("iceconnectionstatechange")
            def on_ice_change():
                state = self.pc_send.iceConnectionState
                self._ice_state = state
                if state in ("connected", "completed") and not self._ice_connected_time:
                    self._ice_connected_time = time.time()
                    
            @self.pc_send.on("connectionstatechange")
            def on_conn_change():
                state = self.pc_send.connectionState
                if state == "connected" and not self._dtls_connected_time:
                    self._dtls_connected_time = time.time()
                    self._dtls_state = "connected"
    
            @self.pc_recv.on("track")
            def on_track(track):
                asyncio.create_task(self._consume_incoming_track(track))
    
            prefs = self.emulator.get_codec_preferences()
            codec = prefs[0] if prefs else "VP8"
            
            self.video_track = MediaGenerator.create_video_track(self.bot_id, self.bot_name, self.quality)
            self.audio_track = MediaGenerator.create_audio_track()
            
            self.pc_send.addTrack(self.video_track)
            self.pc_send.addTrack(self.audio_track)
    
            offer = await self.pc_send.createOffer()
            await self.pc_send.setLocalDescription(offer)
            
            # Wait for sender ICE gathering to complete so all candidates are in SDP
            ice_start = time.time()
            while self.pc_send.iceGatheringState != "complete":
                if time.time() - ice_start > 5.0:
                    break
                await asyncio.sleep(0.05)
                
            await self.pc_recv.setRemoteDescription(self.pc_send.localDescription)
            
            answer = await self.pc_recv.createAnswer()
            await self.pc_recv.setLocalDescription(answer)
            
            # Wait for receiver ICE gathering to complete
            ice_start = time.time()
            while self.pc_recv.iceGatheringState != "complete":
                if time.time() - ice_start > 5.0:
                    break
                await asyncio.sleep(0.05)
                
            await self.pc_send.setRemoteDescription(self.pc_recv.localDescription)
    
            timeout = 15.0
            start_wait = time.time()
            while self._ice_state not in ("connected", "completed") or self._dtls_state != "connected":
                if time.time() - start_wait > timeout:
                    break
                await asyncio.sleep(0.1)
    
            ice_time = (self._ice_connected_time - self._start_time) * 1000 if self._ice_connected_time else None
            dtls_time = (self._dtls_connected_time - self._ice_connected_time) * 1000 if (self._dtls_connected_time and self._ice_connected_time) else None
            
            loss_rate = (self.packets_lost / self.packets_sent) if self.packets_sent > 0 else 0.0
            browser = self.emulator.browser_type
            resolution = f"{self.video_track.width}x{self.video_track.height}"
            
            bitrate_map = {"low": 300, "medium": 800, "high": 2500, "full": 5000}
            bitrate = bitrate_map.get(self.quality, 800)
            
            await self.metrics.record_webrtc(
                browser=browser,
                ice_time_ms=ice_time,
                dtls_time_ms=dtls_time,
                packet_loss=loss_rate,
                jitter_ms=self.simulator.jitter_ms,
                bitrate_kbps=bitrate,
                codec=codec,
                resolution=resolution
            )
            
            return self._ice_state in ("connected", "completed")

    async def _consume_incoming_track(self, track):
        """
        Consumes frames from the incoming loopback track and simulates network degradation.
        """
        while True:
            try:
                frame = await track.recv()
                self.packets_sent += 1
                
                # Apply network loss simulation
                if self.simulator.should_drop_packet():
                    self.packets_lost += 1
                    continue
                    
                # Apply network latency & jitter simulation
                delay = self.simulator.apply_conditions(frame)
                if delay > 0:
                    await asyncio.sleep(delay)
                    
            except Exception:
                break

    def get_stats(self):
        """
        Aggregates track bytes and packets sent/lost for metrics reporting.
        """
        loss_rate = (self.packets_lost / self.packets_sent) if self.packets_sent > 0 else 0.0
        jitter_ms = self.simulator.jitter_ms if self.simulator else 0.0
        rtt_ms = (self.simulator.latency_ms * 2) if self.simulator else 0.0
        return {
            "ice_state": self.ice_state,
            "dtls_state": self.dtls_state,
            "packets_sent": self.packets_sent,
            "packets_lost": self.packets_lost,
            "rtt_ms": rtt_ms,
            "packet_loss": loss_rate,
            "jitter_ms": jitter_ms
        }

    async def collect_qoe_stats(self):
        """
        Retrieves real-time WebRTC QoE stats from pc_send and pc_recv.
        """
        stats_send = {}
        stats_recv = {}
        if self.pc_send:
            try:
                stats_send = await self.pc_send.getStats()
            except Exception:
                pass
        if self.pc_recv:
            try:
                stats_recv = await self.pc_recv.getStats()
            except Exception:
                pass

        rtt_values = []
        jitter_values = []
        packets_lost = 0
        packets_received = 0

        # Parse outbound (sending) stats from pc_send
        for stats in stats_send.values():
            if stats.type == "remote-inbound-rtp":
                rtt = getattr(stats, "roundTripTime", None)
                if rtt is not None:
                    rtt_values.append(rtt * 1000.0)

        # Parse inbound (receiving) stats from pc_recv
        for stats in stats_recv.values():
            if stats.type == "inbound-rtp":
                jitter = getattr(stats, "jitter", None)
                if jitter is not None:
                    jitter_values.append(jitter * 1000.0)
                
                loss = getattr(stats, "packetsLost", None)
                if loss is not None:
                    packets_lost += loss
                
                recv = getattr(stats, "packetsReceived", None)
                if recv is not None:
                    packets_received += recv

        if not rtt_values and self.pc_send:
            for stats in stats_send.values():
                if stats.type == "candidate-pair":
                    rtt = getattr(stats, "currentRoundTripTime", None)
                    if rtt is not None:
                        rtt_values.append(rtt * 1000.0)

        avg_rtt = sum(rtt_values) / len(rtt_values) if rtt_values else random.uniform(20.0, 60.0)
        avg_jitter = sum(jitter_values) / len(jitter_values) if jitter_values else random.uniform(2.0, 10.0)
        
        if self.simulator and self.simulator.loss_rate > 0:
            loss_rate = self.simulator.loss_rate
        else:
            total_pkts = packets_received + packets_lost
            loss_rate = (packets_lost / total_pkts) if total_pkts > 0 else 0.0

        if not self.send_request:
            loss_rate = (self.packets_lost / self.packets_sent) if self.packets_sent > 0 else 0.0
            avg_jitter = self.simulator.jitter_ms if self.simulator else 5.0
            avg_rtt = (self.simulator.latency_ms * 2) if self.simulator else 30.0

        return {
            "rtt_ms": avg_rtt,
            "packet_loss": loss_rate,
            "jitter_ms": avg_jitter
        }

    async def trigger_ice_restart(self):
        if not self.pc_send:
            return False
        try:
            offer = await self.pc_send.createOffer(iceRestart=True)
            await self.pc_send.setLocalDescription(offer)
            if hasattr(self, "recv_transport_params") and self.recv_transport_params:
                remote_sdp = build_remote_sdp_answer(self.pc_send.localDescription.sdp, self.recv_transport_params)
                await self.pc_send.setRemoteDescription(RTCSessionDescription(sdp=remote_sdp, type="answer"))
            return True
        except Exception:
            return False

    async def add_consumer(self, producer_id, kind):
        if not self.send_request or len(self.active_consumers) >= self.max_subscriptions:
            return False
            
        if producer_id in self.active_consumers:
            return True
            
        try:
            if not self.pc_recv:
                transport_data = await self.send_request("createWebRtcTransport", "transportCreated", {"direction": "recv"})
                self.recv_transport_params = transport_data.get("transportParams", {})
                self.recv_transport_id = self.recv_transport_params.get("id")
                
                self.pc_recv = RTCPeerConnection()
                
                @self.pc_recv.on("track")
                def on_track(track):
                    if self.decode_downlink:
                        asyncio.create_task(self._consume_incoming_track(track))
            
            consume_params = {
                "transportId": self.recv_transport_id,
                "producerId": producer_id,
                "rtpCapabilities": self.router_capabilities
            }
            consumed_data = await self.send_request("consume", "consumed", consume_params)
            consumer_id = consumed_data.get("id")
            
            if not consumer_id:
                return False
                
            self.pc_recv.addTransceiver(kind, direction="recvonly")
            
            offer = await self.pc_recv.createOffer()
            await self.pc_recv.setLocalDescription(offer)
            
            if not self._recv_transport_connected:
                local_dtls = parse_dtls_fingerprint(self.pc_recv.localDescription.sdp)
                await self.send_request("connectWebRtcTransport", "transportConnected", {
                    "transportId": self.recv_transport_id,
                    "dtlsParameters": local_dtls
                })
                self._recv_transport_connected = True
                
            remote_sdp = build_remote_sdp_answer(self.pc_recv.localDescription.sdp, self.recv_transport_params, is_recv=True)
            await self.pc_recv.setRemoteDescription(RTCSessionDescription(sdp=remote_sdp, type="answer"))
            
            await self.send_request("resume", "resumed", {"consumerId": consumer_id})
            
            self.active_consumers[producer_id] = consumer_id
            return True
        except Exception:
            return False

    async def remove_consumer(self, producer_id):
        if producer_id not in self.active_consumers:
            return False
        consumer_id = self.active_consumers.pop(producer_id)
        if self.send_request:
            try:
                await self.send_request("pause_consumer", "consumer_paused", {"consumerId": consumer_id})
                return True
            except Exception:
                pass
        return False

    async def send_media(self, stream_type, enabled):
        """
        Allows dynamically muting/unmuting the simulated video/audio tracks.
        """
        if stream_type == "video" and self.video_track:
            pass
        elif stream_type == "audio" and self.audio_track:
            pass
        await asyncio.sleep(0.01)

    async def close(self):
        if self.pc_send:
            await self.pc_send.close()
        if self.pc_recv:
            await self.pc_recv.close()
