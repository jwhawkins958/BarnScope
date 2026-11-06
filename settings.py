"""Validated display options and a transport-neutral future GPIO action bus."""

from collections import deque
from dataclasses import dataclass
from enum import Enum
import threading

from reticle import STYLES


@dataclass(frozen=True)
class DisplaySettings:
    zoom: int = 1
    reticle_style: str = "crosshair"
    reticle_color: str = "#f3b23f"
    reticle_brightness: int = 80
    show_compass: bool = True
    show_battery: bool = True

    @classmethod
    def from_query(cls, query):
        def one(key, default):
            return query.get(key, [default])[0]

        zoom = int(one("zoom", 1))
        style = str(one("reticleStyle", "crosshair"))
        color = str(one("reticleColor", "#f3b23f"))
        brightness = int(one("reticleBrightness", 80))
        if zoom not in (1, 2, 4) or style not in STYLES or brightness not in range(10, 101):
            raise ValueError("Invalid zoom, reticle style, or brightness")
        if len(color) != 7 or not color.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
            raise ValueError("Invalid reticle color")
        for key in ("showCompass", "showBattery"):
            if str(one(key, "true")) not in ("true", "false"):
                raise ValueError(f"Invalid {key}")
        return cls(zoom, style, color, brightness,
                   str(one("showCompass", "true")) == "true",
                   str(one("showBattery", "true")) == "true")


class Action(str, Enum):
    MENU = "MENU"
    ZOOM_1 = "ZOOM_1"
    ZOOM_2 = "ZOOM_2"
    ZOOM_4 = "ZOOM_4"
    ZOOM_IN = "ZOOM_IN"
    ZOOM_OUT = "ZOOM_OUT"
    RECORD = "RECORD"
    SNAPSHOT = "SNAPSHOT"
    FULLSCREEN = "FULLSCREEN"
    RETICLE_NEXT = "RETICLE_NEXT"
    COLOR_NEXT = "COLOR_NEXT"
    PALETTE_NEXT = "PALETTE_NEXT"
    BRIGHTNESS_UP = "BRIGHTNESS_UP"
    BRIGHTNESS_DOWN = "BRIGHTNESS_DOWN"
    COMPASS_TOGGLE = "COMPASS_TOGGLE"
    BATTERY_TOGGLE = "BATTERY_TOGGLE"


class ControlDispatcher:
    """Future GPIO callbacks call dispatch(Action); browsers poll events().

    Browser-local recording and display state stay in the viewer. GPIO input
    emits an action, not a browser click, so there is no Pi-specific UI code.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._sequence = 0
        self._events = deque(maxlen=64)

    def dispatch(self, action: Action):
        if not isinstance(action, Action):
            raise ValueError("Control action must be an Action")
        with self._lock:
            self._sequence += 1
            self._events.append({"sequence": self._sequence, "action": action.value})
            return self._sequence

    def events(self, after=0):
        if not isinstance(after, int) or after < 0:
            raise ValueError("Invalid event cursor")
        with self._lock:
            return {"latest": self._sequence, "events": [e.copy() for e in self._events if e["sequence"] > after]}
