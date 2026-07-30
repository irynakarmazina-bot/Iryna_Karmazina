"""Кнопка «Оновити з Експедитора» на платформі (порт 8788).

GET /run?token=…  → синхронно ОБИДВІ роботи: пряма синхронізація з Експедитора
                     (~20 с) і трекінг Maersk (~1,5 хв). Відповідь приходить, коли
                     все готово — рішення користувачки 30.07.2026.
                     /run?...&maersk=0 — пропустити трекінг (лише Експедитор).
Відповідь JSON містить "new=N" і "MAERSK_OK tracked=… updated=…" — фасад показує
тост «додано нових угод: N · трекінг Maersk: оновлено X з Y».

Копія робочого файла /root/deals_trigger.py (у репозиторії — для історії змін).
"""
import http.server
import json
import socketserver
import subprocess
import urllib.parse

TOKEN = open('/root/deals-sync-trigger-token').read().strip()
PORT = 8788
PY = '/root/unitex-finrep/.venv/bin/python'
SYNC = '/root/direct-sync/expeditor_direct_sync.py'
MAERSK = '/root/direct-sync/maersk_track_sync.py'


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, obj):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):
        q = urllib.parse.urlparse(self.path)
        if q.path != '/run':
            return self._send(404, {'error': 'not found'})
        args = urllib.parse.parse_qs(q.query)
        if args.get('token', [''])[0] != TOKEN:
            return self._send(403, {'error': 'forbidden'})
        try:
            out = subprocess.run([PY, SYNC], capture_output=True, timeout=900).stdout.decode()[-300:]
            note = ''
            if args.get('maersk', ['1'])[0] != '0':
                mo = subprocess.run([PY, MAERSK], capture_output=True, timeout=1800).stdout.decode()
                last = [ln for ln in mo.splitlines() if ln.startswith('MAERSK_')]
                note = ' | ' + (last[-1] if last else 'трекінг Maersk: без результату')
            self._send(200, {'status': 'ok', 'result': out.strip() + note})
        except Exception as e:  # noqa: BLE001
            self._send(500, {'status': 'error', 'detail': str(e)[:100]})

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(('0.0.0.0', PORT), H) as httpd:
    httpd.serve_forever()
