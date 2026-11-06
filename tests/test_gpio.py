"""Hardware-free contract and debounce tests for future button adapters."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gpio import ButtonController, DEFAULT_BUTTON_MAP
from settings import Action, ControlDispatcher


class FakeInput:
    def __init__(self):
        self.starts = self.stops = 0

    def start(self, callback):
        self.starts += 1
        self.callback = callback

    def stop(self):
        self.stops += 1


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.bus = ControlDispatcher()
        self.source = FakeInput()
        self.now = 10.0
        self.buttons = ButtonController(self.bus, self.source, clock=lambda: self.now)

    def test_default_input_is_disabled_and_lifecycle_is_idempotent(self):
        disabled = ButtonController(self.bus)
        disabled.start()
        self.assertEqual(self.bus.events()["events"], [])
        disabled.stop()
        self.buttons.start()
        self.buttons.start()
        self.assertEqual(self.source.starts, 1)
        self.buttons.stop()
        self.buttons.stop()
        self.source.callback("menu", True)
        self.assertEqual(self.source.stops, 1)
        self.assertEqual(self.bus.events()["events"], [])

    def test_press_release_hold_and_per_button_debounce(self):
        self.buttons.start()
        edge = self.source.callback
        edge("menu", True)
        self.now += 1
        edge("menu", True)  # A held button never repeats.
        edge("menu", False)
        edge("menu", True)
        edge("menu", False)
        self.now += .01
        edge("menu", True)  # Contact bounce is suppressed.
        edge("zoom_in", True)  # Other buttons remain independent.
        edge("menu", False)
        self.now += .2
        edge("menu", True)
        self.assertEqual([e["action"] for e in self.bus.events()["events"]],
                         ["MENU", "MENU", "ZOOM_IN", "MENU"])

    def test_custom_mapping_and_all_actions_supported(self):
        self.assertEqual(set(DEFAULT_BUTTON_MAP.values()), set(Action))
        buttons = ButtonController(self.bus, mappings={"primary": Action.SNAPSHOT})
        buttons.start()
        buttons.handle_edge("primary", True)
        self.assertEqual(self.bus.events()["events"][0]["action"], "SNAPSHOT")
        with self.assertRaises(ValueError):
            buttons.handle_edge("unknown", True)
        with self.assertRaises(ValueError):
            buttons.handle_edge("primary", 1)
        buttons.stop()

    def test_invalid_configuration(self):
        for duration in (-1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                ButtonController(self.bus, debounce_seconds=duration)
        with self.assertRaises(ValueError):
            ButtonController(self.bus, mappings={"menu": "MENU"})

    def test_start_failure_closes_source_and_ignores_late_edges(self):
        class BrokenInput(FakeInput):
            def start(self, callback):
                super().start(callback)
                raise RuntimeError("Adapter failed")

        source = BrokenInput()
        buttons = ButtonController(self.bus, source)
        with self.assertRaises(RuntimeError):
            buttons.start()
        self.assertEqual(source.stops, 1)
        source.callback("record", True)
        self.assertEqual(self.bus.events()["events"], [])


if __name__ == "__main__":
    unittest.main()
