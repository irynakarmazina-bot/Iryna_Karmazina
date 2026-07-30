"""Кнопка «Оновити з Експедитора» на платформі (порт 8788).

GET /run?token=…  → синхронно: пряма синхронізація з Експедитора (швидка),
                     потім у фоні: трекінг Maersk (довгий, ~1 хв на 34 угоди).
Відповідь JSON містить "new=N" — фасад показує тост «Додано нових угод: N».

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
            out = subprocess.run([PY, SYNC], capture_output=True, timeout=600).stdout.decode()[-300:]
            note = ''
            if args.get('maersk', ['1'])[0] != '0':
                # трекінг довгий — не тримаємо браузер, віддаємо результат Експедитора одразу
                subprocess.Popen([PY, MAERSK], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                note = ' | трекінг Maersk запущено у фоні (ETA/судно оновляться за ~1 хв)'
            self._send(200, {'status': 'ok', 'result': out.strip() + note})
        except Exception as e:  # noqa: BLE001
            self._send(500, {'status': 'error', 'detail': str(e)[:100]})

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(('0.0.0.0', PORT), H) as httpd:
    httpd.serve_forever()
