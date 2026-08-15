#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прошарок між фасадом і NocoDB: права перевіряються НА СЕРВЕРІ.

НАВІЩО. Сьогодні обмеження прав існує лише як фільтр `scoped()` у браузері
(www/index.html, рядки 1012-1017). Це не захист, а зручність показу: сторінка
сама вирішує, що намалювати, а дані їй віддають ВСІ. Будь-хто, хто вміє
відкрити інструменти розробника, може написати в консолі

    await api("/api/v2/tables/<таблиця>/records?limit=1000")

і отримати чужі угоди й калькуляції. Перевірено на сервері 10.08.2026: у NocoDB
прав на таблицю/рядок/колонку немає взагалі (HTTP 404 на відповідних адресах),
а `v.pontus@unitex.od.ua` має роль `editor` — читання і запис УСІХ таблиць.

ЧОМУ ПРОШАРОК, А НЕ ІНШИЙ КОНСТРУКТОР. Усі п'ять дірок NocoDB (права на рядок,
журнал змін, версії записів, власні ролі, перевірка перед записом) відсутні з
ОДНІЄЇ причини: у нього немає точки входу в шлях запиту. Прошарок нею і є.
Рішення користувачки 11.08.2026 після порівняння з Directus і Supabase.

ЩО ЦЕ ФІЗИЧНО. Маленький HTTP-сервер, який слухає 127.0.0.1:8792 і переказує
запити в NocoDB (127.0.0.1:8080). Ставиться ПОРУЧ і нічого не ламає: доки
маршрут `/api/*` у Caddy дивиться на 8080, прошарок просто стоїть без роботи.
Перехід — зміна ОДНОГО поля upstream у конфізі Caddy, відкат — те саме назад.

ПРАВИЛА НЕ ВИГАДАНІ. Вони переписані з фасада один в один:
    таблиця RC     (www/index.html) → ROLE_TABLES і ROLE_EDIT нижче
    функція scoped (www/index.html) → SCOPE_FIELD нижче
Якщо правило тут розійдеться з фасадом — правильним вважати фасад, бо саме він
показує користувачці те, що вона очікує побачити.

РЕЖИМ РОБОТИ — такий самий, як у server/authcheck.py, і з тієї ж причини.
ENFORCE = False: перевірка рахується і пишеться в журнал, але НІКОГО НЕ БЛОКУЄ.
Вмикати блокування тільки тоді, коли в журналі буде видно, що законні запити
проходять. 08.08.2026 цей підхід уже дав відповідь по authcheck: 323 записи,
249 пропущено (усі з реальною роллю), 37 відмовило б (усі «роль невідома»).

Запуск: python3 /root/gateway.py       (порт міняється через GATEWAY_PORT)
Журнал: /root/gateway.log
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NC = "http://127.0.0.1:8080"
PORT = int(os.environ.get("GATEWAY_PORT", "8792"))
TOKEN_FILE = "/root/nocodb-token.txt"
USERS_T = "meqpi0r197bz14n"
LOG_FILE = os.environ.get("GATEWAY_LOG", "/root/gateway.log")

# ⚠️ ПОКИ ЩО ТІЛЬКИ ДИВИМОСЬ. Перемикати на True одним словом, коли журнал
# покаже, що законні запити проходять. Див. пояснення у шапці файла.
ENFORCE = os.environ.get("GATEWAY_ENFORCE", "") == "1"

# ── таблиці бази (перевірено читанням 11.08.2026) ─────────────────────────
TABLES = {
    "m58xsjo6at01ohl": "Диспетчеризація",
    "mgik03ijqyyct6v": "Клієнти",
    "mfo372vhs3fbbw7": "Задачі",
    "meqpi0r197bz14n": "Користувачі",
    "mvm5xu2mcidt1j3": "Інструкції",
    "mxtg3fvrmtflaid": "Калькуляції",
    "m429u2crlavfmxc": "Журнал дій",
}

# ── які таблиці видно якій ролі ───────────────────────────────────────────
# Переписано з поля nav таблиці RC у фасаді:
#   calc → Калькуляції, clients → Клієнти, tasks → Задачі,
#   dispatch → Диспетчеризація, instr → Інструкції, users → Користувачі.
# «Журнал дій» у nav немає ЖОДНОЇ ролі — його читає лише адміністратор.
# Сторінки «Фінанси» і «Бухгалтерія» сюди не входять свідомо: вони беруть дані
# не з таблиць, а з /finrep-data, і їх уже прикриває findata.py.
_BASE = {"Диспетчеризація", "Клієнти", "Задачі", "Користувачі", "Інструкції"}
ROLE_TABLES = {
    "Адміністратор":        _BASE | {"Калькуляції", "Журнал дій"},
    "Сейлз-менеджер":       _BASE | {"Калькуляції"},
    "Бухгалтер":            _BASE | {"Калькуляції"},
    # У фінансиста в nav немає ні dispatch, ні calc (рішення користувачки
    # 11.08.2026), тож «Калькуляції» йому не належать. «Диспетчеризація»
    # ЛИШАЄТЬСЯ попри прибрану сторінку: «Бух. облік» читає звідти маршрут,
    # коносамент і контейнер і пише туди позначку переказу (див. MARK_ROLES).
    "Фінансист":            _BASE,
    "Операційний менеджер": _BASE,                       # у nav немає calc
    "Логіст":               {"Диспетчеризація", "Інструкції", "Користувачі"},
    "Перегляд":             _BASE | {"Калькуляції"},
}

# ── кому дозволено ЗМІНЮВАТИ (поле edit у RC) ─────────────────────────────
ROLE_EDIT = {"Адміністратор", "Сейлз-менеджер", "Операційний менеджер", "Логіст"}

# ── вузький виняток: галочка «переказано» ─────────────────────────────────
# Бухгалтер і Фінансист права редагування НЕ мають (у RC немає edit), але на
# сторінці «Бух. облік» ставлять позначку переказу за кордон — у фасаді це окрема
# умова `canMark` (fin === "acct" || "full"), і пише вона в таблицю угод.
# Без цього винятку прошарок, коли ми його ввімкнемо, заблокував би саме те,
# заради чого роль «Фінансист» і заводили.
# Прошарок тут СУВОРІШИЙ за фасад: дозволені рівно три колонки. Фасад більше й не
# просить, але браузер може попросити що завгодно — і ось це вже не пройде.
MARK_ROLES = {"Бухгалтер", "Фінансист"}
MARK_FIELDS = {"Id", "Переказ за кордон", "Дата переказу", "Сума переказу"}

# ── третій виняток: бухгалтер прикріплює файли до угоди ───────────────────
# Дозвіл користувачки 15.08.2026 («дозволь»). Бухгалтер угоди не редагує, але
# доносить до них акти й рахунки, а прикріплення ПИШЕ в колонку «Файли».
# Дозволено рівно дві колонки і рівно PATCH: ні статус, ні дати, ні суми цим
# шляхом не пройдуть. У фасаді той самий перелік — ATTACH_ROLES (www/app/main.js):
# фасад ховає кнопку, прошарок стереже сам запис.
FILE_ROLES = {"Бухгалтер"}
FILE_FIELDS = {"Id", "Файли"}

# ── другий виняток: задачі ────────────────────────────────────────────────
# Розділ «Задачі» є в nav У ВСІХ ролей, окрім «Логіста». Правило ROLE_EDIT
# описує право правити УГОДИ — бухгалтер і фінансист його не мають і мати не
# повинні. Але свої задачі вони ставлять і закривають самі, інакше розділ для
# них марний: подивитись можна, відмітити виконане — ні.
# Це те саме рішення, що й у фасаді (функція canTask): задачі веде кожен, хто
# бачить розділ, окрім ролі «Перегляд» — вона на те й «перегляд».
# Обмеження за колонками тут НЕМАЄ свідомо: у таблиці задач немає полів, які
# були б чутливі самі по собі (там текст, дата, статус і виконавці).
TASK_DENY = {"Перегляд", "Логіст"}

# ── чиї задачі видно ──────────────────────────────────────────────────────
# Рішення користувачки 12.08.2026: «адмін бачить всі задачі, інші ролі — тільки
# свої». «Свої» = я виконавець АБО я поставила задачу (інакше керівник підрозділу
# не бачив би того, що сам доручив).
# Зіставляємо по EMAIL, а не по імені: у довіднику двоє людей з ім'ям «Ірина»,
# і зіставлення по імені показало б одній чужі задачі. Саме тому тут окремий
# фільтр, а не звичайний SCOPE_FIELD — той порівнює одне поле з іменем.
TASK_SEE_ALL = {"Адміністратор"}
TASK_SCOPE = "Виконавці/Постановник"      # позначка для журналу і для _pass()

# ── чиї рядки видно (функція scoped у фасаді) ─────────────────────────────
# mgr → бачить угоди, де він «Менеджер»; ops → де він «Оп. менеджер».
# Калькуляції менеджер теж бачить тільки свої (рядок 3877 фасада).
ROLE_SCOPE = {"Сейлз-менеджер": "mgr", "Операційний менеджер": "ops"}
SCOPE_FIELD = {
    ("mgr", "Диспетчеризація"): "Менеджер",
    ("mgr", "Калькуляції"): "Менеджер",
    ("ops", "Диспетчеризація"): "Оп. менеджер",
}

# Довідники, які видно цілком навіть тим, хто обмежений своїми рядками:
# без них сторінка просто не збереться (списки клієнтів, інструкції, колеги).
# «Задачі» ЗВІДСИ ПРИБРАНІ 12.08.2026 — у них тепер власне правило (TASK_SEE_ALL).
SCOPE_FREE = {"Клієнти", "Інструкції", "Користувачі"}

CACHE_SEC = 60
_who = {}          # ключ сесії -> (email, ім'я, роль, коли)
_TOK = None


def _tok():
    global _TOK
    if _TOK is None:
        _TOK = open(TOKEN_FILE).read().strip()
    return _TOK


def log(line):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (stamp, line))
    except Exception:  # noqa: BLE001
        pass
    print("GATEWAY %s" % line, flush=True)


def whoami(jwt):
    """(email, ім'я, роль) за ключем сесії. Роль None — визначити не вдалося.

    Кеш на 60 секунд, як в authcheck.py: інакше кожен запит фасада тягнув би
    ще два запити в NocoDB, і сторінка помітно сповільнилась би.
    """
    if not jwt:
        return None, None, None
    hit = _who.get(jwt)
    if hit and time.time() - hit[3] < CACHE_SEC:
        return hit[0], hit[1], hit[2]
    try:
        r = urllib.request.Request(NC + "/api/v1/auth/user/me", headers={"xc-auth": jwt})
        with urllib.request.urlopen(r, timeout=10) as resp:
            email = (json.loads(resp.read().decode()).get("email") or "").lower()
    except urllib.error.HTTPError as e:
        return None, None, ("__EXPIRED__" if e.code in (401, 403) else None)
    except Exception:  # noqa: BLE001
        return None, None, None
    try:
        r2 = urllib.request.Request(NC + "/api/v2/tables/%s/records?limit=1000" % USERS_T,
                                    headers={"xc-token": _tok()})
        with urllib.request.urlopen(r2, timeout=10) as resp:
            users = json.loads(resp.read().decode()).get("list", [])
    except Exception:  # noqa: BLE001
        return None, None, None
    row = next((u for u in users
                if str(u.get("Email") or "").lower() == email
                and u.get("Активний") is not False), None)
    if not row:
        return email, None, None
    name = str(row.get("Ім'я") or "").strip()
    role = row.get("Роль")
    _who[jwt] = (email, name, role, time.time())
    return email, name, role


def table_of(path):
    """Ід таблиці з адреси /api/v2/tables/<id>/records[...]. None — не про таблиці."""
    parts = [p for p in urllib.parse.urlparse(path).path.split("/") if p]
    if len(parts) >= 4 and parts[:3] == ["api", "v2", "tables"]:
        return parts[3]
    return None


def payload_fields(payload):
    """Які колонки просять змінити. None — розібрати не вдалося (тоді це «ні»)."""
    if not payload:
        return set()
    try:
        js = json.loads(payload.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    recs = js if isinstance(js, list) else [js]
    out = set()
    for r in recs:
        if not isinstance(r, dict):
            return None
        out |= set(r.keys())
    return out


def decide(method, path, role, name, fields=None, email=None):
    """Чи можна. Повертає (дозволено, причина, поле_обмеження або None).

    Свідомо fail-closed: невідома роль, невідома таблиця, невідомий метод —
    це «ні». Мовчазний дозвіл у сумнівному випадку — саме те, через що дірка
    існувала весь цей час.
    """
    tid = table_of(path)
    if tid is None:
        return True, "не запит до таблиці", None          # /api/v1/auth/*, /storage/* тощо
    tname = TABLES.get(tid)
    if tname is None:
        return False, "невідома таблиця %s" % tid, None
    if role in (None, "__EXPIRED__"):
        return False, "роль невідома", None
    allowed = ROLE_TABLES.get(role)
    if allowed is None:
        return False, "невідома роль «%s»" % role, None
    if tname not in allowed:
        return False, "роль «%s» не має доступу до «%s»" % (role, tname), None
    if method not in ("GET", "HEAD"):
        if role not in ROLE_EDIT:
            # виняток перший — свої задачі (створити, змінити; видалення НЕ даємо)
            task_ok = (tname == "Задачі" and role not in TASK_DENY
                       and method in ("POST", "PATCH"))
            # виняток другий — позначка переказу за кордон, і тільки PATCH
            mark_ok = (role in MARK_ROLES and tname == "Диспетчеризація"
                       and method == "PATCH")
            file_ok = (role in FILE_ROLES and tname == "Диспетчеризація"
                       and method == "PATCH")
            if not (task_ok or mark_ok or file_ok):
                return False, "роль «%s» не може змінювати дані" % role, None
            if mark_ok or file_ok:   # task_ok сюди не потрапляє — це інша таблиця
                if fields is None:
                    return False, "не вдалося розібрати, що саме змінюють", None
                # дозволене — це об'єднання винятків, які має саме ця роль
                allowed_fields = set()
                if mark_ok:
                    allowed_fields |= MARK_FIELDS
                if file_ok:
                    allowed_fields |= FILE_FIELDS
                extra = fields - allowed_fields
                if extra:
                    return False, ("роль «%s» може міняти лише %s, а не %s"
                                   % (role, ", ".join(sorted(allowed_fields)),
                                      ", ".join(sorted(extra))[:80])), None
        if tname == "Журнал дій" and method == "DELETE":
            return False, "журнал дій не видаляється", None
    # Задачі: адміністратор бачить усі, решта — лише свої (12.08.2026).
    if tname == "Задачі" and method in ("GET", "HEAD") and role not in TASK_SEE_ALL:
        if not email:
            # обмеження є, а зіставляти нема з чим — це «ні», а не «пропустити»
            return False, "не вдалося визначити пошту, обмежити нема по чому", None
        return True, "дозволено, лише свої задачі", TASK_SCOPE
    scope = ROLE_SCOPE.get(role)
    if not scope or tname in SCOPE_FREE:
        return True, "дозволено", None
    field = SCOPE_FIELD.get((scope, tname))
    if not field:
        return True, "дозволено", None
    if not name:
        # обмеження є, а зіставляти нема з чим — це «ні», а не «пропустити»
        return False, "у довіднику не заповнене ім'я, обмежити нема по чому", None
    return True, "дозволено, лише свої", field


def scope_rows(body, field, name):
    """Прибрати з відповіді чужі рядки. Формат — той самий, що віддає NocoDB."""
    try:
        js = json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return body, 0, 0
    if not isinstance(js, dict) or not isinstance(js.get("list"), list):
        return body, 0, 0
    was = len(js["list"])
    js["list"] = [r for r in js["list"] if str(r.get(field) or "").strip() == name]
    return json.dumps(js, ensure_ascii=False).encode("utf-8"), was, len(js["list"])


def my_task(row, email):
    """Чи ця задача моя: я серед виконавців або я її поставила.

    «Виконавці» — пошти через кому (так вирішено у фасаді: у довіднику двоє
    людей з ім'ям «Ірина», тому ключем може бути тільки пошта).
    """
    doers = [x.strip().lower() for x in str(row.get("Виконавці") or "").split(",")]
    return email in doers or str(row.get("Постановник") or "").strip().lower() == email


def scope_tasks(body, email):
    """Лишити лише свої задачі. Окремо від scope_rows: там одне поле = ім'я,
    а тут два поля і список пошт усередині одного з них."""
    try:
        js = json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return body, 0, 0
    if not isinstance(js, dict) or not isinstance(js.get("list"), list):
        return body, 0, 0
    was = len(js["list"])
    js["list"] = [r for r in js["list"] if my_task(r, (email or "").lower())]
    return json.dumps(js, ensure_ascii=False).encode("utf-8"), was, len(js["list"])


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):      # свій журнал, стандартний не потрібен
        pass

    def _pass(self, method):
        jwt = self.headers.get("xc-auth") or ""
        email, name, role = whoami(jwt)

        # Тіло читаємо ДО рішення: щоб перевірити, які саме колонки міняють,
        # його треба вже мати. Прочитати його потім не можна — потік уже вичерпано.
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length) if length else None

        ok, why, field = decide(method, self.path, role, name,
                                payload_fields(payload), email)

        who = email or "невідомий"
        if not ok:
            log("%s %s · %s · роль=%s · %s%s"
                % (method, self.path[:110], who, role or "—", why,
                   "" if ENFORCE else "  [ТІЛЬКИ ДИВЛЮСЬ, пропускаю]"))
            if ENFORCE:
                return self._json(403, {"error": "Немає прав: %s" % why})

        req = urllib.request.Request(NC + self.path, data=payload, method=method)
        for h in ("xc-auth", "xc-token", "Content-Type", "Accept"):
            if self.headers.get(h):
                req.add_header(h, self.headers[h])
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                code, body = resp.getcode(), resp.read()
                ctype = resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read()
            ctype = e.headers.get("Content-Type", "application/json")
        except Exception as e:  # noqa: BLE001
            log("НЕ ДІЙШЛО до NocoDB: %s" % str(e)[:120])
            return self._json(502, {"error": "база не відповідає"})

        if ok and field and method == "GET" and code == 200:
            # ВАЖЛИВО: рахуємо на копії. У режимі «тільки дивлюсь» віддати треба
            # ВИХІДНЕ тіло, а не обрізане, інакше це вже блокування, просто без
            # напису про нього — і сторінка мовчки показала б менше угод.
            trimmed, was, now = (scope_tasks(body, email) if field == TASK_SCOPE
                                 else scope_rows(body, field, name))
            if was != now:
                log("%s %s · %s · показано %d з %d (лише свої, поле «%s»)%s"
                    % (method, self.path[:80], who, now, was, field,
                       "" if ENFORCE else "  [ТІЛЬКИ ДИВЛЮСЬ, віддаю все]"))
            if ENFORCE:
                body = trimmed
        self._raw(code, ctype, body)

    def _raw(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._raw(code, "application/json", json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):
        self._pass("GET")

    def do_POST(self):
        self._pass("POST")

    def do_PATCH(self):
        self._pass("PATCH")

    def do_DELETE(self):
        self._pass("DELETE")


if __name__ == "__main__":
    log("старт на 127.0.0.1:%d · режим: %s"
        % (PORT, "БЛОКУЄ" if ENFORCE else "тільки дивлюсь"))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
