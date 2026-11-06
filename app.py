#!/usr/bin/env python3
"""HTTP transport for camera frames, independent optic HUD, and control events."""

import json
import logging
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from camera import CameraProvider, PiCameraProvider
from hud import render_hud
from settings import ControlDispatcher, DisplaySettings
LOG = logging.getLogger("barnscope")
WEB_ROOT = Path(__file__).resolve().parent / "web"
STALE_SECONDS = 3


def valid_number(value, minimum, maximum):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def read_telemetry(path=None, battery_root=Path("/sys/class/power_supply")):
    """Never invent readings. Optional sensor JSON must be refreshed every 10s."""
    heading = battery = None
    if path:
        try:
            stat = path.stat()
            if -2 <= time.time() - stat.st_mtime <= 10 and stat.st_size <= 4096:
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    if valid_number(data.get("heading"), 0, 360):
                        heading = data["heading"] % 360
                    if valid_number(data.get("battery"), 0, 100):
                        battery = round(data["battery"])
        except (OSError, ValueError, TypeError):
            pass  # Missing/stale/invalid sensor readings are explicitly null.
    if battery is None:
        for supply in battery_root.glob("*"):
            try:
                if (supply / "type").read_text().strip() != "Battery":
                    continue
                value = int((supply / "capacity").read_text().strip())
                if 0 <= value <= 100:
                    battery = value
                    break
            except (OSError, ValueError):
                continue
    return heading, battery


class CameraServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 8

    def __init__(self, address, provider: CameraProvider, telemetry_file=None, controls=None):
        self.provider = provider
        self.telemetry_file = telemetry_file
        self.controls = controls or ControlDispatcher()
        self.stream_slots = threading.BoundedSemaphore(2)
        super().__init__(address, CameraHandler)

    def status(self):
        _, age = self.provider.latest()
        heading, battery = read_telemetry(self.telemetry_file)
        return {
            "camera": {
                "available": not self.provider.frames.closed_stream and age is not None and age <= STALE_SECONDS,
                "last_frame_age": age,
                "mode": self.provider.mode,
                "width": self.provider.width,
                "height": self.provider.height,
                "fps": self.provider.fps,
            },
            "heading": heading,
            "battery": battery,
            "telemetry_available": heading is not None or battery is not None,
        }


class CameraHandler(BaseHTTPRequestHandler):
    server_version = "BarnScope/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def respond(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        try:
            if path in ("/", "/index.html"):
                self.respond(200, "text/html; charset=utf-8", (WEB_ROOT / "index.html").read_bytes())
            elif path == "/api/status":
                self.respond(200, "application/json", json.dumps(self.server.status()).encode())
            elif path == "/api/controls":
                query = parse_qs(url.query)
                after = int(query.get("after", ["0"])[0])
                self.respond(200, "application/json", json.dumps(self.server.controls.events(after)).encode())
            elif path == "/hud.svg":
                query = parse_qs(url.query)
                settings = DisplaySettings.from_query(query)
                heading, battery = read_telemetry(self.server.telemetry_file)
                if query.get("recording", ["false"])[0] not in ("true", "false"):
                    raise ValueError("Invalid recording state")
                self.respond(200, "image/svg+xml", render_hud(
                    settings, heading, battery, query.get("recording", ["false"])[0] == "true",
                ))
            elif path in ("/camera/frame", "/camera/frame.jpg"):
                provider = self.server.provider
                if path.endswith(".jpg") and provider.content_type != "image/jpeg":
                    self.respond(404, "text/plain", b"JPEG only available with Pi Camera")
                    return
                frame, age = provider.latest()
                if frame is None or age is None or age > STALE_SECONDS:
                    self.respond(503, "text/plain", b"Camera feed unavailable")
                else:
                    self.respond(200, provider.content_type, frame)
            elif path == "/camera/stream.mjpg":
                if self.server.provider.content_type != "image/jpeg":
                    self.respond(501, "text/plain", b"MJPEG is only available in Pi Camera Mode")
                else:
                    self.stream()
            else:
                self.respond(404, "text/plain", b"Not found")
        except ValueError as error:
            self.respond(400, "text/plain", str(error).encode())
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except OSError:
            LOG.exception("Unable to serve %s", path)

    def stream(self):
        if not self.server.stream_slots.acquire(blocking=False):
            self.respond(503, "text/plain", b"Too many streaming clients")
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            frames = self.server.provider.frames
            while not frames.closed_stream:
                with frames.condition:
                    ready = frames.condition.wait_for(
                        lambda: frames.sequence != last or frames.closed_stream, timeout=STALE_SECONDS
                    )
                    if not ready or frames.closed_stream:
                        break
                    frame, last = frames.frame, frames.sequence
                if frame is None:
                    continue
                self.wfile.write(
                    b"--FRAME\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
                )
                self.wfile.flush()
        finally:
            self.server.stream_slots.release()

    def log_message(self, format, *args):
        LOG.debug("%s %s", self.client_address[0], format % args)


if __name__ == "__main__":
    # Compatibility with previous packages invoking python3 app.py.
    from main import main
    raise SystemExit(main())
