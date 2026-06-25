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

    def __init__(self, bot_id, bot_name, quality="medium"):
        super().__init__()
        self.bot_id = bot_id
        self.bot_name = bot_name
        
        # Get resolution and fps from profile
        profile = QUALITY_PROFILES.get(quality, QUALITY_PROFILES["medium"])
        self.width = profile["width"]
        self.height = profile["height"]
        self.fps = profile["fps"]
        
        self.frame_count = 0
        self.time_base = fractions.Fraction(1, self.fps)
        self.start_time = time.time()

    async def recv(self):
        """
        Generates and returns a VideoFrame containing moving color bars
        with bot ID, name, quality and time overlay.
        """
        # Calculate frame pts and timestamp
        pts = int((time.time() - self.start_time) * self.fps)
        if pts <= self.frame_count:
            pts = self.frame_count + 1
        self.frame_count = pts

        # Generate base color bars (moving shift based on frame count)
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        shift = (self.frame_count * 8) % self.width

        # Draw 8 vertical bars with shifting offset
        bar_width = math.ceil(self.width / 8)
        for i in range(8):
            color = [
                255 if (i & 1) else 0,
                255 if (i & 2) else 0,
                255 if (i & 4) else 0
            ]
            x_start = (i * bar_width + shift) % self.width
            x_end = (x_start + bar_width) % self.width
            
            if x_start < x_end:
                img[:, x_start:x_end] = color
            else:
                img[:, x_start:] = color
                img[:, :x_end] = color

        # Draw simple text overlay
        ts_str = time.strftime("%H:%M:%S") + f".{(time.time() % 1) * 1000:03.0f}"
        text_lines = [
            f"BOT ID: Bot-{self.bot_id:04d}",
            f"NAME: {self.bot_name}",
            f"RESOLUTION: {self.width}x{self.height} @ {self.fps}fps",
            f"TIMESTAMP: {ts_str}",
            f"FRAME: {self.frame_count}"
        ]

        if HAS_PIL:
            # Draw text using Pillow
            pil_img = Image.fromarray(img)
            draw = ImageDraw.Draw(pil_img)
            # Use small default font or drawing boxes if custom fonts aren't available
            y_offset = 20
            for line in text_lines:
                # Simple backdrop box for readability
                draw.rectangle([10, y_offset - 2, 350, y_offset + 14], fill=(0, 0, 0, 160))
                draw.text((15, y_offset), line, fill=(255, 255, 255))
                y_offset += 20
            img = np.array(pil_img)
        else:
            # Fallback box when PIL is missing: Draw a black box in top-left
            # to signify bot is operating without Pillow dependencies
            img[10:110, 10:300] = [0, 0, 0]

        # Convert numpy array to VideoFrame
        frame = VideoFrame.from_ndarray(img, format="rgb24")
        frame.pts = self.frame_count
        frame.time_base = self.time_base
        
        # Sleep to maintain framerate pacing
        await asyncio_sleep_pacing(1.0 / self.fps)
        return frame

class SyntheticAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, sample_rate=48000, tone_freq=440):
        super().__init__()
        self.sample_rate = sample_rate
        self.tone_freq = tone_freq
        self.samples_per_frame = 960  # 20ms of audio at 48kHz
        self.frame_count = 0
        self.time_base = fractions.Fraction(1, self.sample_rate)
        self.start_time = time.time()

    async def recv(self):
        """
        Generates and returns an AudioFrame containing silence and periodic tone bursts.
        """
        pts = int((time.time() - self.start_time) * self.sample_rate)
        self.frame_count += 1
        
        # Generate sine wave samples for 20ms
        t = (np.arange(self.samples_per_frame) + self.frame_count * self.samples_per_frame) / self.sample_rate
        
        # 1-second interval: 100ms tone burst, 900ms silence
        is_tone_on = (time.time() % 1.0) < 0.1
        if is_tone_on:
            samples = np.sin(2 * np.pi * self.tone_freq * t) * 16384  # moderate volume
        else:
            samples = np.zeros(self.samples_per_frame)
            
        samples = samples.astype(np.int16)
        
        # Package into PyAV AudioFrame
        frame = AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = self.sample_rate
        frame.pts = self.frame_count * self.samples_per_frame
        frame.time_base = self.time_base
        
        # Sleep for 20ms
        await asyncio_sleep_pacing(0.02)
        return frame

async def asyncio_sleep_pacing(seconds):
    """Safe high-resolution sleep wrapper to prevent CPU lockups."""
    import asyncio
    await asyncio.sleep(seconds)

class MediaGenerator:
    @staticmethod
    def create_video_track(bot_id, bot_name, quality="medium"):
        return SyntheticVideoTrack(bot_id, bot_name, quality)

    @staticmethod
    def create_audio_track():
        return SyntheticAudioTrack()
