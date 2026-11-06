#!/usr/bin/env python3
"""BarnScope Raspberry Pi entrypoint. Simulator Mode requires only Python."""

import argparse
import logging
import signal
from pathlib import Path

from app import CameraServer, WEB_ROOT
from camera import PiCameraProvider, SimulatorCameraProvider
from settings import ControlDispatcher
from gpio import ButtonController

LOG = logging.getLogger("barnscope")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pi", "simulator"), default="pi",
                        help="Explicit image source; never falls back to simulator on camera failure")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 for trusted LAN access")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--camera", type=int, default=0, help="Picamera2 camera index")
    parser.add_argument("--telemetry-file", type=Path, help="Optional external sensor JSON, refreshed every 10s")
    args = parser.parse_args(argv)
    if not (1 <= args.port <= 65535 and 1 <= args.fps <= 30):
        parser.error("Port must be 1–65535; fps must be 1–30")
    if not (320 <= args.width <= 1280 and 240 <= args.height <= 720 and args.width % 2 == args.height % 2 == 0):
        parser.error("Use even dimensions within 320–1280 x 240–720")
    if args.width * 9 != args.height * 16:
        parser.error("Use a 16:9 frame, such as 640x360, 960x540, or 1280x720")
    if not (WEB_ROOT / "index.html").is_file():
        parser.error("Missing web/index.html; copy the complete raspberry-pi directory")

    provider = (PiCameraProvider(args.width, args.height, args.fps, args.camera) if args.mode == "pi"
                else SimulatorCameraProvider(args.width, args.height, args.fps))
    server = None
    buttons = None
    try:
        provider.start()
        controls = ControlDispatcher()
        server = CameraServer((args.host, args.port), provider, args.telemetry_file, controls)
        # Disabled input by default. A future adapter can be injected here without
        # changing the HUD, camera, HTTP routes or shared action vocabulary.
        buttons = ButtonController(controls)
        buttons.start()
        LOG.info("%s camera ready at http://%s:%s", args.mode, args.host, args.port)
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            LOG.warning("Camera is unauthenticated. Use trusted LAN only; never forward this port.")
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        LOG.info("Stopping camera")
    except Exception:
        LOG.exception("%s camera/server failed; no substitute source will be selected", args.mode)
        return 1
    finally:
        if buttons:
            buttons.stop()
        if server:
            server.server_close()
        provider.stop()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    def stop_on_signal(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_on_signal)
    raise SystemExit(main())
