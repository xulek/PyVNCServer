"""
Tests for input handler latency-related behavior.
"""

import types
import sys

from vnc_lib.input_handler import InputHandler


def test_input_handler_disables_pyautogui_delays(monkeypatch):
    fake = types.ModuleType("pyautogui")
    fake.FAILSAFE = True
    fake.PAUSE = 0.1
    fake.MINIMUM_DURATION = 0.1
    fake.MINIMUM_SLEEP = 0.05
    fake.DARWIN_CATCH_UP_TIME = 0.01

    monkeypatch.setattr(InputHandler, "_check_display", lambda self: True)
    monkeypatch.setitem(sys.modules, "pyautogui", fake)

    handler = InputHandler()

    assert handler._pyautogui is fake
    assert fake.FAILSAFE is False
    assert fake.PAUSE == 0
    assert fake.MINIMUM_DURATION == 0
    assert fake.MINIMUM_SLEEP == 0
    assert fake.DARWIN_CATCH_UP_TIME == 0


def test_pointer_move_deduplicates_same_position(monkeypatch):
    calls = {"move_to": 0}

    class FakePyAutoGUI:
        FAILSAFE = False
        PAUSE = 0
        MINIMUM_DURATION = 0
        MINIMUM_SLEEP = 0
        DARWIN_CATCH_UP_TIME = 0

        @staticmethod
        def size():
            return (1920, 1080)

        @staticmethod
        def moveTo(x, y, duration=0):
            calls["move_to"] += 1

        @staticmethod
        def mouseDown(button="left"):
            return None

        @staticmethod
        def mouseUp(button="left"):
            return None

        @staticmethod
        def scroll(amount):
            return None

    handler = InputHandler.__new__(InputHandler)
    handler.scale_factor = 1.0
    handler.logger = _dummy_logger()
    handler.prev_button_mask = 0
    handler.safe_margin = 10
    handler._screen_width = 1920
    handler._screen_height = 1080
    handler._screen_size_time = 10**9
    handler._screen_size_ttl = 5.0
    handler._last_pointer_pos = None
    handler._pyautogui = FakePyAutoGUI
    handler._pyautogui_available = True

    handler.handle_pointer_event(0, 100, 100)
    handler.handle_pointer_event(0, 100, 100)
    handler.handle_pointer_event(0, 101, 100)

    assert calls["move_to"] == 2


def _dummy_logger():
    class _Dummy:
        def debug(self, *_args, **_kwargs):
            return None

        def info(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

    return _Dummy()
