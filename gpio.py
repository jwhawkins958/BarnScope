"""Logical button abstraction only: no pins, electrical levels, or GPIO imports."""

from collections.abc import Callable, Mapping
import math
import threading
import time
from typing import Protocol

from settings import Action, ControlDispatcher

ButtonCallback = Callable[[str, bool], None]
DEFAULT_BUTTON_MAP = {action.value.lower(): action for action in Action}


class ButtonInput(Protocol):
    """Future adapters report logical names and pressed=True/False.

    The adapter owns pin numbering, active-low conversion and resource cleanup.
    start/stop are called serially by the application, never by an edge callback.
    """

    def start(self, on_edge: ButtonCallback) -> None: ...
    def stop(self) -> None: ...


class DisabledButtonInput:
    """Production default until hardware wiring is explicitly configured."""

    def start(self, on_edge: ButtonCallback) -> None:
        pass

    def stop(self) -> None:
        pass


class ButtonController:
    """Convert press edges to shared actions, with per-button debounce.

    One action per press; holding a button does not repeat. Release re-arms it.
    No polling thread, hardware access, browser dependency or sleeping is needed.
    """

    def __init__(self, dispatcher: ControlDispatcher,
                 source: ButtonInput | None = None,
                 mappings: Mapping[str, Action] | None = None,
                 debounce_seconds: float = 0.15,
                 clock: Callable[[], float] = time.monotonic):
        if not math.isfinite(debounce_seconds) or debounce_seconds < 0:
            raise ValueError("Debounce must be a finite nonnegative duration")
        self._mappings = dict(DEFAULT_BUTTON_MAP if mappings is None else mappings)
        if any(not isinstance(name, str) or not name.strip() or
               not isinstance(action, Action) for name, action in self._mappings.items()):
            raise ValueError("Button mappings require nonempty names and Action values")
        self._dispatcher = dispatcher
        self._source = source if source is not None else DisabledButtonInput()
        self._debounce = debounce_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._active = False
        self._pressed = set()
        self._last_press = {}

    def start(self) -> None:
        with self._lock:
            if self._active:
                return
            self._pressed.clear()
            self._last_press.clear()
            self._active = True
        try:
            self._source.start(self.handle_edge)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._pressed.clear()
        self._source.stop()

    def handle_edge(self, button: str, pressed: bool) -> None:
        """Accept logical edges from a future adapter or a hardware-free test."""
        if button not in self._mappings:
            raise ValueError(f"Unmapped button: {button}")
        if not isinstance(pressed, bool):
            raise ValueError("Button pressed state must be boolean")
        with self._lock:
            if not self._active:
                return
            if not pressed:
                self._pressed.discard(button)
                return
            if button in self._pressed:
                return
            now = self._clock()
            self._pressed.add(button)
            if now - self._last_press.get(button, -math.inf) < self._debounce:
                return
            self._last_press[button] = now
            self._dispatcher.dispatch(self._mappings[button])
