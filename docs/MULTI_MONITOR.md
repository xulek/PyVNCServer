# Multi-monitor capture

PyVNCServer 3.4 adds a basic combined-desktop mode.

## Enable

```toml
[server]
capture_backend = "auto"
capture_all_monitors = true
monitor_index = 0
```

When `capture_all_monitors = true` and the backend is `auto`, PyVNCServer prefers MSS because MSS exposes monitor `0` as the Windows virtual desktop spanning all displays.

The capture layout is then reported to clients through ExtendedDesktopSize when the client advertises `-308`.

## Negative monitor coordinates

Windows can place a secondary display to the left or above the primary display, giving it negative desktop coordinates.

RFB screen coordinates are reported inside the captured framebuffer, so PyVNCServer normalizes physical coordinates against the virtual-desktop origin.

Example:

```text
Windows:
monitor A: x=-1280 y=0 1280x1024
monitor B: x=0     y=0 1920x1080

RFB virtual desktop:
monitor A: x=0    y=0 1280x1024
monitor B: x=1280 y=0 1920x1080
framebuffer: 3200x1080
```

## DXCam

The current DXCam integration captures one DXGI output per camera. Therefore:

```toml
capture_all_monitors = true
capture_backend = "dxcam"
```

does not create a combined DXGI virtual desktop. PyVNCServer logs a warning and captures one output.

Use `auto` or `mss` for combined multi-monitor capture.

## `monitor_index`

For normal single-monitor mode:

```toml
capture_all_monitors = false
monitor_index = 0
```

`monitor_index` selects the requested output/monitor according to the active backend.

When `capture_all_monitors = true`, PyVNCServer forces the MSS virtual monitor (`0`) so the capture and ExtendedDesktopSize layout describe the same framebuffer.

## Current limitation

This version reports and captures multiple monitors, but it does not change the host's physical display configuration. Pointer behavior on unusual negative-origin/mixed-DPI arrangements still depends on the underlying input backend and should be tested on the target Windows system.
