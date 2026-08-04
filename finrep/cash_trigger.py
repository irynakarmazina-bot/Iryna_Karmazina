#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тригер для залишків грошей. Порт 8791.

/refresh — оновити залишки з Експедитора і перебудувати фінзвіт
           (спершу синхронно рахуємо каси в normalized/cash_balances.csv,
            потім у фоні запускаємо звичайний run.sh — так звіт бачить свіжу касу).
/sheet   — ОКРЕМО ПО ЗАПИТУ: порахувати і вивантажити залишки в Google-таблицю
           (аркуш «Імпорт_Залишки»). Працює синхронно й повертає підсумок.

Токен той самий, що в фінзвітного тригера: /root/unitex-finrep/secure/trigger_token
Ключі Google тут не зберігаються — запис у таблицю йде через n8n-проксі.
"""
import contextlib
import errno
import fcntl
import http.server
import json
import os
import socketserver
import subprocess
import sys
import urllib.parse

PORT = 8791
TOKEN = open("/root/unitex-finrep/secure/trigger_token").read().strip()
PY = "/root/unitex-finrep/.venv/bin/python"
SCRIPT = "/root/unitex-finrep/engine/cash_from_odata.py"
LOCALCOSTS = "/root/unitex-finrep/engine/local_costs.py"
WORKDIR = "/root/unitex-finrep"
RUN_QUEUED = "/root/unitex-finrep/run_queued.sh"
LOCK_DIR = os.environ.get("RUNLOCK_DIR", "/var/lock")

# Спільна перевірка «хто це і чи можна йому» — server/authcheck.py, копія лежить
# поруч із цим файлом на сервері (/root/authcheck.py). Якщо її раптом немає —
# сервіс має піднятись і працювати, лише без перевірки ролі (з попередженням).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import authcheck
except Exception:  # noqa: BLE001
    authcheck = None


class Busy(Exception):
    """Таке саме завдання вже виконується."""


@contextlib.contextmanager
def only_one(name):
    """Замок «це завдання виконується лише в одному екземплярі».

    Навіщо (рішення користувачки 03.08.2026): кнопки «⟳ Підтягнути свіжі дані» і
    «⟳ Перерахувати з Експедитора» раніше запускали розрахунок на КОЖНЕ натискання.
    Подвійний клік або клік під час нічного перерахунку = два процеси пишуть в одні
    й ті самі файли (normalized/*, computed/*), і звіт може прочитати наполовину
    перезаписані дані. Тепер друге натискання отримує чесне «вже виконується».
    """
    path = os.path.join(LOCK_DIR, "unitex-%s.lock" % name)
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    fh = open(path, "w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(name)
        fh.write("%d\n" % os.getpid())
        fh.flush()
        yield
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def run(args, timeout, script=None):
    p = subprocess.run([PY, script or SCRIPT] + args, cwd=WORKDIR, capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):  # noqa: N802
        q = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(q.query)
        if params.get("token", [""])[0] != TOKEN:
            return self._send(403, {"error": "forbidden"})

        # ДРУГИЙ РУБІЖ (03.08.2026): токен вище підставляє сам Caddy, тому він
        # нікого не відсіює — досить знати адресу сайту, входити не треба.
        # Тому додатково перевіряємо САМОГО користувача: його ключ сесії і роль.
        # Якщо authcheck поруч немає — не падаємо, а працюємо як раніше і кажемо
        # про це в лог: краще працюючі кнопки, ніж мертвий сервіс.
        if authcheck is not None:
            # guard() сам вирішує, блокувати чи лише записати в журнал —
            # залежно від authcheck.ENFORCE. Зараз режим попереджувальний.
            deny = authcheck.guard(self.headers, authcheck.FIN_ROLES, q.path)
            if deny:
                return self._send(deny[0], {"error": deny[1]})
        else:
            print("УВАГА: authcheck.py не знайдено — перевірка ролі ПРОПУЩЕНА", flush=True)

        try:
            if q.path == "/refresh":
                with only_one("cash"):
                    try:
                        rc, out = run(["--csv"], 600)
                    except subprocess.TimeoutExpired:
                        return self._send(504, {"error": "Експедитор не відповів за 10 хв"})
                    if rc != 0:
                        return self._send(500, {"error": "не вдалося порахувати каси", "log": out[-1200:]})
                # Перебудова звіту йде ЧЕРЕЗ ЧЕРГУ (finrep/run_queued.sh): один
                # перерахунок виконується, максимум один чекає, зайві натискання
                # відсіюються. Раніше кожен клік стартував ще один run.sh поверх
                # попереднього — і вони писали в одні й ті самі файли.
                subprocess.Popen(["/bin/bash", RUN_QUEUED])
                line = [x for x in out.splitlines() if x.startswith("CASH_OK")]
                return self._send(200, {"status": "started", "cash": line[0] if line else "", "log": out[-1500:]})

            # локальні витрати за кордоном — перерахунок за кнопкою в «Бух. обліку»
            if q.path == "/localcosts":
                with only_one("localcosts"):
                    try:
                        rc, out = run([], 600, LOCALCOSTS)
                    except subprocess.TimeoutExpired:
                        return self._send(504, {"error": "Експедитор не відповів за 10 хв"})
                    if rc != 0:
                        return self._send(500, {"error": "не вдалося порахувати", "log": out[-1200:]})
                    return self._send(200, {"status": "ok", "log": out[-1500:]})

            if q.path == "/sheet":
                with only_one("cash"):
                    try:
                        rc, out = run(["--csv", "--sheet"], 600)
                    except subprocess.TimeoutExpired:
                        return self._send(504, {"error": "не вклалися за 10 хв"})
                    if rc != 0:
                        return self._send(500, {"error": "не вдалося вивантажити", "log": out[-1200:]})
                    line = [x for x in out.splitlines() if x.startswith("CASH_OK")]
                    return self._send(200, {"status": "ok", "cash": line[0] if line else "", "log": out[-1500:]})
        except Busy as b:
            # 409 = «конфлікт»: не помилка, а «зачекай, це вже рахується»
            return self._send(409, {"status": "busy", "task": str(b),
                                    "error": "Це вже виконується — зачекай, поки завершиться, "
                                             "і онови сторінку. Другий раз запускати не треба."})

        return self._send(404, {"error": "not found"})

    def log_message(self, *a):  # тихо
        pass


# ThreadingTCPServer, а не TCPServer: сервер однопотоковий вішав УСІ запити на час
# розрахунку (до 10 хв), і навіть швидка перевірка стану не проходила — виглядало
# як «платформа зависла». Від паралельних розрахунків захищають замки вище, а не
# однопотоковість. daemon_threads — щоб перезапуск сервісу не чекав на робочі потоки.
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


with Server(("127.0.0.1", PORT), H) as httpd:
    httpd.serve_forever()
