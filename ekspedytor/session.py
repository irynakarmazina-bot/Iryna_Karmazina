"""
RDP session management: Xvfb virtual display + xfreerdp connection + human-like actions.
All delays and movements are randomized to mimic natural human behavior.
"""
import os
import random
import subprocess
import time


DISPLAY = ":99"

# Human-like timing ranges (seconds)
CLICK_DELAY    = (0.3, 0.8)    # pause after a click
TYPE_DELAY     = (0.06, 0.18)  # delay between characters
ACTION_DELAY   = (0.8, 2.0)    # pause between major actions
MOUSE_STEPS    = 12            # steps for smooth mouse movement


def _pause(lo: float, hi: float):
    """Sleep for a random duration in [lo, hi] seconds."""
    time.sleep(random.uniform(lo, hi))


def _human_delay():
    """Natural pause between actions."""
    _pause(*ACTION_DELAY)


class RDPSession:
    def __init__(self, host: str, user: str, password: str):
        self.host = host
        self.user = user
        self.password = password
        self._xvfb = None
        self._rdp = None

    def start(self):
        # Clean up any leftover Xvfb process and lock file from previous runs
        subprocess.run(["pkill", "-f", f"Xvfb {DISPLAY}"], capture_output=True)
        time.sleep(1)
        lock = f"/tmp/.X{DISPLAY.lstrip(':')}-lock"
        if os.path.exists(lock):
            os.remove(lock)
        sock = f"/tmp/.X11-unix/X{DISPLAY.lstrip(':')}"
        if os.path.exists(sock):
            os.remove(sock)

        self._xvfb = subprocess.Popen(
            ["Xvfb", DISPLAY, "-screen", "0", "1920x1080x24", "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)

        # Віконний менеджер — щоб вікно xfreerdp було «видимим» і сервер
        # не вимикав оновлення екрана (Suppress Output), + коректний фокус.
        wm_env = {**os.environ, "DISPLAY": DISPLAY}
        self._wm = subprocess.Popen(
            ["openbox"], env=wm_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

        env = {
            **os.environ,
            "DISPLAY": DISPLAY,
            # WLOG у файл — щоб бачити перебіг зʼєднання xfreerdp
            "WLOG_APPENDER": "FILE",
            "WLOG_LEVEL": "INFO",
            "WLOG_FILEAPPENDER_OUTPUT_FILE_PATH": "/tmp",
            "WLOG_FILEAPPENDER_OUTPUT_FILE_NAME": "eks_rdp.log",
        }
        self._rdplog = open("/tmp/eks_rdp_stdout.log", "w")
        self._rdp = subprocess.Popen(
            [
                "xfreerdp",
                f"/v:{self.host}",
                f"/u:{self.user}",
                f"/p:{self.password}",
                "/w:1920", "/h:1080",
                "/bpp:24",
                "/gdi:sw",               # програмний GDI — рендер у зчитуваний буфер
                "-grab-keyboard",        # не захоплювати клавіатуру монопольно
                "-themes",
                "-wallpaper",
                "/cert:ignore",
                "/log-level:INFO",
            ],
            env=env,
            stdout=self._rdplog,
            stderr=subprocess.STDOUT,
        )
        # Wait for NLA auth + Windows desktop to fully render
        time.sleep(30)
        # Дати вікну xfreerdp фокус (без WM ввід інакше не доходить)
        self._focus_rdp_window(env)
        subprocess.run(["xdotool", "mousemove", "960", "540"], env=env, capture_output=True)
        time.sleep(3)

    def _focus_rdp_window(self, env):
        """Знайти вікно xfreerdp і активувати його, щоб приймало ввід."""
        try:
            out = subprocess.run(
                ["xdotool", "search", "--name", "FreeRDP"],
                env=env, capture_output=True, text=True,
            ).stdout.split()
            if not out:
                out = subprocess.run(
                    ["xdotool", "search", "--name", self.host.split(":")[0]],
                    env=env, capture_output=True, text=True,
                ).stdout.split()
            if out:
                wid = out[0]
                subprocess.run(["xdotool", "windowactivate", "--sync", wid],
                               env=env, capture_output=True)
                subprocess.run(["xdotool", "windowfocus", wid],
                               env=env, capture_output=True)
        except Exception:
            pass

    def stop(self):
        for proc in (self._rdp, getattr(self, "_wm", None), self._xvfb):
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if getattr(self, "_rdplog", None):
            try:
                self._rdplog.close()
            except Exception:
                pass

    # ── Screenshots ──────────────────────────────────────────────────────────

    def screenshot(self) -> bytes:
        """Capture the current RDP screen. Retries if screen appears black."""
        env = {**os.environ, "DISPLAY": DISPLAY}
        tmp = "/tmp/eks_screen.png"

        for attempt in range(3):
            result = subprocess.run(["scrot", "-z", tmp], env=env, capture_output=True)
            if result.returncode != 0:
                subprocess.run(
                    ["import", "-display", DISPLAY, "-window", "root", tmp],
                    env=env, capture_output=True,
                )
            if not os.path.exists(tmp):
                time.sleep(2)
                continue

            data = open(tmp, "rb").read()
            if len(data) > 5000:  # non-trivial image (black screen is ~1-3KB)
                return data

            # Screen looks black — wake up and wait
            subprocess.run(["xdotool", "mousemove", "960", "540"], env=env, capture_output=True)
            subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True)
            time.sleep(5)

        return data  # return whatever we have after retries

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def _move_smooth(self, x: int, y: int):
        """Move mouse along a natural curved path (not instant teleport)."""
        e = {**os.environ, "DISPLAY": DISPLAY}
        # Get current position
        result = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            env=e, capture_output=True, text=True,
        )
        cx, cy = 960, 540  # fallback to center
        for line in result.stdout.splitlines():
            if line.startswith("X="):
                cx = int(line.split("=")[1])
            elif line.startswith("Y="):
                cy = int(line.split("=")[1])

        # Move in small steps with slight random wobble (Bezier-like)
        for i in range(1, MOUSE_STEPS + 1):
            t = i / MOUSE_STEPS
            # Ease-in-out curve
            t_ease = t * t * (3 - 2 * t)
            mx = int(cx + (x - cx) * t_ease + random.randint(-2, 2))
            my = int(cy + (y - cy) * t_ease + random.randint(-2, 2))
            subprocess.run(
                ["xdotool", "mousemove", str(mx), str(my)],
                env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(random.uniform(0.008, 0.025))

        # Final exact position
        subprocess.run(["xdotool", "mousemove", str(x), str(y)], env=e)

    def click(self, x: int, y: int):
        e = {**os.environ, "DISPLAY": DISPLAY}
        self._move_smooth(x, y)
        _pause(0.05, 0.15)  # tiny pause before click (human reaction)
        subprocess.run(["xdotool", "click", "1"], env=e)
        _pause(*CLICK_DELAY)

    def double_click(self, x: int, y: int):
        e = {**os.environ, "DISPLAY": DISPLAY}
        self._move_smooth(x, y)
        _pause(0.05, 0.12)
        subprocess.run(
            ["xdotool", "click", "--repeat", "2", "--delay", "120", "1"], env=e
        )
        _pause(*CLICK_DELAY)

    def right_click(self, x: int, y: int):
        e = {**os.environ, "DISPLAY": DISPLAY}
        self._move_smooth(x, y)
        _pause(0.05, 0.12)
        subprocess.run(["xdotool", "click", "3"], env=e)
        _pause(*CLICK_DELAY)

    def drag(self, x1: int, y1: int, x2: int, y2: int):
        e = {**os.environ, "DISPLAY": DISPLAY}
        self._move_smooth(x1, y1)
        _pause(0.1, 0.2)
        subprocess.run(["xdotool", "mousedown", "1"], env=e)
        time.sleep(0.15)
        self._move_smooth(x2, y2)
        subprocess.run(["xdotool", "mouseup", "1"], env=e)
        _pause(*CLICK_DELAY)

    def scroll(self, x: int, y: int, direction: str = "down", amount: int = 3):
        e = {**os.environ, "DISPLAY": DISPLAY}
        self._move_smooth(x, y)
        button = "4" if direction == "up" else "5"
        for _ in range(amount):
            subprocess.run(["xdotool", "click", button], env=e)
            time.sleep(random.uniform(0.08, 0.18))

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def type_text(self, text: str):
        """
        Type text using clipboard paste for Unicode (Ukrainian) support.
        Splits long texts to simulate natural pasting behavior.
        """
        e = {**os.environ, "DISPLAY": DISPLAY}
        proc = subprocess.Popen(
            ["xclip", "-selection", "clipboard"],
            stdin=subprocess.PIPE, env=e,
        )
        proc.communicate(text.encode("utf-8"))
        _pause(0.05, 0.1)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], env=e)
        # Simulate reading time after typing
        _pause(0.2, 0.5)

    def key(self, key_name: str):
        e = {**os.environ, "DISPLAY": DISPLAY}
        _pause(0.05, 0.15)
        subprocess.run(["xdotool", "key", key_name], env=e)
        _pause(0.2, 0.5)
