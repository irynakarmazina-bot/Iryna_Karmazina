"""Кнопка «⟳ Оновити з Експедитора» на платформі (порт 8788).

GET /run    — ЗАПУСКАЄ оновлення у фоні і відповідає ОДРАЗУ.
GET /state  — стан останнього запуску: іде / завершено / помилка.

ЧОМУ ПЕРЕРОБЛЕНО (04.08.2026, користувачка: «оновлення таблиці диспетчеризації
все ще немає»). Знайдено дві причини, обидві виміряні, не припущені:

1. РОБОТА ТРИВАЄ 153 СЕКУНДИ, а відповідь чекала на її кінець.
   Заміри на сервері: Експедитор 4 с, трекінг Maersk 147 с, COSCO 2 с.
   Тобто браузер мав тримати відкритим один запит ~2,5 хвилини. Будь-який
   обрив — перехід на іншу сторінку, засинання телефона, коротка втрата
   мережі — і результат втрачався, хоча на сервері все відпрацювало.

2. СЕРВЕР БУВ ОДНОПОТОКОВИЙ (`socketserver.TCPServer`).
   Поки один запит виконувався ті самі 2,5 хвилини, УСІ інші стояли в черзі
   на прийом. Друге натискання виглядало як «кнопка не реагує». Точно та сама
   хиба вже виправлялась у cash_trigger.py 03.08.2026 — тут її не поправили.

Тепер: /run ставить роботу у фоновий потік і одразу відповідає «почав», а фасад
питає /state кожні кілька секунд і показує під кнопкою, що відбувається.
Другий клік під час роботи отримує чесне «вже виконується», а не тишу.

Копія робочого файла /root/deals_trigger.py (у репозиторії — для історії змін).
"""
import datetime
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse

TOKEN = open('/root/deals-sync-trigger-token').read().strip()
PORT = 8788
PY = '/root/unitex-finrep/.venv/bin/python'
WORKDIR = '/root/unitex-finrep'
SYNC = '/root/direct-sync/expeditor_direct_sync.py'
MAERSK = '/root/direct-sync/maersk_track_sync.py'
COSCO = '/root/direct-sync/cosco_track_sync.py'
STATE_FILE = '/root/deals_sync_state.json'

# Кроки роботи. Мітка — рядок, яким скрипт звітує про успіх.
# critical=True означає «без цього оновлення не відбулося»: трекінг перевізника
# може не відповісти, і це прикро, але таблиця все одно оновлена з Експедитора.
STEPS = [
    ('Експедитор', SYNC, 'SYNC_OK', True),
    ('Maersk', MAERSK, 'MAERSK_OK', False),
    ('COSCO', COSCO, 'COSCO_OK', False),
]

# Спільна перевірка ролі. Якщо файла немає — працюємо як раніше, з попередженням
# у лог: краще працююча кнопка, ніж мертвий сервіс.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import authcheck
except Exception:  # noqa: BLE001
    authcheck = None

_lock = threading.Lock()
_state = {'running': False, 'started': '', 'finished': '', 'ok': None,
          'result': '', 'error': '', 'steps': []}


def now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def save_state():
    """Стан на диск, щоб він пережив перезапуск сервісу."""
    try:
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)
    except Exception:  # noqa: BLE001
        pass


def load_state():
    global _state
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            s = json.load(f)
        if s.get('running'):
            # сервіс перезапустили посеред роботи — процесу вже немає,
            # тому чесно кажемо, що оновлення обірвалося, а не «іде»
            s['running'] = False
            s['ok'] = False
            s['error'] = 'Оновлення обірвалося — сервіс перезапустили. Натисни ще раз.'
            s['finished'] = now()
        _state = s
    except Exception:  # noqa: BLE001
        pass


def run_step(script, mark):
    """(успіх, рядок-звіт, пояснення проблеми, секунди)."""
    t0 = time.time()
    try:
        p = subprocess.run([PY, script], cwd=WORKDIR, capture_output=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return False, '', 'не вклався за 30 хв', round(time.time() - t0)
    out = (p.stdout or b'').decode('utf-8', 'replace')
    err = (p.stderr or b'').decode('utf-8', 'replace')
    sec = round(time.time() - t0)
    line = next((ln for ln in reversed(out.splitlines()) if ln.startswith(mark)), '')
    if 'ALREADY_RUNNING' in err:
        # це не збій: та сама робота вже йде за розкладом. Так і кажемо.
        return True, 'вже виконується за розкладом — цей запуск пропущено', '', sec
    if p.returncode != 0:
        return False, '', (err or out)[-300:].strip(), sec
    if not line:
        return False, '', ('скрипт завершився без помилки, але не підтвердив «%s». '
                           'Останнє, що він написав: %s' % (mark, (out or err)[-200:].strip())), sec
    return True, line, '', sec


def job():
    parts, steps, ok, error = [], [], True, ''
    for name, script, mark, critical in STEPS:
        good, line, why, sec = run_step(script, mark)
        steps.append({'name': name, 'sec': sec, 'ok': good,
                      'line': line, 'error': why})
        if good and line:
            parts.append(line)
        if not good and critical:
            ok, error = False, '%s: %s' % (name, why)
            break
        if not good:
            # трекінг не спрацював — оновлення відбулося, але про це треба сказати
            parts.append('трекінг %s не спрацював' % name)
    with _lock:
        _state.update({'running': False, 'finished': now(), 'ok': ok,
                       'result': ' | '.join(parts), 'error': error, 'steps': steps})
        save_state()


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, obj):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):  # noqa: N802
        q = urllib.parse.urlparse(self.path)
        args = urllib.parse.parse_qs(q.query)
        if args.get('token', [''])[0] != TOKEN:
            return self._send(403, {'error': 'forbidden'})

        # Токен вище підставляє сам Caddy, тому він нікого не відсіює. Другий
        # рубіж — ключ сесії самого користувача і його роль (див. authcheck.py).
        if authcheck is not None:
            deny = authcheck.guard(self.headers, authcheck.SYNC_ROLES, q.path)
            if deny:
                return self._send(deny[0], {'error': deny[1]})
        else:
            print('УВАГА: authcheck.py не знайдено — перевірка ролі ПРОПУЩЕНА', flush=True)

        if q.path == '/state':
            with _lock:
                return self._send(200, dict(_state))

        if q.path == '/run':
            with _lock:
                if _state.get('running'):
                    return self._send(409, {
                        'status': 'busy', 'started': _state.get('started', ''),
                        'error': 'Оновлення вже виконується — зачекай, воно триває близько '
                                 'двох з половиною хвилин. Другий раз натискати не треба.'})
                _state.update({'running': True, 'started': now(), 'finished': '',
                               'ok': None, 'result': '', 'error': '', 'steps': []})
                save_state()
            threading.Thread(target=job, daemon=True).start()
            # 202 = «прийняв, роблю». Фасад далі питає /state.
            return self._send(202, {'status': 'started', 'started': _state['started']})

        return self._send(404, {'error': 'not found'})

    def log_message(self, *a):
        pass


# ThreadingHTTPServer, а не TCPServer: однопотоковий сервер вішав УСІ запити на
# час роботи (2,5 хв), і навіть /state не проходив — виглядало як мертва кнопка.
class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


load_state()
with Server(('0.0.0.0', PORT), H) as httpd:
    httpd.serve_forever()
