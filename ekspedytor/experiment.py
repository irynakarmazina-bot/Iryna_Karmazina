"""
Експеримент: чи почне віддалений екран оновлюватись за іншого RDP-кодека.
Піднімає Xvfb один раз, по черзі підключається xfreerdp з різними наборами
опцій, робить 2 знімки з інтервалом 35 сек і дивиться, чи кадр змінюється.
  python -m ekspedytor.experiment
"""
import hashlib
import os
import subprocess
import time

from dotenv import load_dotenv

from .debug import upload_debug

load_dotenv()
DISPLAY = ":99"
ENV = {**os.environ, "DISPLAY": DISPLAY}
HOST = os.getenv("RDP_HOST", "unitex.rdport.net:31230")
USER = os.getenv("RDP_USER", "karmazina.i")
PW = os.environ["RDP_PASSWORD"]


def start_xvfb():
    subprocess.run(["pkill", "-f", "Xvfb :99"], capture_output=True)
    time.sleep(1)
    for f in ("/tmp/.X99-lock", "/tmp/.X11-unix/X99"):
        try:
            os.remove(f)
        except OSError:
            pass
    subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1920x1080x24", "-ac"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)


def snap():
    subprocess.run(["scrot", "-z", "/tmp/e.png"], env=ENV, capture_output=True)
    d = open("/tmp/e.png", "rb").read()
    return hashlib.md5(d).hexdigest()[:8], d


def try_variant(name, extra):
    subprocess.run(["pkill", "-f", "xfreerdp"], capture_output=True)
    time.sleep(2)
    base = ["xfreerdp", f"/v:{HOST}", f"/u:{USER}", f"/p:{PW}",
            "/w:1920", "/h:1080", "/cert:ignore", "/log-level:ERROR",
            "-wallpaper", "-themes"]
    p = subprocess.Popen(base + extra, env=ENV,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(40)
    subprocess.run(["xdotool", "mousemove", "500", "500"], env=ENV, capture_output=True)
    h1, d1 = snap()
    time.sleep(35)
    h2, _ = snap()
    alive = p.poll() is None
    upload_debug(f"exp_{name}.png", d1)
    print(f"[{name}] опції={' '.join(extra)} | alive={alive} "
          f"t0={h1} t35={h2} => {'ОНОВЛЮЄТЬСЯ!' if h1 != h2 else 'заморожено'}",
          flush=True)
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()


def main():
    start_xvfb()
    variants = {
        "base":    ["/gdi:sw"],
        "rfx":     ["/gdi:sw", "/rfx"],
        "gfx":     ["/gdi:hw", "/gfx"],
        "nocache": ["/gdi:sw", "-bitmap-cache", "-offscreen-cache", "/relax-order-checks"],
    }
    for n, ex in variants.items():
        try:
            try_variant(n, ex)
        except Exception as e:
            print(f"[{n}] ПОМИЛКА {e}", flush=True)
    subprocess.run(["pkill", "-f", "Xvfb :99"], capture_output=True)
    print("ГОТОВО", flush=True)


if __name__ == "__main__":
    main()
