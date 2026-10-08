#!/usr/bin/env python3
"""Click QQ's saved-account login button when its login window is visible.

Runs inside the SnowLuma container. Exit codes: 0 clicked, 3 no login window,
4 login-sized window present but the expected button is not visible.
"""

import ctypes
import os
import re
import subprocess
import sys


WIDTH = 320
HEIGHT = 460
DISPLAY = os.environ.get("DISPLAY", ":1")
WINDOW = re.compile(
    r'^\s*0x[0-9a-f]+ "QQ": \("qq" "QQ"\) '
    r'\s+(\d+)x(\d+)[+-]\d+[+-]\d+\s+\+(\d+)\+(\d+)\s*$'
)


def pixel(rgb: bytes, x: int, y: int) -> tuple[int, int, int]:
    offset = (y * WIDTH + x) * 3
    return tuple(rgb[offset : offset + 3])


def is_blue(color: tuple[int, int, int]) -> bool:
    red, green, blue = color
    return red < 100 and 90 < green < 215 and blue > 180 and blue > green + 30


def has_login_button(rgb: bytes) -> bool:
    if len(rgb) != WIDTH * HEIGHT * 3:
        raise RuntimeError("Incomplete QQ window screenshot")
    # Two solid-blue points inside the button avoid the white label in its center.
    left = pixel(rgb, 55, 328)
    right = pixel(rgb, 265, 328)
    background = pixel(rgb, 20, 280)
    return is_blue(left) and is_blue(right) and min(background) > 215


def capture(x: int, y: int) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "x11grab",
            "-video_size", f"{WIDTH}x{HEIGHT}", "-i", f"{DISPLAY}+{x},{y}",
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ],
        capture_output=True,
        timeout=12,
        check=True,
    )
    return result.stdout


def click(x: int, y: int) -> None:
    x11 = ctypes.CDLL("libX11.so.6")
    xtst = ctypes.CDLL("libXtst.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeMotionEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong
    ]
    xtst.XTestFakeButtonEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong
    ]
    display = x11.XOpenDisplay(DISPLAY.encode())
    if not display:
        raise RuntimeError(f"Cannot open X display {DISPLAY}")
    try:
        xtst.XTestFakeMotionEvent(display, -1, x, y, 0)
        xtst.XTestFakeButtonEvent(display, 1, 1, 0)
        xtst.XTestFakeButtonEvent(display, 1, 0, 0)
        x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)


def main() -> int:
    tree = subprocess.run(
        ["xwininfo", "-display", DISPLAY, "-root", "-tree"],
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    ).stdout
    windows = [tuple(map(int, match.groups())) for line in tree.splitlines()
               if (match := WINDOW.match(line))]
    if any(width >= 700 and height >= 600 for width, height, _, _ in windows):
        print("QQ main window is visible")
        return 3
    positions = [(x, y) for width, height, x, y in windows
                 if width == WIDTH and height == HEIGHT]
    if not positions:
        print("QQ saved-account login window is not visible")
        return 3
    for x, y in positions:
        if has_login_button(capture(x, y)):
            click(x + 160, y + 328)
            print(f"Clicked QQ saved-account login button at {x + 160},{y + 328}")
            return 0
    print("QQ login-sized window found, but saved-account login button is not visible")
    return 4


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"QQ login recovery error: {exc}", file=sys.stderr)
        sys.exit(2)
