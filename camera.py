"""Interchangeable image sources. This module does not import HUD or settings."""

import io
import math
import threading
import time
from typing import Protocol


class CameraFrames(io.BufferedIOBase):
    """Bounded, shared latest frame; no queue grows with connected viewers."""

    def __init__(self):
        super().__init__()
        self.condition = threading.Condition()
        self.frame = None
        self.updated = None
        self.sequence = 0
        self.closed_stream = False

    def write(self, buffer):
        with self.condition:
            self.frame = bytes(buffer)
            self.updated = time.monotonic()
            self.sequence += 1
            self.condition.notify_all()
        return len(buffer)

    def latest(self):
        with self.condition:
            age = None if self.updated is None else time.monotonic() - self.updated
            return self.frame, age

    def stop(self):
        with self.condition:
            self.closed_stream = True
            self.condition.notify_all()


class CameraProvider(Protocol):
    mode: str
    content_type: str
    width: int
    height: int
    fps: int
    frames: CameraFrames

    def start(self): ...
    def latest(self) -> tuple[bytes | None, float | None]: ...
    def stop(self): ...


class PiCameraProvider:
    mode = "pi"
    content_type = "image/jpeg"

    def __init__(self, width=640, height=360, fps=10, index=0):
        self.width, self.height, self.fps, self.index = width, height, fps, index
        self.frames = CameraFrames()
        self.camera = None
        self.recording_started = False

    def start(self):
        # Import only when the real provider is chosen. Simulator Mode runs on
        # ordinary Python without Picamera2 or camera hardware.
        from picamera2 import Picamera2
        from picamera2.encoders import MJPEGEncoder
        from picamera2.outputs import FileOutput

        self.camera = Picamera2(self.index)
        self.camera.configure(self.camera.create_video_configuration(
            main={"size": (self.width, self.height), "format": "YUV420"},
            controls={"FrameRate": self.fps}, buffer_count=4,
        ))
        self.camera.start_recording(MJPEGEncoder(bitrate=2_000_000), FileOutput(self.frames))
        self.recording_started = True
        with self.frames.condition:
            if not self.frames.condition.wait_for(lambda: self.frames.frame is not None, timeout=15):
                raise RuntimeError("No Pi Camera frames received within 15 seconds")

    def latest(self):
        return self.frames.latest()

    def stop(self):
        self.frames.stop()
        if self.camera:
            try:
                if self.recording_started:
                    self.camera.stop_recording()
            finally:
                self.camera.close()
                self.camera = None


class SimulatorCameraProvider:
    """Explicit demo source, never selected as a fallback when Pi Camera fails."""

    mode = "simulator"
    content_type = "image/svg+xml"

    def __init__(self, width=640, height=360, fps=10):
        self.width, self.height, self.fps = width, height, fps
        self.frames = CameraFrames()
        self.started_at = None
        self._lock = threading.Lock()

    def start(self):
        self.started_at = time.monotonic()
        self.latest()

    def latest(self):
        if self.started_at is None or self.frames.closed_stream:
            return None, None
        with self._lock:
            frame, age = self.frames.latest()
            if age is not None and age < 1 / self.fps:
                return frame, age
            phase = time.monotonic() - self.started_at
            w, h = self.width, self.height
            x = int(640 * (0.43 + math.sin(phase * 0.7) * 0.17))
            y = int(360 * (0.76 + math.sin(phase * 2.4) * 0.008))
            # Only scenery. No labels, bounding boxes, or simulated telemetry.
            scene = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 640 360">
<defs><linearGradient id="sky" x2="0" y2="1"><stop stop-color="#070d16"/><stop offset="1" stop-color="#293536"/></linearGradient>
<linearGradient id="ground" x2="0" y2="1"><stop stop-color="#202d2b"/><stop offset="1" stop-color="#0b1718"/></linearGradient></defs>
<path fill="url(#sky)" d="M0 0h640v240H0z"/><circle cx="145" cy="72" r="22" fill="#a6afa5" opacity=".7"/>
<path fill="#152321" d="M0 195q28-36 57 0t54-5t58-8t52 12t57-11t58 13t62-4t60 8t60-10t72 7v105H0z"/>
<path fill="url(#ground)" d="M0 227h640v133H0z"/>
<path fill="#25312d" d="M350 360L470 210h48L423 360z"/>
<path fill="#401f22" d="M422 153h154v120H422z"/><path fill="#1b2023" d="M412 156l26-34h125l27 34z"/>
<path fill="#211c1c" stroke="#b9ae88" stroke-width="3" d="M470 212h60v61h-60z"/>
<path stroke="#c8bea1" stroke-width="2" d="M470 212l60 61m0-61l-60 61"/>
<path fill="#36352c" d="M74 244h112v61H74z"/><path fill="#171e20" d="M68 244l63-27 62 27z"/>
<path stroke="#7b7462" stroke-width="3" d="M200 277l244-48m-243 57l244-48"/>
<ellipse cx="{x}" cy="{y}" rx="16" ry="7" fill="#c4ad7e"/>
<path d="M{x+9} {y-3}l10-8 2 10z" fill="#c4ad7e"/>
<path d="M{x-8} {y+4}v9m16-9v9" stroke="#c4ad7e" stroke-width="2"/>
</svg>"""
            self.frames.write(scene.encode("utf-8"))
            return self.frames.latest()

    def stop(self):
        self.frames.stop()
