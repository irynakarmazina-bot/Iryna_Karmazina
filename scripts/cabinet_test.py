#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка кабінету клієнта БЕЗ живого NocoDB: угоди підставляємо свої.

Проганяє те, від чого залежить безпека: чи видно щось без входу, чи не пускає
чужий пароль, чи потрапляють у сторінку ЛИШЕ угоди своєї компанії, чи не тече
токен і внутрішні поля, чи можна забрати чужий файл, підмінивши адресу.

Запуск: python3 scripts/cabinet_test.py     (нічого не чіпає, все у тимчасовій теці)
Разом із браузерною перевіркою: bash scripts/check_cabinet.sh
"""
import http.cookiejar
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CABINET = os.path.join(HERE, os.pardir, "server", "cabinet.py")
TMP = tempfile.mkdtemp(prefix="cabtest-")
os.environ["CABINET_DB"] = os.path.join(TMP, "t.db")
os.environ["CABINET_SECRET"] = os.path.join(TMP, "t.secret")
os.environ["CABINET_LOG"] = os.path.join(TMP, "t.log")
os.environ["CABINET_INSECURE"] = "1"
spec = importlib.util.spec_from_file_location("cabinet", CABINET)
CAB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CAB)

ROWS = [
    {"Угода": "101", "Клієнт": "Мірандор", "Статус": "В морі", "Напрямок": "Імпорт",
     "Вид перевезення": "Море", "FCL/LCL": "FCL", "Маршрут": "Shanghai - Gdansk",
     "Лінія": "Maersk", "BL": "BL101", "HBL": "HBL101", "Контейнер": "MRKU1111111",
     "Судно": "MAERSK ATHABASCA", "Вояж": "512W", "ETD (факт)": "2026-07-01",
     "ETA": "2026-08-20", "Вантаж": "Меблі", "Кількість": "1x40'",
     "Коментар клієнту": "Все за планом",
     "Файли": [{"title": "[Лінійний коносамент] bl101.pdf", "path": "download/noco/a/bl101.pdf",
                "mimetype": "application/pdf"},
               {"title": "[Внутрішній] margin.xlsx", "path": "download/noco/a/margin.xlsx"}]},
    {"Угода": "102", "Клієнт": "мірандор  ", "Статус": "Вантаж доставлено",
     "Вид перевезення": "Авіа", "Маршрут": "Bangkok - Kyiv", "ETA": "2026-06-01",
     "Коментар клієнту": "Закрито </script><script>window.PWN=1</script>",
     "Файли": []},
    {"Угода": "103", "Клієнт": "Мірандор Плюс", "Статус": "В морі",
     "Маршрут": "Busan - Gdansk", "ETA": "2026-09-01", "Вантаж": "ЧУЖЕ",
     "Файли": [{"title": "[Рахунок] secret.pdf", "path": "download/noco/b/secret.pdf"}]},
    {"Угода": "104", "Клієнт": "Мірандор", "Статус": "Скасована",
     "Маршрут": "X - Y", "Файли": []},
]

CAB.BP.nc_all = lambda: ROWS
CAB.BP.logo = lambda: ""
FETCHED = []


class FakeResp:
    headers = {"Content-Type": "application/pdf"}

    def __init__(self, url):
        self.url = url

    def read(self):
        return b"%PDF-1.4 fake " + self.url.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_open(req, timeout=0):
    FETCHED.append(req.full_url)
    return FakeResp(req.full_url)


CAB.urllib.request.urlopen = fake_open
CAB.TOKEN_FILE = os.path.join(TMP, "t.token")
open(CAB.TOKEN_FILE, "w").write("faketoken")

CAB.init_db()
srv = ThreadingHTTPServer(("127.0.0.1", 0), CAB.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib за замовчуванням САМ іде за 303, і тоді в тесті видно 200 від
    сторінки входу замість самого перенаправлення. Нам потрібен код як є."""

    def redirect_request(self, *a, **k):
        return None


jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)
plain = urllib.request.build_opener(NoRedirect)

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (name, extra))


def get(path, opener=None, headers=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        r = (opener or op).open(req)
        return r.getcode(), r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


def post(path, data, opener=None, origin=True, headers=None):
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    if origin:
        h["Origin"] = BASE
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode(), headers=h)
    try:
        r = (opener or op).open(req)
        return r.getcode(), r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


print("\n=== 1. Без входу нічого не видно ===")
code, body, hdr = get("/")
check("головна дає форму входу", code == 200 and "Особистий кабінет" in body and "password" in body)
check("угод у сторінці входу немає", "MRKU1111111" not in body and "Мірандор" not in body)
check("є заборона вбудовування", hdr.get("X-Frame-Options") == "DENY")
check("є CSP з nonce", "nonce-" in (hdr.get("Content-Security-Policy") or ""))
code, body, _ = get("/doc/101/0")
check("файл без входу не віддається", code == 303 and not body.startswith("%PDF"), code)
code, body, _ = get("/health")
check("/health працює", code == 200 and body.strip() == "ok")
code, body, _ = get("/robots.txt")
check("robots.txt закриває індексацію", "Disallow: /" in body)

print("\n=== 2. Акаунти ===")
con = CAB.db()
con.execute("INSERT INTO accounts(email,client,name,pwd,active,must_change,created) "
            "VALUES(?,?,?,?,1,1,?)",
            ("ivan@m.ua", "Мірандор", "Іван", CAB.hash_pwd("temp-pass-1"), CAB.now()))
con.execute("INSERT INTO accounts(email,client,name,pwd,active,must_change,created) "
            "VALUES(?,?,?,?,1,0,?)",
            ("olga@mp.ua", "Мірандор Плюс", "Ольга", CAB.hash_pwd("olga-pass-99"), CAB.now()))
con.execute("INSERT INTO accounts(email,client,name,pwd,active,must_change,created) "
            "VALUES(?,?,?,?,0,0,?)",
            ("stop@m.ua", "Мірандор", "Блок", CAB.hash_pwd("stop-pass-99"), CAB.now()))
con.commit()
con.close()
check("хеш не містить пароля", "temp-pass-1" not in open(os.path.join(TMP, "t.db"), "rb").read().decode("latin1"))

print("\n=== 3. Вхід ===")
code, body, _ = post("/login", {"email": "ivan@m.ua", "password": "не той"})
check("невірний пароль → 401", code == 401, code)
check("не каже, чи є така пошта", "Пошта або пароль не підходять" in body)
code, body, _ = post("/login", {"email": "stop@m.ua", "password": "stop-pass-99"})
check("заблокований не входить", code == 401, code)
code, body, _ = post("/login", {"email": "ivan@m.ua", "password": "temp-pass-1"}, origin=False,
                     headers={"Origin": "https://evil.example"})
check("форма з чужого сайту відхилена", code == 403, code)

code, body, hdr = post("/login", {"email": "ivan@m.ua", "password": "temp-pass-1"})
check("правильний пароль пускає", code == 303, code)
sid_cookie = [c for c in jar if c.name == "cab_sid"]
check("кука HttpOnly", bool(sid_cookie) and sid_cookie[0].has_nonstandard_attr("HttpOnly"))
check("кука SameSite=Lax", "SameSite=Lax" in (hdr.get("Set-Cookie") or ""))
code, body, _ = get("/")
check("перший вхід просить змінити пароль", "Придумайте свій пароль" in body)
check("до зміни пароля угод не показує", "MRKU1111111" not in body)

print("\n=== 4. Зміна пароля ===")
code, body, _ = post("/password", {"old": "невірний", "new1": "новий-пароль-1", "new2": "новий-пароль-1"})
check("старий пароль перевіряється", code == 401, code)
code, body, _ = post("/password", {"old": "temp-pass-1", "new1": "abc", "new2": "abc"})
check("короткий пароль не приймається", code == 400 and "10 символів" in body)
code, body, _ = post("/password", {"old": "temp-pass-1", "new1": "довгий-пароль-1", "new2": "інший"})
check("незбіг паролів ловиться", code == 400 and "не збіглися" in body)
code, body, _ = post("/password", {"old": "temp-pass-1", "new1": "temp-pass-1", "new2": "temp-pass-1"})
check("новий = старий не приймається", code == 400, code)
code, body, _ = post("/password", {"old": "temp-pass-1", "new1": "мій-новий-пароль", "new2": "мій-новий-пароль"})
check("пароль змінено", code == 303, code)

print("\n=== 5. Кабінет показує ТІЛЬКИ свої угоди ===")
code, page, hdr = get("/")
check("сторінка кабінету відкрилась", code == 200 and "DEALS" in page)
data = json.loads(re.search(r"const DEALS = (\[.*?\]);\nconst TODAY", page, re.S).group(1)
                  .replace("<\\/", "</"))
deals = sorted(str(d.get("Угода")) for d in data)
check("угоди рівно свої (101,102)", deals == ["101", "102"], deals)
check("чужа угода 103 відсутня", "ЧУЖЕ" not in page and "Busan" not in page)
check("скасована 104 не показана", "104" not in deals)
check("назва компанії в шапці", "Мірандор" in page)
check("кнопка «Вийти» є", ">Вийти<" in page)
check("прапорець демо вимкнено", "const DEMO = false" in page)
check("внутрішній документ не потрапив", "margin.xlsx" not in page)
check("клієнтський документ є", "Лінійний коносамент" in page)
check("шляху у сховищі в сторінці немає", "download/noco" not in page)
check("«</script>» у коментарі знешкоджено", page.count("</script>") == 1, page.count("</script>"))
check("токен NocoDB не потрапив у сторінку", "faketoken" not in page)
for col in ("Менеджер", "Оп. менеджер", "Коментар\"", "Профіт", "Ставка"):
    check("внутрішнє поле «%s» не поїхало" % col, ('"%s"' % col) not in page)

print("\n=== 6. Документи ===")
code, blob, hdr = get("/doc/101/0")
check("свій документ віддається", code == 200 and blob.startswith("%PDF"), code)
check("віддається як файл", "attachment" in (hdr.get("Content-Disposition") or ""))
check("сервер сходив у сховище з токеном", any("bl101.pdf" in u for u in FETCHED))
code, blob, _ = get("/doc/103/0")
check("чужа угода → 404", code == 404, code)
check("чужий файл НЕ забрано зі сховища", not any("secret.pdf" in u for u in FETCHED))
code, _, _ = get("/doc/101/5")
check("неіснуючий номер → 404", code == 404, code)
code, _, _ = get("/doc/101/../../etc/passwd")
check("вихід із каталогу не проходить", code == 404, code)

print("\n=== 7. Вихід ===")
code, body, _ = post("/logout", {"_csrf": "підроблено"})
check("чужа мітка форми не приймається", code == 403, code)
csrf = re.search(r'name="_csrf" value="([^"]+)"', page).group(1)
code, body, _ = post("/logout", {"_csrf": csrf})
check("вихід спрацював", code == 303, code)
code, body, _ = get("/")
check("після виходу знову форма входу", "Пароль" in body and "MRKU1111111" not in body)

print("\n=== 8. Підбір пароля ===")
for i in range(6):
    code, body, _ = post("/login", {"email": "olga@mp.ua", "password": "хиба%d" % i}, opener=plain)
check("після 5 спроб блокує (429)", code == 429, code)
code, body, _ = post("/login", {"email": "olga@mp.ua", "password": "olga-pass-99"}, opener=plain)
check("правильний пароль теж чекає паузи", code == 429, code)

print("\n=== 9. Журнал ===")
con = CAB.db()
acts = [r["action"] for r in con.execute("SELECT action FROM audit ORDER BY id")]
con.close()
for a in ("вхід", "невдалий вхід", "перегляд", "завантажив документ", "вихід",
          "пароль змінено", "відмова у файлі"):
    check("у журналі є «%s»" % a, a in acts)
logtext = open(os.path.join(TMP, "t.log")).read()
for bad in ("temp-pass-1", "мій-новий-пароль", "olga-pass-99", "faketoken"):
    check("у журнал не потрапив секрет «%s»" % bad[:12], bad not in logtext)

print("\n%s  ok=%d  FAIL=%d" % ("ПЕРЕВІРКА ПРОЙДЕНА" if not FAIL else "Є ПОМИЛКИ", OK, FAIL))
srv.shutdown()
sys.exit(1 if FAIL else 0)
