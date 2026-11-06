import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from camera import CameraFrames, PiCameraProvider, SimulatorCameraProvider
from hud import render_hud
from reticle import STYLES, render_reticle
from settings import Action, ControlDispatcher, DisplaySettings


class TelemetryTests(unittest.TestCase):
    def test_no_hardware_never_returns_simulated_values(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(app.read_telemetry(battery_root=Path(root)), (None, None))

    def test_fresh_readings_and_stale_readings(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "sensors.json"
            path.write_text('{"heading": 360, "battery": 48.7}')
            self.assertEqual(app.read_telemetry(path, Path(root) / "none"), (0, 49))
            old = time.time() - 20
            os.utime(path, (old, old))
            self.assertEqual(app.read_telemetry(path, Path(root) / "none"), (None, None))

    def test_reject_invalid_sensor_values(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "sensors.json"
            for value in ['null', '[]', '{"heading": NaN, "battery": 101}', '{"heading": true, "battery": -1}', 'bad json']:
                path.write_text(value)
                self.assertEqual(app.read_telemetry(path, Path(root) / "none"), (None, None))

    def test_linux_battery(self):
        with tempfile.TemporaryDirectory() as root:
            supply = Path(root) / "BAT0"
            supply.mkdir()
            (supply / "type").write_text("Battery\n")
            (supply / "capacity").write_text("63\n")
            self.assertEqual(app.read_telemetry(battery_root=Path(root)), (None, 63))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = PiCameraProvider()
        cls.frames = cls.provider.frames
        cls.server = app.CameraServer(("127.0.0.1", 0), cls.provider)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.frames.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def test_html(self):
        with urlopen(self.url + "/") as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"<html", response.read().lower())
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_frame_and_status(self):
        jpeg = b"\xff\xd8fixture\xff\xd9"
        self.frames.write(jpeg)
        with urlopen(self.url + "/camera/frame") as response:
            self.assertEqual(response.read(), jpeg)
            self.assertEqual(response.headers["Content-Type"], "image/jpeg")
        with urlopen(self.url + "/camera/frame.jpg") as response:
            self.assertEqual(response.read(), jpeg)
        with urlopen(self.url + "/api/status") as response:
            status = json.load(response)
            self.assertTrue(status["camera"]["available"])
            self.assertEqual(status["camera"]["width"], 640)
            self.assertEqual(status["camera"]["mode"], "pi")
            self.assertIsNone(status["heading"])

    def test_missing_or_stale_frames_fail_explicitly(self):
        with self.frames.condition:
            self.frames.updated = time.monotonic() - 30
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url + "/camera/frame.jpg")
        self.assertEqual(error.exception.code, 503)
        with urlopen(self.url + "/api/status") as response:
            self.assertFalse(json.load(response)["camera"]["available"])

    def test_path_traversal_is_not_served(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url + "/../app.py")
        self.assertEqual(error.exception.code, 404)

    def test_hud_settings_validation_and_controls(self):
        with urlopen(self.url + "/hud.svg?zoom=4&reticleStyle=mil-dot&reticleColor=%23ff4b3a") as response:
            body = response.read()
            self.assertEqual(response.headers["Content-Type"], "image/svg+xml")
            self.assertIn(b"ZOOM 4X", body)
            self.assertIn(b"#ff4b3a", body)
            self.assertNotIn(b"<image", body)  # camera pixels cannot enter the HUD
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url + "/hud.svg?reticleColor=%22%3E%3Cscript%3E")
        self.assertEqual(error.exception.code, 400)
        self.server.controls.dispatch(Action.ZOOM_IN)
        with urlopen(self.url + "/api/controls?after=0") as response:
            data = json.load(response)
            self.assertEqual(data["events"], [{"sequence": 1, "action": "ZOOM_IN"}])
        with urlopen(self.url + "/api/controls?after=1") as response:
            self.assertEqual(json.load(response)["events"], [])
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url + "/api/controls?after=-1")
        self.assertEqual(error.exception.code, 400)


class ArchitectureTests(unittest.TestCase):
    def test_simulator_without_pi_hardware_and_same_hud(self):
        sim = SimulatorCameraProvider()
        sim.start()
        try:
            frame, age = sim.latest()
            self.assertIsNotNone(age)
            self.assertIn(b"<svg", frame)
            self.assertNotIn(b"CONTACT", frame)
            self.assertNotIn(b"ZOOM", frame)
            server = app.CameraServer(("127.0.0.1", 0), sim)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = "http://127.0.0.1:" + str(server.server_address[1])
                with urlopen(url + "/api/status") as response:
                    self.assertEqual(json.load(response)["camera"]["mode"], "simulator")
                with urlopen(url + "/camera/frame") as response:
                    self.assertEqual(response.headers["Content-Type"], "image/svg+xml")
                with urlopen(url + "/hud.svg") as response:
                    self.assertEqual(response.headers["Content-Type"], "image/svg+xml")
                with self.assertRaises(HTTPError) as error:
                    urlopen(url + "/camera/frame.jpg")
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
        finally:
            sim.stop()

    def test_reticles_and_live_only_telemetry(self):
        for style in STYLES:
            hud = render_hud(DisplaySettings(reticle_style=style))
            self.assertIn(render_reticle(style).encode(), hud)
            self.assertIn(b"BATT N/A", hud)
            self.assertNotIn(b"<image", hud)
        real = render_hud(DisplaySettings(), heading=72, battery=43, recording=True)
        self.assertIn(b"NE", real)
        self.assertIn(b"BATT 43%", real)
        self.assertIn(b"#ff5147", real)

    def test_reticle_magnifies_around_center_without_scaling_readouts(self):
        from xml.etree import ElementTree

        ns = "{http://www.w3.org/2000/svg}"
        for zoom in (1, 2, 4):
            for style in STYLES:
                root = ElementTree.fromstring(render_hud(
                    DisplaySettings(zoom=zoom, reticle_style=style),
                    heading=72, battery=43, recording=True,
                ))
                reticle = root[0]
                self.assertEqual(reticle.attrib["transform"],
                                 f"translate(640 360) scale({zoom}) translate(-640 -360)")
                self.assertEqual(len(reticle), 1)
                self.assertFalse(reticle.findall(f".//{ns}text"))
                self.assertTrue(any(child.text == f"ZOOM {zoom}X"
                                    for child in root.findall(f"{ns}text")))
                self.assertEqual(root[-1].attrib["cx"], "1226")
                self.assertNotIn("transform", root[-1].attrib)

    def test_control_bus_concurrency_and_replay_cursor(self):
        dispatcher = ControlDispatcher()
        with self.assertRaises(ValueError):
            dispatcher.dispatch("RECORD")
        for _ in range(66):
            dispatcher.dispatch(Action.RECORD)
        self.assertEqual(dispatcher.events(64)["events"][0]["sequence"], 65)
        self.assertEqual(len(dispatcher.events()["events"]), 64)


if __name__ == "__main__":
    unittest.main()
