#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кабінет клієнта: вхід за паролем і фільтрація ДАНИХ НА СЕРВЕРІ.

ЧИМ ЦЕ ВІДРІЗНЯЄТЬСЯ ВІД ПРОТОТИПУ. `client_cabinet/build_preview.py` збирає
СТАТИЧНИЙ файл на одного клієнта: хто знає адресу — той бачить сторінку, входу
немає. Тут навпаки: сторінки на диску немає взагалі, вона збирається на кожен
запит уже ПІСЛЯ того, як сервер упізнав, хто прийшов, і бере лише угоди його
компанії. Браузер клієнта не отримує ні токена NocoDB, ні чужих рядків — не
«не показує», а фізично не отримує.

ЗВІДКИ ВИГЛЯД. Розмітка й стилі — той самий `TPL` з build_preview.py, тобто
узгоджений з користувачкою макет (схема руху вантажу, плитки-відбори, палітра
ЕРП). Тут він НЕ дублюється: файл імпортується, і правка вигляду в одному місці
міняє і прототип, і бойовий кабінет. Розходження двох копій — саме те, через що
02.08.2026 з платформи зникла денна робота.

ДЕ ЖИВУТЬ АКАУНТИ КЛІЄНТІВ. В окремій базі `/root/cabinet/cabinet.db` (SQLite),
а НЕ в NocoDB. Причини дві. Перша — вимога користувачки: клієнтські акаунти
окремі від співробітницьких. Друга — у NocoDB `v.pontus@unitex.od.ua` має роль
`editor`, тобто читання й запис УСІХ таблиць (перевірено 10.08.2026); хеші
паролів клієнтів там лежали б у нього перед очима. Заводяться акаунти скриптом
`server/cabinet_admin.py`.

ПАРОЛІ. У базі лежить лише scrypt-хеш із сіллю. Сам пароль не пишеться ні в
журнал, ні в репозиторій, ні у відповідь сервера — його видно рівно один раз,
у терміналі того, хто заводить акаунт.

ЖУРНАЛ. Серверний і непідробний, на відміну від журналу ЕРП, який пише браузер:
входи, невдалі спроби, перегляди, завантаження документів.

Запуск: python3 /root/Iryna_Karmazina/server/cabinet.py
Порт:   127.0.0.1:8793 (Caddy проксює cabinet.unitex.od.ua сюди)
Журнал: /root/cabinet.log
Розгортання й перевірки: server/CABINET.md
"""
import base64
import datetime
import hashlib
import hmac
import html
import importlib.util
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NC = "http://127.0.0.1:8080"
TOKEN_FILE = "/root/nocodb-token.txt"
PORT = int(os.environ.get("CABINET_PORT", "8793"))
DB_PATH = os.environ.get("CABINET_DB", "/root/cabinet/cabinet.db")
SECRET_FILE = os.environ.get("CABINET_SECRET", "/root/cabinet/secret")
LOG_FILE = os.environ.get("CABINET_LOG", "/root/cabinet.log")
# Публічна адреса кабінету — потрібна, щоб платформа могла відкрити перехід
# у новій вкладці. У змінній, а не зашита: домен може змінитись.
PUBLIC_URL = os.environ.get("CABINET_URL", "https://cabinet.unitex.od.ua")

COOKIE = "cab_sid"
IDLE_HOURS = 12            # скільки живе сесія без дій
CACHE_SEC = 60             # кеш угод, як у gateway.py — інакше кожен клік у NocoDB
MIN_PWD = 10               # мінімальна довжина пароля
FAILS_BEFORE_PAUSE = 3     # після скількох невдалих спроб вмикається пауза
                           # (вимога користувачки 13.08.2026: «після 3х, а не 5ти»)

# Прапорець ТІЛЬКИ для перевірки на машині без HTTPS. У бою не ставити:
# без нього кука має Secure і по http не піде взагалі.
INSECURE = os.environ.get("CABINET_INSECURE") == "1"

# ⚠️ ТИМЧАСОВИЙ РЕЖИМ: ВХІД БЕЗ ПАРОЛЯ (рішення користувачки 13.08.2026,
# «поки що», щоб не тягати тимчасові паролі через веб-консоль під час перевірки).
# Що це означає НАСПРАВДІ: досить знати пошту заведеного акаунта — і людина
# бачить усі угоди тієї компанії. Пошта співробітника є на сайті й у листах,
# тобто це рівнозначно тому, що кабінет відкритий. Компанії одна від одної
# лишаються відділені (пошта визначає, чиї угоди показати), але від сторонніх
# кабінет не захищений НІЧИМ.
# Вмикається лише змінною середовища в unitex-cabinet.service. Вимкнути —
# прибрати рядок Environment=CABINET_NO_PASSWORD=1 і перезапустити службу;
# паролі в базі лишаються на місці й одразу знову працюють.
NO_PASSWORD = os.environ.get("CABINET_NO_PASSWORD") == "1"


# ── шаблон сторінки беремо з прототипу, а не копіюємо ─────────────────────
def _load_builder():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, os.pardir, "client_cabinet", "build_preview.py"),
              "/root/Iryna_Karmazina/client_cabinet/build_preview.py"):
        p = os.path.abspath(p)
        if os.path.exists(p):
            spec = importlib.util.spec_from_file_location("build_preview", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise SystemExit("НЕ ЗНАЙДЕНО client_cabinet/build_preview.py — без нього "
                     "немає ні шаблону сторінки, ні списку дозволених колонок.")


BP = _load_builder()


def log(line):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (stamp, line))
    except Exception:  # noqa: BLE001
        pass
    print("CABINET %s" % line, flush=True)


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ── база акаунтів ─────────────────────────────────────────────────────────
def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(
  email       TEXT PRIMARY KEY,
  client      TEXT NOT NULL,
  name        TEXT NOT NULL DEFAULT '',
  pwd         TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1,
  must_change INTEGER NOT NULL DEFAULT 1,
  created     TEXT NOT NULL,
  last_login  TEXT
);
CREATE TABLE IF NOT EXISTS sessions(
  sid       TEXT PRIMARY KEY,
  email     TEXT NOT NULL,
  created   TEXT NOT NULL,
  seen      TEXT NOT NULL,
  ip        TEXT,
  ua        TEXT,
  -- Заповнене as_client означає СЕСІЮ СПІВРОБІТНИКА: він дивиться кабінет
  -- очима клієнта. Акаунта клієнта при цьому не існує і пароль не потрібен —
  -- права дав ЕРП. У журналі така сесія позначається окремо.
  as_client TEXT
);
CREATE TABLE IF NOT EXISTS audit(
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  ts     TEXT NOT NULL,
  email  TEXT,
  client TEXT,
  action TEXT NOT NULL,
  detail TEXT,
  ip     TEXT
);
CREATE TABLE IF NOT EXISTS invites(
  th      TEXT PRIMARY KEY,          -- sha256 від токена; сам токен НЕ зберігається
  email   TEXT NOT NULL,
  created TEXT NOT NULL,
  expires TEXT NOT NULL,
  used    TEXT
);
CREATE TABLE IF NOT EXISTS views(
  th      TEXT PRIMARY KEY,
  email   TEXT NOT NULL,          -- співробітник, якому видано
  client  TEXT NOT NULL,
  created TEXT NOT NULL,
  expires TEXT NOT NULL,
  used    TEXT
);
CREATE TABLE IF NOT EXISTS throttle(
  k     TEXT PRIMARY KEY,
  fails INTEGER NOT NULL DEFAULT 0,
  until TEXT
);
"""


# Колонки, додані ПІСЛЯ того, як база вже жила на сервері. `CREATE TABLE IF NOT
# EXISTS` існуючу таблицю не чіпає, тому нову колонку треба додавати окремо —
# інакше код пише в неї, а її немає. Саме так 14.08.2026 перегляд кабінету
# співробітником відповів 500: у `sessions` не було `as_client`.
MIGRATIONS = [("sessions", "as_client", "TEXT")]


def init_db():
    con = db()
    con.executescript(SCHEMA)
    for table, col, kind in MIGRATIONS:
        have = {r["name"] for r in con.execute("PRAGMA table_info(%s)" % table)}
        if col not in have:
            con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, kind))
            log("база оновлена: %s.%s додано" % (table, col))
    con.commit()
    con.close()


def audit(email, client, action, detail="", ip=""):
    """Журнал пише СЕРВЕР. Підробити його з браузера неможливо."""
    try:
        con = db()
        con.execute("INSERT INTO audit(ts,email,client,action,detail,ip) VALUES(?,?,?,?,?,?)",
                    (now(), email or "", client or "", action, detail[:500], ip or ""))
        con.commit()
        con.close()
    except Exception as e:  # noqa: BLE001
        log("ЖУРНАЛ НЕ ЗАПИСАВСЯ: %s" % str(e)[:120])
    log("%s · %s · %s%s" % (action, email or "—", detail[:160], "  ip=%s" % ip if ip else ""))


# ── паролі ────────────────────────────────────────────────────────────────
# scrypt зі стандартної бібліотеки: сіль на кожен пароль, порівняння —
# compare_digest (без нього час відповіді підказує, наскільки хеш збігся).
SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1


def hash_pwd(plain):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(plain.encode("utf-8"), salt=salt,
                       n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (
        SCRYPT_N, SCRYPT_R, SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def check_pwd(plain, stored):
    try:
        alg, n, r, p, salt_b, hash_b = str(stored).split("$")
        if alg != "scrypt":
            return False
        h = hashlib.scrypt(plain.encode("utf-8"), salt=base64.b64decode(salt_b),
                           n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(h, base64.b64decode(hash_b))
    except Exception:  # noqa: BLE001
        return False


def pwd_problem(p):
    """Чому такий пароль не годиться. None — годиться."""
    if len(p or "") < MIN_PWD:
        return "Пароль має бути щонайменше %d символів." % MIN_PWD
    if p.strip() != p:
        return "Пароль не має починатись або закінчуватись пробілом."
    if p.lower() in ("password", "parol", "1234567890", "qwertyuiop", "unitex1234"):
        return "Такий пароль підбирається за секунди — виберіть інший."
    return None


# ── обмеження на підбір пароля ────────────────────────────────────────────
def throttle_left(key):
    """Скільки секунд ще заблоковано. 0 — можна пробувати."""
    con = db()
    row = con.execute("SELECT fails,until FROM throttle WHERE k=?", (key,)).fetchone()
    con.close()
    if not row or not row["until"]:
        return 0
    try:
        left = (datetime.datetime.fromisoformat(row["until"]) - datetime.datetime.now()).total_seconds()
    except Exception:  # noqa: BLE001
        return 0
    return int(max(0, left))


def throttle_fail(key):
    """Порахувати невдачу. З 3-ї — пауза, яка подвоюється до години.

    Тобто 5 хв, 10, 20, 40, далі 60. Перші дві помилки нічого не вмикають:
    людина, яка просто одруклася, паузи не помітить, а перебір зупиняється
    майже одразу.
    """
    con = db()
    row = con.execute("SELECT fails FROM throttle WHERE k=?", (key,)).fetchone()
    fails = (row["fails"] if row else 0) + 1
    until = None
    if fails >= FAILS_BEFORE_PAUSE:
        mins = min(60, 5 * (2 ** (fails - FAILS_BEFORE_PAUSE)))
        until = (datetime.datetime.now() + datetime.timedelta(minutes=mins)).isoformat(timespec="seconds")
    con.execute("INSERT INTO throttle(k,fails,until) VALUES(?,?,?) "
                "ON CONFLICT(k) DO UPDATE SET fails=?,until=?", (key, fails, until, fails, until))
    con.commit()
    con.close()
    return fails, until


def throttle_ok(key):
    con = db()
    con.execute("DELETE FROM throttle WHERE k=?", (key,))
    con.commit()
    con.close()


# ── сесії ─────────────────────────────────────────────────────────────────
def secret():
    """Ключ для міток CSRF. Файл 0600, переживає перезапуск."""
    os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
    if not os.path.exists(SECRET_FILE):
        fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secrets.token_bytes(32))
    with open(SECRET_FILE, "rb") as f:
        return f.read()


def csrf_for(sid):
    return hmac.new(secret(), sid.encode(), hashlib.sha256).hexdigest()[:32]


def same_str(a, b):
    """Порівняння без підказки за часом. Обов'язково через байти:
    `hmac.compare_digest` на рядку з кирилицею кидає TypeError, і підроблена
    мітка «підроблено» роняла б обробник замість звичайної відмови
    (знайдено власним тестом 13.08.2026, до викладення)."""
    return hmac.compare_digest(str(a or "").encode("utf-8"), str(b or "").encode("utf-8"))


def session_new(email, ip, ua, as_client=None):
    sid = secrets.token_urlsafe(32)
    con = db()
    con.execute("INSERT INTO sessions(sid,email,created,seen,ip,ua,as_client) "
                "VALUES(?,?,?,?,?,?,?)",
                (sid, email, now(), now(), ip, (ua or "")[:200], as_client))
    con.commit()
    con.close()
    return sid


def session_get(sid):
    """Акаунт за ключем сесії або None. Заразом продовжує сесію."""
    if not sid:
        return None
    con = db()
    st = con.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone()
    if not st:
        con.close()
        return None
    if st["as_client"]:
        # Сесія співробітника: акаунта клієнта немає і не треба.
        try:
            idle = (datetime.datetime.now()
                    - datetime.datetime.fromisoformat(st["seen"])).total_seconds()
        except Exception:  # noqa: BLE001
            idle = 0
        if idle > IDLE_HOURS * 3600:
            con.execute("DELETE FROM sessions WHERE sid=?", (sid,))
            con.commit()
            con.close()
            return None
        con.execute("UPDATE sessions SET seen=? WHERE sid=?", (now(), sid))
        con.commit()
        con.close()
        return {"sid": sid, "email": st["email"], "client": st["as_client"],
                "name": st["email"], "must_change": 0, "active": 1, "staff": 1}
    row = con.execute(
        "SELECT s.sid,s.seen,a.* FROM sessions s JOIN accounts a ON a.email=s.email "
        "WHERE s.sid=?", (sid,)).fetchone()
    if not row:
        con.close()
        return None
    if not row["active"]:
        con.execute("DELETE FROM sessions WHERE sid=?", (sid,))   # заблокували — вхід обриваємо
        con.commit()
        con.close()
        return None
    try:
        idle = (datetime.datetime.now() - datetime.datetime.fromisoformat(row["seen"])).total_seconds()
    except Exception:  # noqa: BLE001
        idle = 0
    if idle > IDLE_HOURS * 3600:
        con.execute("DELETE FROM sessions WHERE sid=?", (sid,))
        con.commit()
        con.close()
        return None
    con.execute("UPDATE sessions SET seen=? WHERE sid=?", (now(), sid))
    con.commit()
    acc = dict(row)
    con.close()
    return acc


def session_drop(sid):
    con = db()
    con.execute("DELETE FROM sessions WHERE sid=?", (sid,))
    con.commit()
    con.close()


def sessions_drop_email(email, keep=None):
    con = db()
    if keep:
        con.execute("DELETE FROM sessions WHERE email=? AND sid<>?", (email, keep))
    else:
        con.execute("DELETE FROM sessions WHERE email=?", (email,))
    con.commit()
    con.close()


# ── дані з NocoDB ─────────────────────────────────────────────────────────
_cache = {"ts": 0.0, "rows": []}


def all_rows():
    if time.time() - _cache["ts"] < CACHE_SEC and _cache["rows"]:
        return _cache["rows"]
    rows = BP.nc_all()                       # той самий читач, що й у прототипі
    _cache["rows"] = rows
    _cache["ts"] = time.time()
    return rows


def deals_for(client):
    """Угоди ОДНІЄЇ компанії. Збіг лише ТОЧНИЙ.

    Підрядковий збіг тут був би дірою: «Мірандор» підтягнув би «Мірандор Плюс»
    (знайдено аудитом 07.08.2026 у прототипі). Назву компанії звіряють один раз,
    коли заводять акаунт (cabinet_admin.py), і далі порівнюють дослівно.
    """
    want = BP.nz(client).lower()
    if not want:
        return []
    return [r for r in all_rows()
            if BP.nz(r.get("Клієнт")).lower() == want
            and BP.nz(r.get("Статус")) != BP.CANCELLED]


DOC_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$")


def docs_of(row):
    """Документи угоди, які МОЖНА показати клієнту, разом зі шляхом у сховищі.

    Відрізняється від BP.files_of лише тим, що лишає `path` — він потрібен
    серверу, щоб віддати файл, і НЕ потрапляє в сторінку: браузер бачить тільки
    номер по порядку. Правило відбору те саме — білий список BP.CLIENT_DOCS,
    усе з чужим або відсутнім префіксом [Тип] лишається всередині фірми.
    """
    raw = row.get("Файли")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001
            raw = []
    out = []
    for f in raw or []:
        title = BP.nz(f.get("title") or f.get("fileName"))
        m = DOC_RE.match(title)
        kind = m.group(1).strip() if m else ""
        # ⚠️ БЕЗ ПРЕФІКСА [Тип] — ТЕЖ НЕ ВІДДАЄМО (див. пояснення у BP.files_of).
        # Тут це критичніше, ніж у прев'ю: цей перелік не лише малює сторінку, а й
        # вирішує, чи віддасть сервер файл за номером. Поки умова була
        # `if kind and …`, клієнт міг і побачити, і СКАЧАТИ внутрішній документ.
        if kind not in BP.CLIENT_DOCS:
            continue
        # `path` — постійна адреса у сховищі, `signedPath` — тимчасова (dltemp/…)
        # з датою протермінування всередині. Беремо постійну, бо файл віддається
        # сервером із токеном і підпис нам не потрібен, а тимчасова колись стухне.
        path = f.get("path") or f.get("signedPath") or ""
        if not path:
            continue
        out.append({"kind": kind,
                    "name": (m.group(2) if m else title) or title,
                    "path": path,
                    "mime": f.get("mimetype") or "application/octet-stream"})
    return out


TRACK_LOG = os.environ.get("CABINET_TRACK_LOG", "/root/direct-sync/maersk.log")
RE_RUN = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) Оновити угод:")


def last_sync():
    """Коли автоматика ОСТАННІЙ РАЗ звірила дані з лініями. None — невідомо.

    Джерело — рядок завершення прогону в журналі трекінгу. Свідомо НЕ час
    складання сторінки: він оновлювався б на кожне натискання F5 і показував би
    клієнту «щойно», коли дані насправді вчорашні.
    І свідомо НЕ `automation.json`: перевірено 13.08.2026 — там лежав прогін від
    11.08, бо `automation_log.py` після кожного прогону ще не викликається.
    Не вдалося прочитати — повертаємо None, і позначки просто не буде.
    Вигадувати час не можна.
    """
    try:
        with open(TRACK_LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-4000:]
    except Exception:  # noqa: BLE001
        return None
    for ln in reversed(lines):
        m = RE_RUN.match(ln)
        if m:
            try:
                return datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    return None


def updated_badge():
    """Готова позначка «дані оновлено …» або порожньо, якщо часу не знаємо."""
    ts = last_sync()
    if not ts:
        return ""
    # Формат за вказівкою користувачки 13.08.2026: «Оновлено (години, дата)».
    # Дата в тому ж вигляді, що й у таблиці (16.08.26), щоб не було двох
    # різних форматів дати на одному екрані.
    when = ts.strftime("%H:%M, %d.%m.%y")
    return ('<div class="upd" title="Коли автоматика востаннє звіряла статуси '
            'з системами ліній">'
            '<i></i>Оновлено <b>%s</b></div>' % esc(when))


def page_data(rows):
    """Те, що поїде в браузер. Колонки — рівно BP.CLIENT_COLS, нічого понад."""
    data = []
    for r in rows:
        d = {k: r.get(k) for k in BP.CLIENT_COLS if k != "Файли"}
        deal = BP.nz(r.get("Угода"))
        d["_docs"] = [{"kind": x["kind"], "name": x["name"],
                       "url": "/doc/%s/%d" % (urllib.parse.quote(deal, safe=""), i)}
                      for i, x in enumerate(docs_of(r))]
        data.append(d)
    # Базовий, передбачуваний порядок. Остаточний задає браузер (byDate у
    # шаблоні: за датою відправлення, без дати — вниз, доставлені в кінці).
    data.sort(key=lambda d: (BP.nz(d.get("Статус")) == "Вантаж доставлено",
                             BP.nz(d.get("ETA")) or "9999"))
    return data



# ── одноразові посилання на встановлення пароля ───────────────────────────
# НАВІЩО. Раніше пароль вигадував сервер, і його треба було якось передати —
# через термінал, файл, листування. Будь-який із цих шляхів означає, що готовий
# пароль десь лежить. Тепер пароль вигадує САМ КЛІЄНТ, а ми передаємо лише
# одноразове посилання: воно живе обмежений час, спрацьовує один раз і після
# використання не діє. Зберігати після цього нічого не треба.
# У базі лежить лише sha256 від токена — навіть маючи базу, посилання не
# відновити. Це та сама логіка, що з паролями: зберігаємо перевірку, не секрет.
INVITE_HOURS = 72


def _th(token):
    return hashlib.sha256(("cab-invite:" + str(token)).encode("utf-8")).hexdigest()


def invite_new(email, hours=INVITE_HOURS):
    """Створити посилання. Повертає сам токен — його показують РІВНО ОДИН РАЗ."""
    token = secrets.token_urlsafe(32)
    exp = (datetime.datetime.now() + datetime.timedelta(hours=hours)).isoformat(timespec="seconds")
    con = db()
    # старі невикористані запрошення цієї людини гасимо: щоб не лишалось
    # кількох робочих посилань на один акаунт
    con.execute("UPDATE invites SET used=? WHERE email=? AND used IS NULL",
                (now() + " (замінено новим)", email))
    con.execute("INSERT INTO invites(th,email,created,expires) VALUES(?,?,?,?)",
                (_th(token), email, now(), exp))
    con.commit()
    con.close()
    return token, exp


def invite_check(token):
    """(email, причина_відмови). email None — посилання не годиться."""
    if not token:
        return None, "порожнє посилання"
    con = db()
    row = con.execute("SELECT * FROM invites WHERE th=?", (_th(token),)).fetchone()
    con.close()
    if not row:
        return None, "посилання невідоме"
    if row["used"]:
        return None, "посилання вже використане"
    if row["expires"] < now():
        return None, "термін дії посилання минув"
    return row["email"], ""


def invite_use(token):
    con = db()
    con.execute("UPDATE invites SET used=? WHERE th=?", (now(), _th(token)))
    con.commit()
    con.close()


def view_new(email, client, minutes=5):
    """Короткий одноразовий токен: ЕРП відкриває кабінет клієнта в новій вкладці.

    Живе хвилини, а не дні: він потрібен рівно на один перехід із платформи.
    Права перевіряються ДО видачі — по ролі в ЕРП, а не по цьому токену.
    """
    token = secrets.token_urlsafe(32)
    exp = (datetime.datetime.now() + datetime.timedelta(minutes=minutes)).isoformat(timespec="seconds")
    con = db()
    con.execute("INSERT INTO views(th,email,client,created,expires) VALUES(?,?,?,?,?)",
                (_th(token), email, client, now(), exp))
    con.commit()
    con.close()
    return token


def view_use(token):
    """(email, client) або (None, причина)."""
    if not token:
        return None, "порожнє посилання"
    con = db()
    row = con.execute("SELECT * FROM views WHERE th=?", (_th(token),)).fetchone()
    if not row:
        con.close()
        return None, "посилання невідоме"
    if row["used"]:
        con.close()
        return None, "посилання вже використане"
    if row["expires"] < now():
        con.close()
        return None, "термін дії минув"
    con.execute("UPDATE views SET used=? WHERE th=?", (now(), _th(token)))
    con.commit()
    con.close()
    return (row["email"], row["client"]), ""


def clients_with_deals(manager=None):
    """Компанії, у яких є непорожній кабінет: назва + скільки угод.

    `manager` — якщо задано, рахуємо ЛИШЕ угоди цього менеджера. Так сейлз
    бачить тільки своїх клієнтів (рішення користувачки 24.08.2026: «сейлз
    менеджер — тільки свої клієнтів»). Порожній рядок сюди передавати НЕ можна:
    це означало б «без обмеження», тобто відкрити все. Виклик зверху зобов'язаний
    перевірити, що ім'я взагалі є.
    """
    out = {}
    for r in all_rows():
        name = BP.nz(r.get("Клієнт"))
        if not name or BP.nz(r.get("Статус")) == BP.CANCELLED:
            continue
        if manager is not None and BP.nz(r.get("Менеджер")) != manager:
            continue
        out[name] = out.get(name, 0) + 1
    return out


# ── журнал для ЕРП ────────────────────────────────────────────────────────
_GW = None


def gateway():
    """Прошарок ЕРП — з нього беремо перевірку «хто ти і яка в тебе роль».

    Свою копію цієї логіки тут НЕ пишемо: роль читається з таблиці
    «Користувачі», і два різні прочитання ролей рано чи пізно розійдуться.
    """
    global _GW
    if _GW is None:
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, "gateway.py"), "/root/gateway.py",
                  "/root/Iryna_Karmazina/server/gateway.py"):
            if os.path.exists(p):
                spec = importlib.util.spec_from_file_location("gateway", p)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _GW = mod
                break
        else:
            _GW = False
    return _GW or None


def journal_rows(limit=500, client="", email=""):
    con = db()
    sql = "SELECT ts,email,client,action,detail,ip FROM audit"
    args, where = [], []
    if client:
        where.append("lower(client)=lower(?)"); args.append(client)
    if email:
        where.append("lower(email)=lower(?)"); args.append(email)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(int(limit), 2000)))
    rows = [dict(r) for r in con.execute(sql, args)]
    con.close()
    return rows


# ── сторінки ──────────────────────────────────────────────────────────────
LOGIN_CSS = """
/* Палітра взята ДОСЛІВНО з кабінету (client_cabinet/build_preview.py),
   а той — з ЕРП. Своїх кольорів тут не вигадуємо. */
:root{--paper:#f9f9f7;--surface:#ffffff;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
  --line:#e1e0d9;--accent:#2a78d6;--accent-soft:#e7f0fb;--accent-ink:#1c5cab;
  --err:#b42318;--err-bg:#fdeceb;--pos:#1a8f5c;--pos-bg:#e6f5ec;
  --shadow:0 1px 2px rgba(11,11,11,.05),0 1px 3px rgba(11,11,11,.04);--r:14px}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);min-height:100vh;
  display:flex;align-items:center;justify-content:center;padding:24px;
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
.box{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);padding:30px 32px;width:100%;max-width:404px}
.box img{height:54px;display:block;margin:0 auto 18px}
h1{font-size:19px;margin:0 0 4px;text-align:center;letter-spacing:-.3px}
.sub{color:var(--muted);font-size:13px;text-align:center;margin-bottom:22px}
label{display:block;font-size:12.5px;color:var(--ink-2);margin:0 0 6px;font-weight:600}
input{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:11px;
  background:var(--surface);font:inherit;font-size:14.5px;color:var(--ink);margin-bottom:15px}
input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
button{width:100%;padding:12px;border:1px solid var(--accent);background:var(--accent);
  color:#fff;border-radius:11px;font:inherit;font-size:14.5px;font-weight:600;cursor:pointer}
button:hover{filter:brightness(1.06)}
.msg{border-radius:11px;padding:11px 13px;font-size:13.5px;margin-bottom:16px}
.msg.err{background:var(--err-bg);color:var(--err)}
.msg.ok{background:var(--pos-bg);color:var(--pos)}
.msg.warn{background:#fdf3e3;color:#b45309}
.hint{color:var(--muted);font-size:12px;margin-top:16px;text-align:center;line-height:1.45}
"""

LOGIN_TPL = """<!doctype html>
<meta charset="utf-8">
<title>__TITLE__</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style nonce="__NONCE__">__CSS__</style>
<form class="box" method="post" action="__ACTION__" autocomplete="on">
  __LOGO__
  <h1>__H1__</h1>
  <div class="sub">__SUB__</div>
  __MSG__
  __FIELDS__
  <button type="submit">__BTN__</button>
  <div class="hint">__HINT__</div>
</form>
"""


def esc(s):
    return html.escape(str(s or ""), quote=True)


def render_login(msg="", kind="err", email=""):
    logo = BP.logo()
    fields = (
        '<label for="email">Електронна пошта</label>'
        '<input id="email" name="email" type="email" required autocomplete="username" value="%s">'
        % esc(email))
    if not NO_PASSWORD:
        fields += ('<label for="password">Пароль</label>'
                   '<input id="password" name="password" type="password" required '
                   'autocomplete="current-password">')
    # У режимі без пароля це видно на самій сторінці входу — щоб ніхто (і я
    # в тому числі) не забув, що кабінет зараз відкритий.
    hint = ("Доступ надає ваш менеджер UNITEX. Якщо не пам'ятаєте пароль — "
            "зверніться до нього, ми надішлемо новий.")
    if NO_PASSWORD and not msg:
        msg, kind = ("Тимчасовий режим перевірки: вхід без пароля. "
                     "Кабінет зараз відкритий для всіх, хто знає пошту."), "warn"
    return _fill_login(
        title="UNITEX — вхід в особистий кабінет", h1="Особистий кабінет",
        sub="Відстеження ваших вантажів", action="/login", fields=fields,
        btn="Увійти", msg=msg, kind=kind, logo=logo, hint=hint)


def render_invite(token, msg="", kind="err"):
    """Сторінка за одноразовим посиланням: людина сама придумує пароль.
    Поточного пароля тут не питаємо — його ніхто й не знає, у цьому вся суть."""
    fields = ('<input type="hidden" name="t" value="%s">'
              '<label for="new1">Придумайте пароль</label>'
              '<input id="new1" name="new1" type="password" required autocomplete="new-password">'
              '<label for="new2">Повторіть пароль</label>'
              '<input id="new2" name="new2" type="password" required autocomplete="new-password">'
              % esc(token))
    return _fill_login(
        title="UNITEX — створення пароля", h1="Створіть свій пароль",
        sub="Це посилання одноразове й діє обмежений час",
        action="/set", fields=fields, btn="Зберегти і увійти",
        msg=msg, kind=kind, logo=BP.logo(),
        hint="Щонайменше %d символів. Пароль знаєте тільки ви — "
             "ми його не бачимо і не зберігаємо у відкритому вигляді." % MIN_PWD)


def render_change(msg="", kind="err", first=False):
    fields = ('<label for="old">Поточний пароль</label>'
              '<input id="old" name="old" type="password" required autocomplete="current-password">'
              '<label for="new1">Новий пароль</label>'
              '<input id="new1" name="new1" type="password" required autocomplete="new-password">'
              '<label for="new2">Новий пароль ще раз</label>'
              '<input id="new2" name="new2" type="password" required autocomplete="new-password">')
    return _fill_login(
        title="UNITEX — зміна пароля",
        h1="Придумайте свій пароль" if first else "Зміна пароля",
        sub=("Це перший вхід — тимчасовий пароль треба замінити"
             if first else "Після зміни інші пристрої вийдуть із кабінету"),
        action="/password", fields=fields, btn="Зберегти", msg=msg, kind=kind,
        logo=BP.logo(), hint="Щонайменше %d символів." % MIN_PWD)


def _fill_login(title, h1, sub, action, fields, btn, msg, kind, logo, hint):
    nonce = secrets.token_urlsafe(16)
    body = (LOGIN_TPL
            .replace("__CSS__", LOGIN_CSS)
            .replace("__TITLE__", esc(title))
            .replace("__H1__", esc(h1))
            .replace("__SUB__", esc(sub))
            .replace("__ACTION__", action)
            .replace("__FIELDS__", fields)
            .replace("__BTN__", esc(btn))
            .replace("__HINT__", esc(hint))
            .replace("__LOGO__", '<img src="%s" alt="UNITEX">' % logo if logo else "")
            .replace("__MSG__", '<div class="msg %s">%s</div>' % (kind, esc(msg)) if msg else "")
            .replace("__NONCE__", nonce))
    return body, nonce


def render_cabinet(acc):
    """Сторінка кабінету. Збирається на кожен запит із угод ЦІЄЇ компанії."""
    rows = deals_for(acc["client"])
    data = page_data(rows)
    nonce = secrets.token_urlsafe(16)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    who = esc(acc["name"] or acc["email"])
    # Кнопка стоїть УСЕРЕДИНІ блоку з назвою компанії (див. .who в шаблоні):
    # назва зверху, кнопка під нею, обидві по правому краю рамки таблиці.
    head = ('<form method="post" action="/logout">'
            '<input type="hidden" name="_csrf" value="%s">'
            '<button class="btn" type="submit" title="%s">%s</button></form>'
            % (csrf_for(acc["sid"]), who,
               "Закрити перегляд" if acc.get("staff") else "Вийти"))
    banner = ""
    if acc.get("staff"):
        banner = ('<div class="staffbar">Ви дивитесь кабінет <b>%s</b> як співробітник '
                  'UNITEX. Клієнт цього перегляду не бачить, але він записаний у журнал.'
                  '</div>' % esc(BP.client_title(acc["client"])))
    html_out = (BP.TPL
                .replace("__BANNER__", banner)
                .replace("__LOGO__", BP.logo())
                .replace("__TITLE__", "UNITEX — особистий кабінет")
                .replace("__HEADEXTRA__", head)
                .replace("__DEMO__", "false")
                .replace("__UPDATED__", updated_badge())
                .replace("__CLIENTFULL__", esc(BP.client_title(acc["client"])))
                .replace("__CLIENT__", esc(acc["client"]))
                .replace("__TODAY__", datetime.date.today().isoformat())
                .replace("__DATA__", payload))
    # Скрипт і стилі в шаблоні вбудовані, тому CSP пускає їх за міткою nonce:
    # будь-який ЧУЖИЙ скрипт, який колись потрапить у дані, мітки не матиме
    # і не виконається. Це другий шар поверх екранування «</» у даних.
    html_out = html_out.replace("<script>", '<script nonce="%s">' % nonce, 1)
    html_out = html_out.replace("<style>", '<style nonce="%s">' % nonce, 1)
    return html_out, nonce, len(data)


# ── HTTP ──────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "unitex-cabinet"
    sys_version = ""

    def log_message(self, fmt, *args):        # свій журнал, стандартний не потрібен
        pass

    # ── дрібні помічники ──
    def ip(self):
        fwd = self.headers.get("X-Forwarded-For") or ""
        return (fwd.split(",")[0].strip() or self.client_address[0])[:45]

    def cookie(self, name):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return urllib.parse.unquote(v)
        return ""

    def form(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 64 * 1024:
            return {}
        raw = self.rfile.read(length).decode("utf-8", "replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    def send_html(self, code, body, nonce, extra=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        # default-src 'none' — сторінка не має права звертатись НІКУДИ назовні.
        # style-src з 'unsafe-inline': у розмітці є атрибути style=…, а мітка
        # nonce на атрибути не поширюється — це обмеження самого CSP, не недогляд.
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; img-src 'self' data:; "
                         "style-src 'unsafe-inline'; script-src 'nonce-%s'; "
                         "form-action 'self'; base-uri 'none'; frame-ancestors 'none'" % nonce)
        self.send_header("X-Frame-Options", "DENY")          # кабінет не вбудовується в чужу сторінку
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_plain(self, code, text, ctype="text/plain; charset=utf-8", extra=None):
        data = text.encode("utf-8") if isinstance(text, str) else text
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def redirect(self, where, cookie=None):
        extra = [("Location", where)]
        if cookie:
            extra.append(("Set-Cookie", cookie))
        self.send_response(303)
        self.send_header("Content-Length", "0")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()

    def cookie_set(self, sid):
        bits = ["%s=%s" % (COOKIE, sid), "Path=/", "HttpOnly", "SameSite=Lax",
                "Max-Age=%d" % (IDLE_HOURS * 3600)]
        if not INSECURE:
            bits.insert(2, "Secure")
        return "; ".join(bits)

    def cookie_clear(self):
        bits = ["%s=" % COOKIE, "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
        if not INSECURE:
            bits.insert(2, "Secure")
        return "; ".join(bits)

    def same_origin(self):
        """Захист від чужої сторінки, яка надсилає форму від імені клієнта.

        Браузер сам проставляє Origin у POST. Якщо він є і не наш — це не наша
        форма. Якщо його немає (старий браузер) — покладаємось на SameSite=Lax.
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host") or ""
        return urllib.parse.urlparse(origin).netloc == host

    # ── маршрути ──
    def do_GET(self):
        self._guard(self._get)

    def do_HEAD(self):
        self._guard(self._get)

    def do_POST(self):
        self._guard(self._post)

    def _guard(self, fn):
        """Неочікувана помилка має стати відповіддю, а не обривом з'єднання.

        Без цього будь-який недогляд у коді виглядає для клієнта як «сайт не
        працює», а в журналі не лишається нічого. Текст помилки назовні НЕ
        віддаємо — тільки в журнал.
        """
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError):
            pass                                   # клієнт закрив вкладку
        except Exception as e:  # noqa: BLE001
            log("ЗБІЙ %s %s: %s" % (self.command, self.path[:80], repr(e)[:200]))
            try:
                self.send_plain(500, "Технічна помилка. Спробуйте, будь ласка, ще раз.")
            except Exception:  # noqa: BLE001
                pass

    def _get(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            return self.send_plain(200, "ok")
        if path == "/robots.txt":
            return self.send_plain(200, "User-agent: *\nDisallow: /\n")
        acc = session_get(self.cookie(COOKIE))
        if path == "/":
            if not acc:
                body, nonce = render_login()
                return self.send_html(200, body, nonce)
            # Вимога змінити тимчасовий пароль у режимі без пароля не має сенсу:
            # форма питала б поточний пароль, якого людина не вводила, і в
            # кабінет не потрапив би ніхто. Позначка «новий» у базі лишається —
            # щойно режим вимкнуть, вимога знову спрацює.
            if acc["must_change"] and not NO_PASSWORD:
                body, nonce = render_change(first=True)
                return self.send_html(200, body, nonce)
            try:
                body, nonce, n = render_cabinet(acc)
            except Exception as e:  # noqa: BLE001
                log("СТОРІНКА НЕ ЗІБРАЛАСЬ для %s: %s" % (acc["email"], str(e)[:200]))
                return self.send_plain(503, "Дані тимчасово недоступні. "
                                            "Спробуйте, будь ласка, за хвилину.")
            audit(acc["email"], acc["client"], "перегляд", "угод %d" % n, self.ip())
            return self.send_html(200, body, nonce)
        if path == "/as":
            token = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                     .get("t") or [""])[0]
            who, why = view_use(token)
            if not who:
                audit("", "", "невдалий перегляд", why, self.ip())
                return self.send_plain(410, "Посилання не діє: %s. "
                                            "Відкрийте кабінет із платформи заново." % why)
            staff_email, client = who
            sid = session_new(staff_email, self.ip(), self.headers.get("User-Agent"),
                              as_client=client)
            audit(staff_email, client, "перегляд кабінету співробітником", "", self.ip())
            return self.redirect("/", self.cookie_set(sid))
        if path == "/set":
            token = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                     .get("t") or [""])[0]
            email, why = invite_check(token)
            if not email:
                audit("", "", "невдале посилання", why, self.ip())
                body, nonce = _fill_login(
                    title="UNITEX — посилання недійсне", h1="Посилання не діє",
                    sub=why, action="/", fields="", btn="На сторінку входу",
                    msg="Попросіть менеджера UNITEX надіслати нове посилання.",
                    kind="err", logo=BP.logo(), hint="")
                return self.send_html(410, body, nonce)
            body, nonce = render_invite(token)
            return self.send_html(200, body, nonce)
        if path == "/password":
            if not acc:
                return self.redirect("/")
            body, nonce = render_change(first=bool(acc["must_change"]))
            return self.send_html(200, body, nonce)
        if path == "/cabinet-log":
            return self.serve_journal()
        if path == "/cabinet-clients":
            return self.serve_clients()
        if path == "/cabinet-accounts":
            return self.serve_accounts()
        if path.startswith("/doc/"):
            return self.serve_doc(path, acc)
        return self.send_plain(404, "Сторінки немає.")

    def _post(self):
        path = urllib.parse.urlparse(self.path).path
        if not self.same_origin():
            return self.send_plain(403, "Запит прийшов не з кабінету.")
        if path == "/login":
            return self.do_login()
        if path == "/logout":
            return self.do_logout()
        if path == "/cabinet-view":
            return self.do_view_link()
        if path == "/cabinet-invite":
            return self.do_invite_link()
        if path == "/set":
            return self.do_set()
        if path == "/password":
            return self.do_password()
        return self.send_plain(404, "Сторінки немає.")

    def do_login(self):
        f = self.form()
        email = (f.get("email") or "").strip().lower()[:120]
        password = f.get("password") or ""
        ip = self.ip()
        # Рахуємо і пошту, і адресу: інакше або один клієнт блокує іншого з тієї
        # самої контори, або перебір з різних адрес не помічається зовсім.
        keys = ["e:" + email, "i:" + ip]
        left = max(throttle_left(k) for k in keys)
        if left:
            audit(email, "", "вхід заблоковано", "ще %d с" % left, ip)
            body, nonce = render_login(
                "Забагато спроб. Спробуйте за %d хв." % max(1, left // 60), email=email)
            return self.send_html(429, body, nonce)

        con = db()
        row = con.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
        con.close()
        if NO_PASSWORD:
            ok = bool(row)                 # пароля не питаємо взагалі — див. шапку файла
        else:
            # Пароль перевіряємо навіть коли акаунта немає — по фіктивному хешу.
            # Без цього час відповіді видає, які пошти в нас заведені.
            ok = check_pwd(password, row["pwd"]) if row else check_pwd(password, hash_pwd("-"))
        if not row or not ok or not row["active"]:
            why = ("немає такої пошти" if not row
                   else "заблокований" if not row["active"] else "невірний пароль")
            fails = max(throttle_fail(k)[0] for k in keys)
            audit(email, row["client"] if row else "", "невдалий вхід",
                  "%s (спроба %d)" % (why, fails), ip)
            body, nonce = render_login("Пошта або пароль не підходять.", email=email)
            return self.send_html(401, body, nonce)

        for k in keys:
            throttle_ok(k)
        sid = session_new(email, ip, self.headers.get("User-Agent"))
        con = db()
        con.execute("UPDATE accounts SET last_login=? WHERE email=?", (now(), email))
        con.commit()
        con.close()
        audit(email, row["client"], "вхід БЕЗ ПАРОЛЯ" if NO_PASSWORD else "вхід", "", ip)
        return self.redirect("/", self.cookie_set(sid))

    def do_logout(self):
        sid = self.cookie(COOKIE)
        acc = session_get(sid)
        if acc and not same_str(self.form().get("_csrf", ""), csrf_for(sid)):
            return self.send_plain(403, "Позначка форми не збіглася. Оновіть сторінку.")
        if acc:
            audit(acc["email"], acc["client"], "вихід", "", self.ip())
        session_drop(sid)
        return self.redirect("/", self.cookie_clear())

    def do_password(self):
        sid = self.cookie(COOKIE)
        acc = session_get(sid)
        if not acc:
            return self.redirect("/")
        first = bool(acc["must_change"])
        f = self.form()
        old, new1, new2 = f.get("old") or "", f.get("new1") or "", f.get("new2") or ""
        if not check_pwd(old, acc["pwd"]):
            audit(acc["email"], acc["client"], "зміна пароля відхилена",
                  "поточний пароль невірний", self.ip())
            body, nonce = render_change("Поточний пароль невірний.", first=first)
            return self.send_html(401, body, nonce)
        if new1 != new2:
            body, nonce = render_change("Паролі не збіглися.", first=first)
            return self.send_html(400, body, nonce)
        problem = pwd_problem(new1)
        if problem:
            body, nonce = render_change(problem, first=first)
            return self.send_html(400, body, nonce)
        if check_pwd(new1, acc["pwd"]):
            body, nonce = render_change("Новий пароль такий самий, як старий.", first=first)
            return self.send_html(400, body, nonce)
        con = db()
        con.execute("UPDATE accounts SET pwd=?,must_change=0 WHERE email=?",
                    (hash_pwd(new1), acc["email"]))
        con.commit()
        con.close()
        sessions_drop_email(acc["email"], keep=sid)   # інші пристрої виходять
        audit(acc["email"], acc["client"], "пароль змінено", "", self.ip())
        return self.redirect("/")

    def do_set(self):
        """Клієнт сам ставить собі пароль за одноразовим посиланням."""
        f = self.form()
        token = f.get("t") or ""
        email, why = invite_check(token)
        if not email:
            audit("", "", "невдале посилання", why, self.ip())
            return self.send_plain(410, "Посилання не діє: %s" % why)
        new1, new2 = f.get("new1") or "", f.get("new2") or ""
        if new1 != new2:
            body, nonce = render_invite(token, "Паролі не збіглися.")
            return self.send_html(400, body, nonce)
        problem = pwd_problem(new1)
        if problem:
            body, nonce = render_invite(token, problem)
            return self.send_html(400, body, nonce)
        con = db()
        row = con.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
        if not row or not row["active"]:
            con.close()
            audit(email, "", "невдале посилання", "акаунт заблокований або зник", self.ip())
            return self.send_plain(403, "Доступ закритий. Зверніться до менеджера UNITEX.")
        con.execute("UPDATE accounts SET pwd=?,must_change=0 WHERE email=?",
                    (hash_pwd(new1), email))
        con.commit()
        con.close()
        invite_use(token)
        sessions_drop_email(email)          # старі входи обриваємо
        sid = session_new(email, self.ip(), self.headers.get("User-Agent"))
        audit(email, row["client"], "пароль створено за посиланням", "", self.ip())
        return self.redirect("/", self.cookie_set(sid))

    def erp_admin(self):
        """Пошта адміністратора ЕРП або None. Роль читає gateway.py, не ми."""
        gw = gateway()
        if gw is None:
            return None
        email, _n, role = gw.whoami(self.headers.get("xc-auth") or "")
        return email if role == "Адміністратор" else None

    def erp_scope(self):
        """Хто прийшов з ЕРП і які компанії йому видно.

        Повертає (пошта, {назва: угод} або None). None — доступу немає взагалі.
        Рішення користувачки 24.08.2026: кабінети клієнтів бачать адміністратор
        (усі) і сейлз-менеджер (лише свої компанії); фінансист і бухгалтер не
        бачать їх зовсім.

        Свідомо fail-closed: якщо роль не з переліку, або в сейлза не заповнене
        ім'я в довіднику — доступу немає. Обмежувати нема по чому, а «пропустити
        про всяк випадок» тут означало б віддати чужі кабінети.
        """
        gw = gateway()
        if gw is None:
            return None, None
        email, name, role = gw.whoami(self.headers.get("xc-auth") or "")
        if role == "Адміністратор":
            return email, clients_with_deals()
        if role != "Сейлз-менеджер":
            return None, None
        name = (name or "").strip()
        if not name:
            audit(email or "", "", "відмова у кабінетах",
                  "сейлз без імені в довіднику", self.ip())
            return None, None
        return email, clients_with_deals(name)

    def serve_clients(self):
        """Список компаній для платформи: кого можна відкрити і скільки угод."""
        who, counts = self.erp_scope()
        if not who:
            return self.send_plain(403, "Кабінети клієнтів доступні адміністратору й сейлз-менеджеру.")
        con = db()
        accs = {}
        for r in con.execute("SELECT client, COUNT(*) n, SUM(active) a FROM accounts "
                             "GROUP BY client"):
            accs[r["client"]] = {"акаунтів": r["n"], "робочих": r["a"] or 0}
        con.close()
        rows = [{"client": c, "deals": n,
                 "accounts": accs.get(c, {}).get("акаунтів", 0),
                 "active": accs.get(c, {}).get("робочих", 0)}
                for c, n in sorted(counts.items(), key=lambda kv: -kv[1])]
        return self.send_plain(200, json.dumps({"list": rows}, ensure_ascii=False).encode(),
                               "application/json; charset=utf-8")

    def do_view_link(self):
        """ЕРП просить посилання, щоб відкрити кабінет клієнта. Тільки адмін."""
        who, allowed = self.erp_scope()
        if not who:
            return self.send_plain(403, "Кабінети клієнтів доступні адміністратору й сейлз-менеджеру.")
        f = self.form()
        client = (f.get("client") or "").strip()
        # Перевіряємо саме ДОЗВОЛЕНИЙ перелік, а не всі компанії: інакше сейлз
        # відкрив би чужий кабінет, підмінивши назву в запиті.
        if client not in allowed:
            return self.send_plain(404, "Такої компанії немає серед ваших угод.")
        token = view_new(who, client)
        audit(who, client, "видано посилання на перегляд", "з платформи", self.ip())
        return self.send_plain(200, json.dumps(
            {"url": PUBLIC_URL + "/as?t=" + token}, ensure_ascii=False).encode(),
            "application/json; charset=utf-8")

    def serve_accounts(self):
        """Акаунти клієнтів для платформи. Паролів і хешів тут НЕМАЄ."""
        who, allowed = self.erp_scope()
        if not who:
            return self.send_plain(403, "Кабінети клієнтів доступні адміністратору й сейлз-менеджеру.")
        con = db()
        rows = [{"email": r["email"], "client": r["client"], "name": r["name"],
                 "active": bool(r["active"]), "new": bool(r["must_change"]),
                 "last": r["last_login"] or ""}
                for r in con.execute("SELECT email,client,name,active,must_change,"
                                     "last_login FROM accounts ORDER BY client, email")
                if r["client"] in allowed]
        con.close()
        return self.send_plain(200, json.dumps({"list": rows}, ensure_ascii=False).encode(),
                               "application/json; charset=utf-8")

    def do_invite_link(self):
        """Посилання, за яким КЛІЄНТ САМ створює пароль. Показується один раз."""
        who, allowed = self.erp_scope()
        if not who:
            return self.send_plain(403, "Кабінети клієнтів доступні адміністратору й сейлз-менеджеру.")
        email = (self.form().get("email") or "").strip().lower()
        con = db()
        row = con.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
        con.close()
        if not row:
            return self.send_plain(404, "Такого акаунта немає.")
        # Те саме, що й для перегляду: сейлз не видає доступ чужій компанії.
        if row["client"] not in allowed:
            audit(email, row["client"], "відмова у посиланні",
                  "не свій клієнт (" + str(who) + ")", self.ip())
            return self.send_plain(403, "Це не ваш клієнт.")
        if not row["active"]:
            return self.send_plain(409, "Акаунт заблокований — спершу розблокуйте.")
        token, exp = invite_new(email)
        audit(email, row["client"], "створено посилання на пароль",
              "з платформи, %s, діє до %s" % (who, exp), self.ip())
        return self.send_plain(200, json.dumps(
            {"url": PUBLIC_URL + "/set?t=" + token, "expires": exp},
            ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def serve_journal(self):
        """Журнал кабінету для ЕРП. Тільки адміністраторові ЕРП.

        Клієнтська сесія тут НЕ приймається свідомо: журнал — внутрішній
        документ, клієнтові нема чого бачити, хто ще заходив.
        Перевірка ролі — через прошарок gateway.py, щоб не завести другого
        прочитання ролей.
        """
        gw = gateway()
        if gw is None:
            return self.send_plain(503, "Перевірка ролі недоступна.")
        jwt = self.headers.get("xc-auth") or ""
        email, _name, role = gw.whoami(jwt)
        if role != "Адміністратор":
            audit(email or "", "", "відмова у журналі",
                  "роль «%s»" % (role or "невідома"), self.ip())
            return self.send_plain(403, "Журнал доступний лише адміністратору.")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        rows = journal_rows(limit=(q.get("limit") or ["500"])[0],
                            client=(q.get("client") or [""])[0],
                            email=(q.get("email") or [""])[0])
        body = json.dumps({"list": rows}, ensure_ascii=False).encode("utf-8")
        return self.send_plain(200, body, "application/json; charset=utf-8")

    def serve_doc(self, path, acc):
        """Файл віддається лише після перевірки, чия це угода.

        Браузер називає угоду і номер документа в ній; шлях у сховищі
        обчислюється тут заново з тих самих правил, що й для сторінки. Підмінити
        адресу і забрати чужий файл не вийде: чужої угоди немає в deals_for().
        """
        if not acc:
            return self.redirect("/")
        parts = [p for p in path.split("/") if p]           # ['doc', '<угода>', '<i>']
        if len(parts) != 3:
            return self.send_plain(404, "Документа немає.")
        deal = urllib.parse.unquote(parts[1])
        try:
            idx = int(parts[2])
        except ValueError:
            return self.send_plain(404, "Документа немає.")
        row = next((r for r in deals_for(acc["client"]) if BP.nz(r.get("Угода")) == BP.nz(deal)), None)
        if row is None:
            audit(acc["email"], acc["client"], "відмова у файлі",
                  "угода %s не належить компанії" % deal[:40], self.ip())
            return self.send_plain(404, "Документа немає.")
        docs = docs_of(row)
        if not (0 <= idx < len(docs)):
            return self.send_plain(404, "Документа немає.")
        doc = docs[idx]
        # Шлях у сховищі підставляємо ЕКРАНОВАНИМ. Причина (15.08.2026): у першому
        # ж реальному документі — угода 252, «OBL NO.GDNBB2607002TH.pdf» — у назві
        # був пробіл, і запит із сирим шляхом не проходив зовсім, клієнт бачив
        # «Файл тимчасово недоступний». Той самий шлях з екранованим пробілом
        # віддає файл цілим (200, 1 048 935 байт). Раніше це не спливало, бо в базі
        # не було жодного вкладення. `%` лишаємо як є, щоб не закодувати двічі.
        url = NC + "/" + urllib.parse.quote(doc["path"].lstrip("/"), safe="/%")
        try:
            req = urllib.request.Request(url,
                                         headers={"xc-token": open(TOKEN_FILE).read().strip()})
            with urllib.request.urlopen(req, timeout=60) as resp:
                blob = resp.read()
                ctype = resp.headers.get("Content-Type") or doc["mime"]
        except Exception as e:  # noqa: BLE001
            log("ФАЙЛ НЕ ВІДДАВСЯ (%s, угода %s): %s" % (acc["email"], deal, str(e)[:160]))
            return self.send_plain(502, "Файл тимчасово недоступний.")
        name = re.sub(r'[^\w .()\-Ѐ-ӿ]', "_", "%s — %s" % (doc["kind"], doc["name"]))[:120]
        audit(acc["email"], acc["client"], "завантажив документ",
              "угода %s · %s" % (deal, doc["kind"]), self.ip())
        return self.send_plain(200, blob, ctype, extra=[
            ("Content-Disposition", "attachment; filename*=UTF-8''%s" % urllib.parse.quote(name)),
            ("X-Content-Type-Options", "nosniff")])


if __name__ == "__main__":
    init_db()
    secret()
    log("старт на 127.0.0.1:%d · база %s%s%s"
        % (PORT, DB_PATH, "  [БЕЗ Secure — тільки для перевірки!]" if INSECURE else "",
           "  [⚠️ ВХІД БЕЗ ПАРОЛЯ — кабінет відкритий усім, хто знає пошту]"
           if NO_PASSWORD else ""))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
