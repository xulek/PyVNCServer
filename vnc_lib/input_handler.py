"""
Input Handler for VNC Server
Handles keyboard and mouse events with proper state tracking
"""

import logging
import os
from typing import Dict, Optional


class InputHandler:
    """Handles keyboard and mouse input events from VNC clients"""

    # Mouse button bits (RFC 6143 Section 7.5.5)
    BUTTON_LEFT = 1 << 0
    BUTTON_MIDDLE = 1 << 1
    BUTTON_RIGHT = 1 << 2
    BUTTON_SCROLL_UP = 1 << 3
    BUTTON_SCROLL_DOWN = 1 << 4

    def __init__(self, scale_factor: float = 1.0):
        """
        Initialize input handler

        Args:
            scale_factor: Scale factor for coordinate translation
        """
        self.scale_factor = scale_factor
        self.logger = logging.getLogger(__name__)

        # Track previous button state to detect press/release
        self.prev_button_mask = 0

        # Mouse safety margin (prevent clicks near screen edges)
        self.safe_margin = 10

        # Lazy load pyautogui (only when needed and display is available)
        self._pyautogui = None
        self._pyautogui_available = self._check_display()

        if self._pyautogui_available:
            try:
                import pyautogui
                self._pyautogui = pyautogui
                # Disable pyautogui fail-safe
                pyautogui.FAILSAFE = False
            except Exception as e:
                self.logger.warning(f"pyautogui not available: {e}")
                self._pyautogui_available = False

        self.logger.info("InputHandler initialized")

    def _check_display(self) -> bool:
        """Check if DISPLAY environment variable is set (for Linux/X11)"""
        return 'DISPLAY' in os.environ or os.name != 'posix'

    def _ensure_pyautogui(self):
        """Ensure pyautogui is available, raise error if not"""
        if not self._pyautogui_available or self._pyautogui is None:
            raise RuntimeError(
                "pyautogui is not available. This likely means:\n"
                "1. DISPLAY environment variable is not set (headless environment)\n"
                "2. pyautogui failed to import\n"
                "InputHandler requires a graphical environment to function."
            )

    def handle_pointer_event(self, button_mask: int, x: int, y: int):
        """
        Handle pointer (mouse) event

        Per RFC 6143 Section 7.5.5:
        - button_mask indicates which buttons are currently pressed
        - x, y are pointer coordinates

        This method properly tracks button state changes.
        """
        try:
            self._ensure_pyautogui()

            # Translate coordinates according to scale factor
            actual_x = int(x / self.scale_factor)
            actual_y = int(y / self.scale_factor)

            # Get screen dimensions
            screen_width, screen_height = self._pyautogui.size()

            # Safety check - don't move cursor near edges
            if (actual_x < self.safe_margin or
                actual_x > screen_width - self.safe_margin or
                actual_y < self.safe_margin or
                actual_y > screen_height - self.safe_margin):
                self.logger.debug(f"Pointer event near edge ignored: ({actual_x}, {actual_y})")
                return

            # Move mouse to position
            self._pyautogui.moveTo(actual_x, actual_y, duration=0)

            # Handle button state changes
            self._handle_button_changes(button_mask)

            # Update previous state
            self.prev_button_mask = button_mask

        except Exception as e:
            self.logger.error(f"Error handling pointer event: {e}")

    def _handle_button_changes(self, button_mask: int):
        """
        Handle mouse button state changes

        Compares current button_mask with previous state to detect
        which buttons were pressed or released.
        """
        # Check each button
        self._handle_button(self.BUTTON_LEFT, button_mask, 'left')
        self._handle_button(self.BUTTON_MIDDLE, button_mask, 'middle')
        self._handle_button(self.BUTTON_RIGHT, button_mask, 'right')

        # Handle scroll events
        if button_mask & self.BUTTON_SCROLL_UP and not (self.prev_button_mask & self.BUTTON_SCROLL_UP):
            self._pyautogui.scroll(1)
            self.logger.debug("Scroll up")

        if button_mask & self.BUTTON_SCROLL_DOWN and not (self.prev_button_mask & self.BUTTON_SCROLL_DOWN):
            self._pyautogui.scroll(-1)
            self.logger.debug("Scroll down")

    def _handle_button(self, button_bit: int, button_mask: int, button_name: str):
        """Handle a single button press/release"""
        is_pressed = bool(button_mask & button_bit)
        was_pressed = bool(self.prev_button_mask & button_bit)

        if is_pressed and not was_pressed:
            # Button pressed
            self._pyautogui.mouseDown(button=button_name)
            self.logger.debug(f"Mouse {button_name} down")
        elif not is_pressed and was_pressed:
            # Button released
            self._pyautogui.mouseUp(button=button_name)
            self.logger.debug(f"Mouse {button_name} up")

    def handle_key_event(self, down_flag: int, key: int):
        """
        Handle keyboard event

        Per RFC 6143 Section 7.5.4:
        - down_flag: 1 if key pressed, 0 if released
        - key: X11 keysym value

        Note: This implementation provides basic key support.
        Full X11 keysym mapping would be more extensive.
        """
        try:
            self._ensure_pyautogui()

            # Convert X11 keysym to pyautogui key name
            key_name = self._keysym_to_key(key)

            if key_name:
                if down_flag:
                    self._pyautogui.keyDown(key_name)
                    self.logger.debug(f"Key down: {key_name} (keysym: 0x{key:08x})")
                else:
                    self._pyautogui.keyUp(key_name)
                    self.logger.debug(f"Key up: {key_name} (keysym: 0x{key:08x})")
            else:
                self.logger.debug(f"Unmapped keysym: 0x{key:08x}")

        except Exception as e:
            self.logger.error(f"Error handling key event: {e}")

    def _keysym_to_key(self, keysym: int) -> Optional[str]:
        """
        Convert X11 keysym to pyautogui key name

        This is a basic mapping. A complete implementation would
        include the full X11 keysym table.
        """
        # ASCII printable characters (0x0020-0x007E)
        if 0x0020 <= keysym <= 0x007E:
            return chr(keysym)

        # Common special keys
        keysym_map = {
            0xFF08: 'backspace',
            0xFF09: 'tab',
            0xFF0D: 'enter',
            0xFF1B: 'esc',
            0xFF50: 'home',
            0xFF51: 'left',
            0xFF52: 'up',
            0xFF53: 'right',
            0xFF54: 'down',
            0xFF55: 'pageup',
            0xFF56: 'pagedown',
            0xFF57: 'end',
            0xFF63: 'insert',
            0xFFFF: 'delete',

            # Function keys
            0xFFBE: 'f1',
            0xFFBF: 'f2',
            0xFFC0: 'f3',
            0xFFC1: 'f4',
            0xFFC2: 'f5',
            0xFFC3: 'f6',
            0xFFC4: 'f7',
            0xFFC5: 'f8',
            0xFFC6: 'f9',
            0xFFC7: 'f10',
            0xFFC8: 'f11',
            0xFFC9: 'f12',

            # Modifiers
            0xFFE1: 'shift',
            0xFFE2: 'shift',  # Right shift
            0xFFE3: 'ctrl',
            0xFFE4: 'ctrl',   # Right ctrl
            0xFFE9: 'alt',
            0xFFEA: 'alt',    # Right alt
            0xFFEB: 'win',    # Super/Windows key
            0xFFEC: 'win',    # Right super

            # Numpad
            0xFFAA: 'multiply',
            0xFFAB: 'add',
            0xFFAD: 'subtract',
            0xFFAE: 'decimal',
            0xFFAF: 'divide',
        }

        return keysym_map.get(keysym)
