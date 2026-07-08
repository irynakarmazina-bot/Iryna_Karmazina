"""
Діагностика вводу/відображення RDP:
чи реагує віддалений робочий стіл на клавіатуру/мишу і чи оновлюється картинка.
Робить серію знімків з контролем md5 і викладає їх у _debug/.
  python -m ekspedytor.diag
"""
import hashlib
import os
import time

from dotenv import load_dotenv

from .debug import upload_debug
from .session import RDPSession

load_dotenv()


def snap(s: RDPSession, tag: str) -> str:
    data = s.screenshot()
    h = hashlib.md5(data).hexdigest()[:8]
    st = upload_debug(f"diag_{tag}.png", data)
    print(f"{tag}: {len(data)}b md5={h} upload={st}", flush=True)
    return h


def main():
    s = RDPSession(
        host=os.getenv("RDP_HOST", "unitex.rdport.net:31230"),
        user=os.getenv("RDP_USER", "karmazina.i"),
        password=os.environ["RDP_PASSWORD"],
    )
    try:
        s.start()
        snap(s, "1_desktop")

        # 1) Перевірка вводу з КЛАВІАТУРИ: клавіша Windows має відкрити «Пуск»
        s.key("super")
        time.sleep(2)
        snap(s, "2_after_winkey")
        s.key("Escape")
        time.sleep(1)

        # 2) Перевірка вводу МИШІ: подвійний клік по іконці BAF (запуск 1С)
        s.double_click(37, 342)
        snap(s, "3_after_dblclick")
        time.sleep(15)
        snap(s, "4_wait15")
        time.sleep(20)
        snap(s, "5_wait35")
        time.sleep(20)
        snap(s, "6_wait55")

        # 3) Контроль позиції миші (чи xdotool взагалі рухає курсор)
        import subprocess
        env = {**os.environ, "DISPLAY": ":99"}
        r = subprocess.run(["xdotool", "getmouselocation"], env=env,
                           capture_output=True, text=True)
        print("mouse:", r.stdout.strip(), flush=True)
    finally:
        s.stop()


if __name__ == "__main__":
    main()
