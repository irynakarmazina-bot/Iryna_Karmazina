"""
Вирішальна діагностика RDP:
1) чи оновлюється віддалений екран БЕЗ нашого вводу (годинник має цокати)
2) наявність віконного менеджера
3) фокус вікна + один тест вводу
  python -m ekspedytor.diag
"""
import hashlib
import os
import shutil
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
    upload_debug(f"diag_{tag}.png", d)
    print(f"{tag}: md5={h}", flush=True)
    return h


def main():
    print("=== віконні менеджери ===", flush=True)
    for wm in ("openbox", "fluxbox", "metacity", "matchbox-window-manager",
               "icewm", "twm", "xfwm4"):
        p = shutil.which(wm)
        print(f"  {wm}: {p or '-'}", flush=True)

    s = RDPSession(
        host=os.getenv("RDP_HOST", "unitex.rdport.net:31230"),
        user=os.getenv("RDP_USER", "karmazina.i"),
        password=os.environ["RDP_PASSWORD"],
    )
    try:
        s.start()
        print("=== ПАСИВНИЙ ТЕСТ: 70 сек без вводу, чи цокає годинник ===", flush=True)
        a = snap(s, "passive_t0")
        time.sleep(35)
        b = snap(s, "passive_t35")
        time.sleep(35)
        c = snap(s, "passive_t70")
        print(f"екран живий (кадри різні)? {'ТАК' if len({a,b,c}) > 1 else 'НІ — заморожений'}",
              flush=True)

        print("=== фокус ===", flush=True)
        print("focused window:", sh("xdotool", "getwindowfocus"), flush=True)

        print("=== хвіст логу xfreerdp ===", flush=True)
        try:
            print(open("/tmp/eks_rdp.log").read()[-1500:], flush=True)
        except Exception as e:
            print("недоступний:", e, flush=True)
    finally:
        s.stop()


if __name__ == "__main__":
    main()
