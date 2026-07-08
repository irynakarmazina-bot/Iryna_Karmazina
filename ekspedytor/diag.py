"""
Діагностика вводу/відображення RDP (v2):
список вікон у Xvfb, лог xfreerdp, статус процесу, фокус вікна, тести вводу.
  python -m ekspedytor.diag
"""
import hashlib
import os
import subprocess
import time

from dotenv import load_dotenv

from .debug import upload_debug
from .session import RDPSession, DISPLAY

load_dotenv()
ENV = {**os.environ, "DISPLAY": DISPLAY}


def sh(*a) -> str:
    return subprocess.run(a, env=ENV, capture_output=True, text=True).stdout.strip()


def snap(s: RDPSession, tag: str) -> str:
    d = s.screenshot()
    h = hashlib.md5(d).hexdigest()[:8]
    st = upload_debug(f"diag_{tag}.png", d)
    print(f"{tag}: md5={h} upload={st}", flush=True)
    return h


def list_windows():
    ids = sh("xdotool", "search", "--name", "").split()
    print(f"вікон знайдено: {len(ids)}", flush=True)
    for wid in ids[:15]:
        name = sh("xdotool", "getwindowname", wid)
        geo = sh("xdotool", "getwindowgeometry", wid).replace("\n", " ")
        print(f"  win {wid}: '{name}' | {geo}", flush=True)


def main():
    s = RDPSession(
        host=os.getenv("RDP_HOST", "unitex.rdport.net:31230"),
        user=os.getenv("RDP_USER", "karmazina.i"),
        password=os.environ["RDP_PASSWORD"],
    )
    try:
        print("=== xfreerdp версія ===", flush=True)
        print(subprocess.run(["xfreerdp", "--version"], capture_output=True,
                             text=True).stdout.strip()[:200], flush=True)
        s.start()
        print("=== xfreerdp процес ===", flush=True)
        print(sh("pgrep", "-af", "xfreerdp") or "НЕ ПРАЦЮЄ", flush=True)
        print("=== вікна у Xvfb ===", flush=True)
        list_windows()
        snap(s, "1_start")

        # Тест клавіатури: Windows → Пуск
        s.key("super")
        time.sleep(2)
        snap(s, "2_winkey")
        s.key("Escape")
        time.sleep(1)

        # Тест миші: подвійний клік по BAF
        s.double_click(37, 342)
        time.sleep(20)
        snap(s, "3_after_baf")

        for logf in ("/tmp/eks_rdp.log", "/tmp/eks_rdp_stdout.log"):
            print(f"=== {logf} ===", flush=True)
            try:
                print(open(logf).read()[-2000:], flush=True)
            except Exception as e:
                print("недоступний:", e, flush=True)
    finally:
        s.stop()


if __name__ == "__main__":
    main()
