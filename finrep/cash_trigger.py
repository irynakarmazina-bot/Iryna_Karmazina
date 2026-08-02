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
import http.server
import json
import socketserver
import subprocess
import urllib.parse

PORT = 8791
TOKEN = open("/root/unitex-finrep/secure/trigger_token").read().strip()
PY = "/root/unitex-finrep/.venv/bin/python"
SCRIPT = "/root/unitex-finrep/engine/cash_from_odata.py"
LOCALCOSTS = "/root/unitex-finrep/engine/local_costs.py"
WORKDIR = "/root/unitex-finrep"


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

        if q.path == "/refresh":
            try:
                rc, out = run(["--csv"], 600)
            except subprocess.TimeoutExpired:
                return self._send(504, {"error": "Експедитор не відповів за 10 хв"})
            if rc != 0:
                return self._send(500, {"error": "не вдалося порахувати каси", "log": out[-1200:]})
            subprocess.Popen(["/bin/bash", "/root/unitex-finrep/run.sh"])
            line = [x for x in out.splitlines() if x.startswith("CASH_OK")]
            return self._send(200, {"status": "started", "cash": line[0] if line else "", "log": out[-1500:]})

        # локальні витрати за кордоном — перерахунок за кнопкою в «Бух. обліку»
        if q.path == "/localcosts":
            try:
                rc, out = run([], 600, LOCALCOSTS)
            except subprocess.TimeoutExpired:
                return self._send(504, {"error": "Експедитор не відповів за 10 хв"})
            if rc != 0:
                return self._send(500, {"error": "не вдалося порахувати", "log": out[-1200:]})
            return self._send(200, {"status": "ok", "log": out[-1500:]})

        if q.path == "/sheet":
            try:
                rc, out = run(["--csv", "--sheet"], 600)
            except subprocess.TimeoutExpired:
                return self._send(504, {"error": "не вклалися за 10 хв"})
            if rc != 0:
                return self._send(500, {"error": "не вдалося вивантажити", "log": out[-1200:]})
            line = [x for x in out.splitlines() if x.startswith("CASH_OK")]
            return self._send(200, {"status": "ok", "cash": line[0] if line else "", "log": out[-1500:]})

        return self._send(404, {"error": "not found"})

    def log_message(self, *a):  # тихо
        pass


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), H) as httpd:
    httpd.serve_forever()
