"""
RDP session management: Xvfb virtual display + xfreerdp connection + mouse/keyboard actions.
"""
import os
import subprocess
import time

DISPLAY = ":99"


class RDPSession:
    def __init__(self, host: str, user: str, password: str):
        self.host = host
        self.user = user
        self.password = password
        self._xvfb = None
        self._rdp = None

    def start(self):
        self._xvfb = subprocess.Popen(
            ["Xvfb", DISPLAY, "-screen", "0", "1920x1080x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

        env = {**os.environ, "DISPLAY": DISPLAY}
        self._rdp = subprocess.Popen(
            [
                "xfreerdp",
                f"/v:{self.host}",
                f"/u:{self.user}",
                f"/p:{self.password}",
                "/w:1920",
                "/h:1080",
                "/cert:ignore",
                "/log-level:OFF",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(10)  # wait for Windows desktop to appear

    def stop(self):
        if self._rdp:
            self._rdp.terminate()
            try:
                self._rdp.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._rdp.kill()
        if self._xvfb:
            self._xvfb.terminate()
            try:
                self._xvfb.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._xvfb.kill()

    def screenshot(self) -> bytes:
        """Capture screenshot of the RDP session."""
        env = {**os.environ, "DISPLAY": DISPLAY}
        tmp = "/tmp/eks_screen.png"
        # Try scrot first, fallback to ImageMagick import
        result = subprocess.run(
            ["scrot", "-z", tmp], env=env, capture_output=True
        )
        if result.returncode != 0:
            subprocess.run(
                ["import", "-display", DISPLAY, "-window", "root", tmp],
                env=env,
                check=True,
            )
        with open(tmp, "rb") as f:
            return f.read()

    def _env(self) -> dict:
        return {**os.environ, "DISPLAY": DISPLAY}

    def click(self, x: int, y: int):
        e = self._env()
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], env=e)
        subprocess.run(["xdotool", "click", "1"], env=e)
        time.sleep(0.4)

    def double_click(self, x: int, y: int):
        e = self._env()
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], env=e)
        subprocess.run(
            ["xdotool", "click", "--repeat", "2", "--delay", "100", "1"], env=e
        )
        time.sleep(0.6)

    def right_click(self, x: int, y: int):
        e = self._env()
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], env=e)
        subprocess.run(["xdotool", "click", "3"], env=e)
        time.sleep(0.3)

    def type_text(self, text: str):
        """Type text using clipboard to support Ukrainian/Unicode characters."""
        e = self._env()
        proc = subprocess.Popen(
            ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE, env=e
        )
        proc.communicate(text.encode("utf-8"))
        time.sleep(0.1)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], env=e)
        time.sleep(0.3)

    def key(self, key_name: str):
        e = self._env()
        subprocess.run(["xdotool", "key", key_name], env=e)
        time.sleep(0.2)

    def scroll(self, x: int, y: int, direction: str = "down", amount: int = 3):
        e = self._env()
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], env=e)
        button = "4" if direction == "up" else "5"
        for _ in range(amount):
            subprocess.run(["xdotool", "click", button], env=e)
            time.sleep(0.05)

    def drag(self, x1: int, y1: int, x2: int, y2: int):
        e = self._env()
        subprocess.run(["xdotool", "mousemove", str(x1), str(y1)], env=e)
        subprocess.run(["xdotool", "mousedown", "1"], env=e)
        time.sleep(0.1)
        subprocess.run(["xdotool", "mousemove", "--sync", str(x2), str(y2)], env=e)
        subprocess.run(["xdotool", "mouseup", "1"], env=e)
        time.sleep(0.3)
