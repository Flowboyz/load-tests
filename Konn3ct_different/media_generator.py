# media_generator.py — Synthetic Audio/Video Track Generators for WebRTC

import fractions
import time
import math
import numpy as np
from aiortc import MediaStreamTrack
from av import VideoFrame, AudioFrame

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Mapping qualities to resolutions and framerates
QUALITY_PROFILES = {
    "low": {"width": 320, "height": 240, "fps": 15},     # QVGA
    "medium": {"width": 640, "height": 480, "fps": 30},  # VGA
    "high": {"width": 1280, "height": 720, "fps": 30},   # HD
    "full": {"width": 1920, "height": 1080, "fps": 30}   # FHD
}

class SyntheticVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, bot_id, bot_name, quality="medium", is_screen=False):
        super().__init__()
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.is_screen = is_screen
        self.enabled = True
        
        # Get resolution and fps from profile
        profile = QUALITY_PROFILES.get(quality, QUALITY_PROFILES["medium"])
        self.width = profile["width"]
        self.height = profile["height"]
        self.fps = profile["fps"]
        
        self.frame_count = 0
        self.time_base = fractions.Fraction(1, 90000)
        self.start_time = time.time()

    async def recv(self):
        """
        Generates and returns a VideoFrame containing vivid moving patterns,
        bouncing scanner, bot ID, name, resolution, and live timestamps.
        """
        now = time.time()
        self.frame_count += 1
        pts = int((now - self.start_time) * 90000)

        # Base image buffer
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        if not self.enabled:
            # Standby dark frame when camera is muted
            img[:, :] = [20, 24, 30]
            if HAS_PIL:
                pil_img = Image.fromarray(img)
                draw = ImageDraw.Draw(pil_img)
                draw.rectangle([self.width // 4, self.height // 2 - 30, 3 * self.width // 4, self.height // 2 + 30], fill=(40, 45, 55))
                draw.text((self.width // 4 + 20, self.height // 2 - 10), f"📷 Camera Off — Bot-{self.bot_id:04d} ({self.bot_name})", fill=(180, 190, 205))
                img = np.array(pil_img)
        elif self.is_screen:
            # Solid screen share template with dynamic animated header
            img[:, :] = [180, 30, 40]
            # Animated grid pattern
            grid_step = 40
            offset = (self.frame_count * 4) % grid_step
            for x in range(offset, self.width, grid_step):
                img[:, x:x+2] = [220, 50, 60]
            for y in range(0, self.height, grid_step):
                img[y:y+2, :] = [220, 50, 60]
        else:
            # Shifting vivid color bars background
            shift = (self.frame_count * 10) % self.width
            bar_width = math.ceil(self.width / 8)
            colors = [
                [230, 40, 40],    # Red
                [40, 200, 60],    # Green
                [40, 90, 230],    # Blue
                [240, 210, 40],   # Yellow
                [220, 40, 220],   # Magenta
                [40, 220, 220],   # Cyan
                [240, 140, 30],   # Orange
                [60, 60, 90]      # Dark Indigo
            ]
            for i in range(8):
                c = colors[i % len(colors)]
                x_start = (i * bar_width + shift) % self.width
                x_end = (x_start + bar_width) % self.width
                if x_start < x_end:
                    img[:, x_start:x_end] = c
                else:
                    img[:, x_start:] = c
                    img[:, :x_end] = c

        # Draw overlays with Pillow
        if self.enabled:
            ts_str = time.strftime("%H:%M:%S") + f".{int((now % 1) * 1000):03d}"
            
            if HAS_PIL:
                pil_img = Image.fromarray(img)
                draw = ImageDraw.Draw(pil_img)
                
                # Title badge
                badge_text = "🖥️ SCREEN SHARE ACTIVE" if self.is_screen else f"🎥 BOT LIVE FEED: Bot-{self.bot_id:04d}"
                draw.rectangle([10, 10, min(self.width - 10, 420), 40], fill=(15, 23, 42, 230))
                draw.text((20, 18), badge_text, fill=(255, 255, 255))
                
                # Info card
                info_lines = [
                    f"Name: {self.bot_name}",
                    f"Resolution: {self.width}x{self.height} @ {self.fps}fps",
                    f"Time: {ts_str} | Frame: #{self.frame_count}",
                    f"Status: WEBRTC TRANSMITTING OK"
                ]
                card_h = len(info_lines) * 22 + 15
                draw.rectangle([10, 50, min(self.width - 10, 420), 50 + card_h], fill=(15, 23, 42, 210))
                for idx, line in enumerate(info_lines):
                    draw.text((20, 58 + idx * 22), line, fill=(226, 232, 240))
                    
                # Animated bouncing orb at bottom of screen
                orb_x = int((math.sin(self.frame_count * 0.1) + 1.0) * 0.5 * (self.width - 60)) + 30
                orb_y = self.height - 35
                draw.ellipse([orb_x - 16, orb_y - 16, orb_x + 16, orb_y + 16], fill=(16, 185, 129))
                draw.ellipse([orb_x - 8, orb_y - 8, orb_x + 8, orb_y + 8], fill=(255, 255, 255))
                
                # Dynamic timestamp box at bottom right
                draw.rectangle([self.width - 180, self.height - 40, self.width - 10, self.height - 10], fill=(0, 0, 0, 200))
                draw.text((self.width - 170, self.height - 32), f"LIVE: {ts_str}", fill=(74, 222, 128))
                
                img = np.array(pil_img)
            else:
                # Fallback simple bounding box
                img[10:90, 10:300] = [15, 23, 42]

        # Convert numpy array to VideoFrame with standard 90kHz RTP time_base
        frame = VideoFrame.from_ndarray(img, format="rgb24")
        frame.pts = pts
        frame.time_base = self.time_base
        
        # Sleep to maintain framerate pacing
        await asyncio_sleep_pacing(1.0 / self.fps)
        return frame

class SyntheticAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, bot_id=1, sample_rate=48000, tone_freq=440, mode="conversational"):
        super().__init__()
        self.bot_id = bot_id
        self.sample_rate = sample_rate
        self.tone_freq = tone_freq
        self.mode = mode  # "conversational" or "continuous"
        self.samples_per_frame = 960  # 20ms of audio at 48kHz
        self.frame_count = 0
        self.time_base = fractions.Fraction(1, self.sample_rate)
        self.start_time = time.time()
        self.enabled = True
        
        # Conversational timing parameters (offset by bot_id to create natural turn-taking)
        self.speech_duration = 3.5 + (bot_id % 3) * 0.8  # ~3.5s to 5.1s of speech
        self.pause_duration = 5.0 + ((bot_id * 7) % 5) * 1.0  # ~5s to 9s of silence
        self.cycle_period = self.speech_duration + self.pause_duration
        self.cycle_offset = (bot_id * 2.3) % self.cycle_period

    async def recv(self):
        """Generates 20ms of synthetic audio frames (continuous tone or conversational speech bursts)."""
        now = time.time()
        pts = int((now - self.start_time) * self.sample_rate)
        if pts <= self.frame_count:
            pts = self.frame_count + self.samples_per_frame
        self.frame_count = pts

        is_actively_speaking = self.enabled
        if self.enabled and self.mode == "conversational":
            elapsed = (now - self.start_time + self.cycle_offset) % self.cycle_period
            is_actively_speaking = elapsed < self.speech_duration

        if is_actively_speaking:
            # Generate 20ms of voice-like harmonic waveform (> -60dBov for SFU AudioLevelObserver)
            t = np.arange(self.frame_count, self.frame_count + self.samples_per_frame) / self.sample_rate
            # Fundamental + 2nd harmonic for richer speech-like acoustic signature
            fundamental = 3500 * np.sin(2 * np.pi * self.tone_freq * t)
            harmonic = 1200 * np.sin(2 * np.pi * (self.tone_freq * 2) * t)
            audio_data = fundamental + harmonic
            audio_ndarray = audio_data.astype(np.int16).reshape(1, self.samples_per_frame)
        else:
            # Silence / background ambient (< -60dBov)
            audio_ndarray = np.zeros((1, self.samples_per_frame), dtype=np.int16)

        # Convert to AudioFrame
        frame = AudioFrame.from_ndarray(audio_ndarray, format="s16", layout="mono")
        frame.pts = self.frame_count
        frame.sample_rate = self.sample_rate
        frame.time_base = self.time_base
        
        # Sleep to maintain framerate pacing (20ms)
        await asyncio_sleep_pacing(20 / 1000.0)
        return frame

async def asyncio_sleep_pacing(seconds):
    """Safe high-resolution sleep wrapper to prevent CPU lockups."""
    import asyncio
    await asyncio.sleep(seconds)

class MediaGenerator:
    @staticmethod
    def create_video_track(bot_id, bot_name, quality="medium", is_screen=False):
        return SyntheticVideoTrack(bot_id, bot_name, quality, is_screen=is_screen)

    @staticmethod
    def create_audio_track(bot_id=1, mode="conversational"):
        return SyntheticAudioTrack(bot_id=bot_id, mode=mode)


