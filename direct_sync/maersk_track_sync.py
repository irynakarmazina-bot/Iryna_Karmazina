#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Трекінг Maersk → платформа (NocoDB «Диспетчеризація») НАПРЯМУ, без Google-таблиці.

Портовано з n8n-воркфлоу «Container Tracking — Maersk (CRM)» (id JQKA35haUsXU4XqE,
вимкнений 30.07.2026): та сама логіка відбору, розбору подій і 8-модель статусів,
але замість читання/запису майстер-таблиці — читання й запис прямо в NocoDB.

Що пише: Судно, Вояж, ETA порт (план/факт), ETA, Статус, Контейнер (лінія), Звірка,
Зміни ETA (історія), Остання зміна, Останнє оновлення.
Чого не робить: не чіпає угоди зі статусом «Вантаж доставлено» (заморожені),
не стирає заповнені значення порожніми, нічого не видаляє.

Секрети: /root/direct-sync/secure/maersk.env (600) — MAERSK_CONSUMER_KEY,
MAERSK_CLIENT_ID, MAERSK_CLIENT_SECRET. У репозиторій і в логи не потрапляють.

Запуск: python3 /root/direct-sync/maersk_track_sync.py [--dry-run] [--limit N] [--all]
Лог:    /root/direct-sync/maersk.log
"""
import argparse
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

WORKDIR = "/root/direct-sync"
ENV_FILE = os.path.join(WORKDIR, "secure", "maersk.env")
LOG = os.path.join(WORKDIR, "maersk.log")

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOKEN_FILE = "/root/nocodb-token.txt"
CHUNK = 25

TOKEN_URL = "https://api.maersk.com/customer-identity/oauth/v2/access_token"
EVENTS_URL = "https://api.maersk.com/track-and-trace-private/events"
EVENTS_URL_PUBLIC = "https://api.maersk.com/track-and-trace/events"
THROTTLE = 1.5          # пауза між запитами до Maersk (у воркфлоу ловили 429)
RETRIES = 3

BL_RE = re.compile(r"^\d{9}$")
CONT_RE = re.compile(r"^[A-Z]{4}\d{7}$")   # ISO-номер контейнера, напр. MRSU8851528
DELIVERED = "Вантаж доставлено"
# Прибуття судна в порт — окремий статус (рішення користувачки 05.08.2026).
# Доти подія ARRI на судні давала «В морі», і вантаж, який уже стоїть у порту,
# показувався як такий, що пливе. Саме це вона побачила на угоді 256.
# Перейменовано 11.08.2026 з «Прибув у порт» (рішення користувачки 10.08.2026):
# стара назва не казала, в ЯКОМУ порту вантаж, і плуталась з «В порту відправлення».
# Перед перейменуванням перевірено читанням бази: старий варіант не стояв у жодної
# з 277 угод, тому жодного запису правити не довелось.
ARRIVED = "В порту призначення"
# Заїзд контейнера у ворота порту ВІДПРАВЛЕННЯ (додано 10.08.2026, див. GTIN нижче).
IN_POL = "В порту відправлення"
# Вивантаження з судна в порту призначення.
DISCHARGED = "Вивантажений в порту прибуття"
# «Гейт аут» — НЕ статус, а ДАТА-колонка (вивіз з порту прибуття): уточнення
# користувачки 25.08.2026 «цей статус не потрібний». Послідовність статусів
# залізничного хвоста: «Завантажений на потяг» → «Вивантажений в сухому порту»
# → «Вантаж доставлено».
DRY_PORT = "Вивантажений в сухому порту"   # прибув/вивантажений у сухому порту
# Вантаж на ПЕРЕВАЛЦІ: судно прийшло і його вивантажили, але це не кінець шляху —
# попереду ще одне морське плече. Доданий 11.08.2026 після угоди 238 (Бусан →
# Гданськ через Танджунг Пелепас і Вільгельмсгафен): 07.08 контейнер вивантажили
# у Вільгельмсгафені, і платформа показала «Вивантажений в порту прибуття», хоча
# до Гданська лишалось два тижні й ще один рейс. Трекінг перевалку РОЗРІЗНЯВ, але
# називав тим самим статусом — тобто розрізнення нічого не давало.
TRANSSHIP = "В порту перевалки"
# Умови поставки, за яких наша відповідальність закінчується ТІЛЬКИ після фінальної
# доставки авто, а не в порту призначення. Список — вибір користувачки 02.08.2026
# (той самий, що й на схемі кабінету клієнта, див. direct_sync/add_incoterms.py).
# DDU скасований редакцією Incoterms 2010, але в договорах досі трапляється.
# DDP і DPU сюди СВІДОМО не внесені: користувачка назвала саме DAP і DDU. Якщо
# їх теж треба рахувати «до дверей» — це рішення людини, а не моя здогадка.
DOOR_TERMS = {"DAP", "DDU"}
INCOTERMS_FIELD = "Умови поставки (Інкотермс)"
# Хто поставив статус. Автомат перебиває лише те, що поставив автомат:
# якщо в колонці «Статус (джерело)» стоїть «людина», трекінг статус не чіпає.
STATUS_SRC = "трекінг Maersk"
HUMAN_SRC = "людина"
# Колонка з датою, коли статус востаннє поставили (її ж пише фасад при ручній правці).
STATUS_WHEN = "Статус (оновлено)"


def _fact_newer_than_human(row, last_dt):
    """Чи має Maersk ФАКТ, датований ПІЗНІШЕ, ніж людина поставила статус.

    Навіщо (рішення користувачки 16.08.2026, варіант «А»). Правило «статус
    поставила людина — автомат мовчить» (05.08.2026) захищало ручні правки, але
    робило їх ВІЧНИМИ. Живий випадок, з якого це й випливло: угода 260 —
    13.08 людина поставила «В порту відправлення» (і тоді це була правда),
    14.08 судно вийшло, Maersk записав фактичний ETD, а статус так і лишився
    «В порту відправлення», бо автомат не мав права його чіпати. Позначка
    «застаріло» теж не спрацьовувала: вона дивиться на дату прибуття (15.10).

    Тепер захист діє, доки факт не свіжіший за ручну правку. Порівнюємо ДАТИ, а
    не час: людина ставить статус кнопкою (пишеться лише день), тому порівняння
    з точністю до секунди було б несправедливим до неї.
    Якщо дати рівні — лишаємо перевагу ЛЮДИНІ: у той самий день вона бачила те
    саме, що й трекінг, і вирішила інакше.
    Якщо якоїсь із дат немає — теж перевага людині: без порівняння не перебиваємо.
    """
    human_when = str(row.get(STATUS_WHEN) or "")[:10]
    fact_when = str(last_dt or "")[:10]
    if not human_when or not fact_when:
        return False
    return fact_when > human_when
# Статус «Завантажений» РОЗДІЛЕНИЙ на авто і потяг (рішення користувачки 30.07.2026):
# у колонці «Статус» є варіанти «Завантажений на авто» і «Завантажений на потяг»,
# старий об'єднаний «Завантажений на авто/потяг» прибрано на її прохання
# (жоден запис його не використовував; бекап варіантів — status_options.bak.json).
# Читаємо з платформи ВСІ колонки, які потім пишемо, інакше порівняння «старе != нове»
# завжди істинне і скрипт переписує ті самі значення щопрогону. Саме так було до
# 01.08.2026 з «Гейт ін», «Гейт аут», «ETD (факт)/(план)» і «Вивантаження в порту (факт)»:
# лог показував 156 «змін» при нулі нових даних.
# «Напрямок» читаємо не для запису, а для ЛОГІКИ: від нього залежить, яке судно
# показувати для експорту (перше плече, а не останнє) — див. рядок з is_export.
# Помилка 02.08.2026: поле використовувалось, але сюди додати забули, тому воно
# завжди приходило порожнім, кожна угода вважалась імпортом, і виправлення
# «експорт → перше судно» не діяло взагалі.
READ_FIELDS = ["Id", "Угода", "Напрямок", "BL", "Контейнер", "Контейнер (лінія)", "ETA",
               "ETA порт (план)", "ETA порт (факт)", "Статус", "Судно", "Вояж",
               "Зміни ETA (історія)", "Звірка", "Лінія",
               "Гейт ін", "Гейт аут", "ETD (факт)", "ETD (план)",
               "Вивантаження в порту (факт)", "ETA сухий порт", "Вид перевезення",
               # 31.08.2026: читаємо для перевірки ПОСЛІДОВНОСТІ дат (див. CHAIN
               # у parse_events) — якщо поля тут немає, воно приходить порожнім
               # і перевірка його не бачить (граблі 02.08 з «Напрямком»)
               "Вивантаження у отримувача (факт)",
               "Порт перевалки", "Перевалка (прибуття)", "Перевалка (відправлення)",
               "Остання зміна", "Останнє оновлення",
               # 05.08.2026: джерело статусу і стан трекінгу — див. STATUS_SRC нижче
               "Статус (джерело)", "Статус (оновлено)", "Трекінг (стан)",
               # 11.08.2026: умови поставки читаємо для ЛОГІКИ, не для запису —
               # від них залежить, де закінчується перевезення (див. DOOR_TERMS).
               # Та сама пастка вже була з «Напрямком» 02.08.2026: поле
               # використовувалось у логіці, але сюди його додати забули, тому воно
               # завжди приходило порожнім і виправлення не діяло взагалі.
               INCOTERMS_FIELD]


def cancelled_numbers():
    """Номери скасованих угод (файл пише expeditor_direct_sync.py) — їх не трекаємо."""
    path = os.path.join(WORKDIR, "cancelled.json")
    try:
        return {str(x) for x in json.load(open(path, encoding="utf-8"))}
    except Exception:  # noqa: BLE001
        return set()


def deal_no(v):
    s = str(v or "").strip()
    try:
        return str(int(s))
    except ValueError:
        return s


def log(msg):
    line = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(msg, flush=True)


def load_env():
    env = {}
    with open(ENV_FILE, encoding="utf-8") as f:
        for ln in f:
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.strip().split("=", 1)
                env[k.strip()] = v.strip()
    missing = [k for k in ("MAERSK_CONSUMER_KEY", "MAERSK_CLIENT_ID", "MAERSK_CLIENT_SECRET")
               if not env.get(k)]
    if missing:
        raise SystemExit("немає секретів: %s" % ", ".join(missing))
    return env


# ---------------------------------------------------------------- NocoDB
# Токен читаємо, ЯКЩО файл є. Було безумовне open() — і модуль неможливо було
# навіть імпортувати там, де секрета немає (машина розробки, перевірки). Через це
# логіку статусів не можна було перевірити інакше, ніж прогоном по живій базі.
# Порожній токен не «тихо працює»: nc() нижче одразу каже, чого бракує.
TOK = open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else ""


def nc(method, path, data=None):
    if not TOK:
        return 0, {"err": "немає токена NocoDB: файл %s не знайдено" % TOKEN_FILE}
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(NC + path, data=body, method=method,
                                 headers={"Content-Type": "application/json", "xc-token": TOK})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"err": e.read().decode()[:300]}
    except Exception as e:  # noqa: BLE001
        return 0, {"err": str(e)[:300]}


def nc_status_options():
    """Дозволені варіанти колонки «Статус» — щоб не завалити запис невідомим значенням."""
    st, js = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        return set()
    col = next((c for c in js["columns"] if c["title"] == "Статус"), None)
    if not col:
        return set()
    return {o["title"] for o in (col.get("colOptions") or {}).get("options", [])}


def nc_records():
    out, off = [], 0
    q = urllib.parse.quote(",".join(READ_FIELDS), safe=",")
    while True:
        st, js = nc("GET", "/api/v2/tables/%s/records?limit=200&offset=%d&fields=%s" % (TABLE, off, q))
        if st != 200:
            raise SystemExit("READ_FAIL %s %s" % (st, js))
        out += js.get("list", [])
        if js.get("pageInfo", {}).get("isLastPage"):
            return out
        off += 200


# ---------------------------------------------------------------- Maersk API
def maersk_token(env):
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": env["MAERSK_CLIENT_ID"],
        "client_secret": env["MAERSK_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
        "Consumer-Key": env["MAERSK_CONSUMER_KEY"],
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        js = json.loads(r.read().decode())
    tok = js.get("access_token")
    if not tok:
        raise SystemExit("MAERSK_TOKEN_FAIL: у відповіді немає access_token")
    return tok


def maersk_events(env, token, value, param="transportDocumentReference", url=EVENTS_URL):
    """Події по букінгу або по номеру контейнера. Повертає (events|None, note)."""
    q = urllib.parse.urlencode({param: value})
    req = urllib.request.Request(url + "?" + q, headers={
        "Consumer-Key": env["MAERSK_CONSUMER_KEY"],
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
    })
    delay = 2
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                js = json.loads(r.read().decode() or "{}")
            body = js.get("body", js) if isinstance(js, dict) else js
            events = body.get("events") if isinstance(body, dict) else None
            if events is None and isinstance(js, list):
                events = js
            return events, ""
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < RETRIES - 1:
                time.sleep(delay)
                delay *= 2
                continue
            if e.code == 404:
                return None, "404 немає даних"
            return None, "HTTP %d" % e.code
        except Exception as e:  # noqa: BLE001
            return None, str(e)[:80]
    return None, "429 (ліміт запитів)"


# ---------------------------------------------------------------- розбір подій
def collect_events(env, token, bl, container):
    """Усі події по відправці: спершу по КОНОСАМЕНТУ (віддає більше, ніж букінг),
    потім домішуємо по букінгу, і лише якщо нічого — по номеру контейнера.
    Повертає (події, як_знайшли, нота)."""
    found, seen, how = [], set(), []

    def add(evs):
        new = 0
        for e in evs or []:
            k = e.get("eventID") or json.dumps(e, sort_keys=True, ensure_ascii=False)[:200]
            if k not in seen:
                seen.add(k)
                found.append(e)
                new += 1
        return new

    note = ""
    for param, value, label in (("transportDocumentReference", bl, "коносамент"),
                                ("carrierBookingReference", bl, "букінг")):
        evs, n = maersk_events(env, token, value, param)
        note = note or n
        if add(evs):
            how.append(label)
        time.sleep(THROTTLE)
    if not found and container:
        evs, n = maersk_events(env, token, container, "equipmentReference")
        note = note or n
        if add(evs):
            how.append("контейнер")
        time.sleep(THROTTLE)
    return found, "+".join(how), note


def _dt(e):
    return str(e.get("eventDateTime") or "")


def vessel_move_after(events, ts):
    """Чи є ПІСЛЯ моменту ts ще завантаження або відхід судна (хоч планові).

    Це єдина ознака, за якою відрізняється ПЕРЕВАЛКА від порту призначення.
    Раніше для цього використовувалось «останнє вивантаження = призначення», і
    воно ламається у звичайнісінькому випадку: Maersk публікує вивантаження в
    порту призначення лише коли воно станеться. До того моменту останнім
    вивантаженням є перевалка — і саме вона помилково вважалась кінцем шляху.
    Перевірено на угоді 238 (11.08.2026): події — вивантаження в Танджунг
    Пелепас 29.06, вивантаження у Вільгельмсгафені 07.08, далі ПЛАНОВІ відхід
    20.08 і прибуття в Гданськ 23.08. Вивантаження в Гданську серед подій немає
    взагалі, тому Вільгельмсгафен ставав «портом прибуття».
    """
    for e in events:
        c = (e.get("transportEventTypeCode") or e.get("equipmentEventTypeCode") or "")
        m = (e.get("transportCall") or {}).get("modeOfTransport") or ""
        if c in ("LOAD", "DEPA") and m == "VESSEL" and _dt(e) > ts:
            return True
    return False


def bl_from_events(events):
    """Коносамент, який Maersk віддає в самих подіях. Потрібен, коли ми знайшли
    відправку по номеру контейнера, а поля BL в угоді не було (прохання
    користувачки 31.07.2026 — «додати коносамент з сайту»)."""
    for e in events:
        v = str(e.get("transportDocumentReference") or "").strip()
        if BL_RE.match(v):
            return v
        for dr in (e.get("documentReferences") or []):
            t = str(dr.get("documentReferenceType") or "").upper()
            val = str(dr.get("documentReferenceValue") or "").strip()
            if t in ("TRD", "BL", "BOL") and BL_RE.match(val):
                return val
    return ""


def parse_events(events, row, today_iso, statuses=frozenset()):
    """Портована логіка вузла «Розбір». Повертає {колонка: значення}."""
    out = {}
    # Напрямок потрібен у ДВОХ місцях: при виборі судна і при розборі GTIN.
    # Рахуємо його ОДИН раз тут, на початку. Раніше він обчислювався всередині
    # `if named_ves:` (вибір судна) — тобто за відсутності названого судна змінної
    # просто не існувало, і звернення до неї нижче впало б з помилкою.
    is_export = str(row.get("Напрямок") or "").strip() == "Експорт"
    if not str(row.get("BL") or "").strip():
        bl = bl_from_events(events)
        if bl:
            out["BL"] = bl
    conts = []
    for e in events:
        c = e.get("equipmentReference")
        if c and c not in conts:
            conts.append(c)
    our = str(row.get("Контейнер") or "").strip()
    if conts:
        out["Контейнер (лінія)"] = ", ".join(conts)
        if not our:
            out["Контейнер"] = conts[0]
    if our and conts and our not in conts:
        out["Звірка"] = "За Maersk: " + ", ".join(conts)
    elif str(row.get("Звірка") or "").startswith("За Maersk:"):
        out["Звірка"] = ""          # розбіжність зникла — прибираємо стару позначку

    ves = sorted([e for e in events if (e.get("transportCall") or {}).get("modeOfTransport") == "VESSEL"], key=_dt)
    # «ETA порт» — це прибуття в ПОРТ, тобто подія МОРСЬКОГО плеча.
    # Було: бралась остання подія ARRI будь-яким транспортом. Для угод із
    # залізничним плечем після порту це давало дату прибуття ПОТЯГА.
    # Приклад 03.08.2026, угода 236 (Chennai → Gdansk → Мостиська):
    #   2026-08-01 ARRI ACT  VESSEL  Gdansk Baltic HUB   ← справжнє прибуття в порт
    #   2026-08-08 ARRI EST  RAIL    Мостиська           ← бралось помилково
    # У платформі стояло 08.08 (прогноз по залізниці), а закреслене «було
    # 01.08» було насправді ПРАВИЛЬНОЮ датою. Статус при цьому був вірний,
    # бо він рахується лише з фактичних подій.
    # Якщо морських подій немає взагалі (суто залізнична відправка) —
    # поводимось як раніше і беремо останню ARRI, щоб не втратити дату.
    arr_all = sorted([e for e in events if e.get("transportEventTypeCode") == "ARRI"
                      or e.get("equipmentEventTypeCode") == "ARRI"], key=_dt)
    arr_ves = [e for e in arr_all
               if (e.get("transportCall") or {}).get("modeOfTransport") == "VESSEL"]
    arr = arr_ves or arr_all
    last_arr = arr[-1] if arr else None

    eta_iso, actual = "", False
    if last_arr:
        eta_iso = _dt(last_arr)[:10]
        actual = last_arr.get("eventClassifierCode") == "ACT"

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", eta_iso):
        eta_iso = ""

    # Судно і вояж — БЕЗ обмеження за датою (вимога користувачки 01.08.2026
    # «простав дати та назви судна скрізь»). Раніше стояло `days <= 7`, тобто
    # назва писалась лише коли до прибуття лишалось не більше тижня; через це
    # 104 угоди лишались без судна, хоча Maersk назву віддавав (перевірка на
    # 25 угодах: 253 → MAERSK SARAT, 238 → MAERSK VIRGINIA, 23 → MAERSK EINDHOVEN).
    # Беремо ОСТАННЄ судно, у якого назва справді є: last_ves могла бути подія
    # без vesselName, і тоді не писалось нічого.
    # ЯКЕ саме судно з рейсу (рішення користувачки 02.08.2026):
    #   ЕКСПОРТ — ПЕРШЕ судно (те, на яке вантаж поставлять у нашому порту),
    #   ІМПОРТ  — ОСТАННЄ (те, що привезе вантаж до порту призначення).
    # Причина: угода 260 (експорт, три плечі) показувала XIAMEN — судно третього
    # плеча 14.10, хоча першим 15.08 іде LEONIDIO. До цього завжди бралося
    # останнє, і для експорту це давало судно, якого клієнт ще довго не побачить.
    named_ves = [e for e in ves
                 if ((e.get("transportCall") or {}).get("vessel") or {}).get("vesselName")]
    if named_ves:
        # is_export уже обчислено на початку функції — тут лише використовуємо
        tc = (named_ves[0] if is_export else named_ves[-1]).get("transportCall") or {}
        vessel = (tc.get("vessel") or {}).get("vesselName") or ""
        voyage = tc.get("carrierVoyageNumber") or tc.get("exportVoyageNumber") or tc.get("importVoyageNumber") or ""
        if vessel:
            out["Судно"] = vessel
        if voyage:
            out["Вояж"] = voyage

    # ── порт перевалки (вимога користувачки 01.08.2026, для схеми руху в кабінеті)
    # Перевалка = кожне вивантаження з судна (DISC), після якого є нове завантаження
    # (LOAD). Останній DISC — це порт призначення, він перевалкою не є.
    # Дві дати важливі: різниця між ними — скільки контейнер простояв у перевалці
    # (угода 106: Bremerhaven 02.03 → 26.03, тобто 24 дні).
    sea_legs = []
    for e in sorted(events, key=_dt):
        tc = e.get("transportCall") or {}
        if tc.get("modeOfTransport") != "VESSEL":
            continue
        code = e.get("transportEventTypeCode") or e.get("equipmentEventTypeCode") or ""
        if code not in ("LOAD", "DISC"):
            continue
        sea_legs.append((code, _dt(e)[:10],
                         (tc.get("location") or {}).get("locationName") or "", _dt(e)))
    # Перевалка — це вивантаження, ПІСЛЯ якого судно ще кудись іде. Раніше тут
    # стояло «усі вивантаження, крім останнього», і на угоді 238 це дало лише
    # Танджунг Пелепас: вивантаження в Гданську ще не сталося, тому останнім у
    # списку був Вільгельмсгафен — і саме та перевалка, на якій вантаж стоїть
    # ЗАРАЗ, у колонку не потрапляла.
    disc_idx = [i for i, l in enumerate(sea_legs)
                if l[0] == "DISC" and vessel_move_after(events, l[3])]
    if disc_idx:
        ports, arr, dep = [], "", ""
        for i in disc_idx:
            if sea_legs[i][2] and sea_legs[i][2] not in ports:
                ports.append(sea_legs[i][2])
            if not arr:
                arr = sea_legs[i][1]
            nxt = next((sea_legs[j][1] for j in range(i + 1, len(sea_legs))
                        if sea_legs[j][0] == "LOAD"), "")
            if nxt:
                dep = nxt
        if ports:
            out["Порт перевалки"] = " → ".join(ports)
        if arr:
            out["Перевалка (прибуття)"] = arr
        if dep:
            out["Перевалка (відправлення)"] = dep

    if eta_iso:
        if actual:
            out["ETA порт (факт)"] = eta_iso
        else:
            out["ETA порт (план)"] = eta_iso
            old = str(row.get("ETA порт (план)") or "")[:10]
            if old and old != eta_iso:
                hist = str(row.get("Зміни ETA (історія)") or "")
                out["Зміни ETA (історія)"] = (hist + "\n" if hist else "") + \
                    "%s: ETA порт: %s → %s (Maersk)" % (today_iso, old, eta_iso)
                out["Остання зміна"] = today_iso
        # головна колонка ETA = факт, якщо є, інакше план (як робив старий ланцюг)
        out["ETA"] = eta_iso

    # ── дати з подій Maersk (запит користувачки 01.08.2026 «гейт ін також бери там»)
    def pick(codes, classifier=None, mode=None, last=False):
        sel = []
        for e in events:
            c = e.get("equipmentEventTypeCode") or e.get("transportEventTypeCode") or ""
            if c not in codes:
                continue
            if classifier and e.get("eventClassifierCode") != classifier:
                continue
            if mode and (e.get("transportCall") or {}).get("modeOfTransport") != mode:
                continue
            sel.append(e)
        if not sel:
            return ""
        sel.sort(key=_dt)
        return _dt(sel[-1] if last else sel[0])[:10]

    # GATE IN — контейнер заїхав у порт відправлення. Беремо ПЕРШУ таку подію:
    # остання GTIN може бути вже видачею отримувачу.
    gate_in = pick(("GTIN",), "ACT") or pick(("GTIN",))
    if gate_in:
        out["Гейт ін"] = gate_in
    # ETD — відхід судна з порту завантаження (перший рейс морем)
    etd_act = pick(("DEPA",), "ACT", "VESSEL")
    if etd_act:
        out["ETD (факт)"] = etd_act
    else:
        etd_est = pick(("DEPA",), "EST", "VESSEL")
        if etd_est:
            out["ETD (план)"] = etd_est
    # вивантаження в порту прибуття (останнє DISC із судна)
    # СУХИЙ ПОРТ. Залізничне плече ПІСЛЯ морського — це доставка на сухий порт
    # (напр. Мостиська). Раніше ця дата нікуди не писалась, а до 03.08.2026 ще й
    # помилково потрапляла в «ETA порт» замість прибуття судна.
    # Користувачка про угоду 236: «Дата вивантаження в порту 2.08. Дата 8.08 —
    # це планова дата прибуття в сухий порт». Саме так тепер і розкладено:
    #   ARRI VESSEL 01.08 → ETA порт
    #   DISC VESSEL 02.08 → Вивантаження в порту (факт)
    #   ARRI RAIL   08.08 → ETA сухий порт
    # Умова «є морські події»: для суто залізничної відправки («Трейн») прибуття
    # потяга — це кінцева точка, а не сухий порт, і туди його писати не можна.
    # ⚠️ І ЛИШЕ ДЛЯ ЗАЛІЗНИЧНИХ УГОД (правило користувачки 28.08.2026, угода 238):
    # «немає сухого порту для цього перевезення, це авто». Maersk часом віддає
    # планову RAIL-подію навіть коли вантаж повезе авто — і дата сухого порту
    # з'являлась в авто-угоді. Вид перевезення веде синк з Експедитора.
    disc = pick(("DISC",), "ACT", "VESSEL", last=True)
    if disc:
        out["Вивантаження в порту (факт)"] = disc

    # ── ГЕЙТ АУТ = вивіз з порту ПРИБУТТЯ, і ТІЛЬКИ з нього ─────────────────
    # (правило користувачки 25.08.2026: «Гейт аут → Сухий порт → Доставлено»).
    # Було до 31.08.2026: бралась ОСТАННЯ фактична GTOT-подія де завгодно, і в
    # колонку потрапляло що завгодно, крім потрібного:
    #   • угода 280 (експорт, ще не поплив): GTOT 26.08 з депо ВІДПРАВЛЕННЯ
    #     (порожній контейнер поїхав на завантаження) — «звідки тут гейт аут????»;
    #   • угода 236 (імпорт із залізницею): потяг виїхав з Гданська 19.08, але
    #     остання GTOT — це вивіз АВТО з сухого порту 26.08, і «Гейт аут» (26.08)
    #     ставав ПІЗНІШИМ за «Сухий порт» (24.08) — порядок колонок ламався.
    # Тепер: перша фактична GTOT ПІСЛЯ останнього фактичного вивантаження з
    # судна, і лише коли моря попереду вже немає. Немає такої події — колонка
    # порожня; а якщо в ній стоїть дата якоїсь ІНШОЇ GTOT-події (тобто наш же
    # старий запис із відправлення) — чистимо (None: NocoDB на "" для дат свариться).
    disc_full = ""            # момент останнього фактичного вивантаження з судна
    for e in events:
        c = e.get("equipmentEventTypeCode") or e.get("transportEventTypeCode") or ""
        if (c == "DISC" and e.get("eventClassifierCode") == "ACT"
                and (e.get("transportCall") or {}).get("modeOfTransport") == "VESSEL"
                and _dt(e) > disc_full):
            disc_full = _dt(e)
    gt_all = sorted([e for e in events
                     if (e.get("equipmentEventTypeCode")
                         or e.get("transportEventTypeCode") or "") == "GTOT"
                     and e.get("eventClassifierCode") == "ACT"], key=_dt)
    if ves:
        gt_ok = [e for e in gt_all
                 if disc_full and _dt(e) > disc_full
                 and not vessel_move_after(events, _dt(e))]
        gtot = _dt(gt_ok[0])[:10] if gt_ok else ""
    else:
        # суто безморська відправка — тут «порт прибуття» не розрізнити,
        # лишаємо стару поведінку (остання фактична GTOT)
        gtot = _dt(gt_all[-1])[:10] if gt_all else ""
        gt_ok = gt_all
    cur_gt = str(row.get("Гейт аут") or "")[:10]
    if gtot:
        out["Гейт аут"] = gtot
    elif cur_gt and cur_gt in {_dt(e)[:10] for e in gt_all}:
        out["Гейт аут"] = None

    # ── СУХИЙ ПОРТ: факт важливіший за прогноз, прогноз — лише поки не бреше ──
    # Було до 31.08.2026: остання ARRI RAIL БУДЬ-ЯКОЇ класифікації. Maersk свої
    # RAIL-прогнози не оновлює, тому в 275 стояло «прибуде 15.08», хоча потяг
    # виїхав з Гданська лише 26.08 — «прибуття» раніше за виїзд. А ФАКТ прибуття
    # в сухий порт приходить подією GTIN ACT RAIL (заїзд у ворота термінала,
    # угода 236: Мостиська 24.08), яку старий код не дивився взагалі.
    # Тепер: (1) факт = остання ARRI/GTIN ACT залізницею після виїзду з порту;
    # (2) немає факту — прогноз ARRI EST, але тільки якщо він НЕ раніший за
    # фактичний виїзд потяга; (3) прогноз, що став неможливим, чистимо.
    rail_deal = "залізниця" in str(row.get("Вид перевезення") or "")
    if ves and rail_deal:
        rail_dep = ""         # факт виїзду залізницею з порту прибуття
        for e in gt_ok:
            if ((e.get("transportCall") or {}).get("modeOfTransport") == "RAIL"
                    and _dt(e) > rail_dep):
                rail_dep = _dt(e)
        after = rail_dep or disc_full
        arr_fact = ""
        for e in events:
            c = e.get("equipmentEventTypeCode") or e.get("transportEventTypeCode") or ""
            if (c in ("ARRI", "GTIN") and e.get("eventClassifierCode") == "ACT"
                    and (e.get("transportCall") or {}).get("modeOfTransport") == "RAIL"
                    and after and _dt(e) > after and _dt(e) > arr_fact):
                arr_fact = _dt(e)
        if arr_fact:
            dry = arr_fact[:10]
        else:
            est = pick(("ARRI",), "EST", "RAIL", last=True)
            dry = est if est and (not rail_dep or est >= rail_dep[:10]) else ""
        cur_dry = str(row.get("ETA сухий порт") or "")[:10]
        if dry:
            out["ETA сухий порт"] = dry
        elif cur_dry and rail_dep and cur_dry < rail_dep[:10]:
            out["ETA сухий порт"] = None

    # ── ПОСЛІДОВНІСТЬ ДАТ (вимога користувачки 31.08.2026: «всі дати
    # послідовні, не може бути наступна дата ранішою ніж попередня»).
    # Рух вантажу один: здача в порт → відхід → прибуття й вивантаження →
    # вивіз з порту → сухий порт → доставка отримувачу. Дату, що РАНІША за
    # попередній факт, прибираємо (None) — вона фізично неможлива. Приклад,
    # з якого це з'явилось: угода 236 — «Вивантаження у отримувача (факт)»
    # 10.06 при відході з порту 16.06; трекінг це поле взагалі не пише,
    # це слід старого разового імпорту. Чистимо саме ПІЗНІШУ за ланцюжком
    # колонку: попередні дати тут — перевірені події Maersk.
    CHAIN = ("Гейт ін", "ETD (факт)", "ETA порт (факт)",
             "Вивантаження в порту (факт)", "Гейт аут", "ETA сухий порт",
             "Вивантаження у отримувача (факт)")
    prev = ""
    for cname in CHAIN:
        v = out.get(cname, str(row.get(cname) or ""))
        v = (v or "")[:10] if isinstance(v, str) else ""
        if not v:
            continue
        if prev and v < prev:
            out[cname] = None
        else:
            prev = v

    # статус: 8-модель, «Завантажений» розділений на авто/потяг.
    #
    # ВАЖЛИВО (виправлено 02.08.2026): статус беремо ТІЛЬКИ з подій, які
    # (а) фактичні — eventClassifierCode == "ACT", і (б) вже відбулися.
    # Було: бралася просто остання подія за датою. Maersk віддає весь план
    # рейсу наперед, тому «остання» — це прогноз на майбутнє.
    # Угода 260 (експорт ГРАНД МАРИН, стафіровка аж 03.08): з 10 подій дві
    # фактичні (CONF) і вісім планових; останньою була ARRI EST 22.10.2026
    # на судні XIAMEN → платформа поставила «В морі» вантажу, який ще навіть
    # не завантажений. Помітила користувачка, а не я.
    # Якщо фактичних подій ще немає — статус НЕ чіпаємо взагалі.
    actual = [e for e in events
              if e.get("eventClassifierCode") == "ACT" and _dt(e)[:10] <= today_iso]
    last = sorted(actual, key=_dt)[-1] if actual else None
    mode = (last.get("transportCall") or {}).get("modeOfTransport") or "" if last else ""
    code = ((last.get("equipmentEventTypeCode") or last.get("transportEventTypeCode")
             or last.get("shipmentEventTypeCode") or "") if last else "")
    is_vessel = mode in ("VESSEL", "")
    load_st = "Завантажений на потяг" if mode == "RAIL" else "Завантажений на авто"

    # ── ЧИ МОРСЬКЕ ПЛЕЧЕ ЩЕ ПОПЕРЕДУ ────────────────────────────────────────
    # Єдиний надійний спосіб відрізнити ПОЧАТОК шляху від КІНЦЯ, коли код події
    # той самий. Дивимось не лише на фактичні події, а на ВЕСЬ рейс: Maersk віддає
    # план наперед, тому якщо після цієї події ще заплановане завантаження на
    # судно — вантаж нікуди не приїхав, він тільки збирається пливти.
    # Це закриває одразу дві речі:
    #   • заїзд у порт ВІДПРАВЛЕННЯ (і в експорті, і в імпорті) — не «доставлено»;
    #   • вивантаження на ПЕРЕВАЛЦІ — не «доставлено» і не кінець морського плеча.
    last_dt = _dt(last) if last else ""

    sea_ahead = vessel_move_after(events, last_dt) if last else False

    # ── УМОВИ ПОСТАВКИ ──────────────────────────────────────────────────────
    # Порожньо — це НЕ «звичайні умови», це «невідомо». Тому поводимось обережно:
    # без заповнених умов «Вантаж доставлено» ставиться лише після фінального
    # завезення авто, як в імпорті. Щойно колонку заповнять — правило запрацює
    # само, міняти код не доведеться. Станом на 11.08.2026 вона порожня у всіх
    # 277 угодах, тобто зараз ця гілка ще нічого не змінює на практиці.
    terms = str(row.get(INCOTERMS_FIELD) or "").strip().upper()
    # Експорт на ЗВИЧАЙНИХ умовах закінчується вивантаженням у порту призначення;
    # експорт DAP/DDU та БУДЬ-ЯКИЙ імпорт — тільки після фінальної доставки авто
    # (рішення користувачки 10.08.2026).
    ends_at_pod = is_export and terms and terms not in DOOR_TERMS

    st = ""
    if code in ("LOAD", "DEPA"):
        st = "В морі" if is_vessel else load_st
    elif code == "ARRI":
        # Судно ПРИБУЛО в порт — це вже не «в морі». Окремий статус з 05.08.2026.
        # Якщо попереду ще одне морське плече, то це перевалка, а не призначення.
        # ПОРЯДОК ЗАЛІЗНИЧНОГО ХВОСТА — правило користувачки 25.08.2026:
        # «Гейт аут (вивіз з порту прибуття) → Сухий порт → Доставлено».
        # Раніше БУДЬ-ЯКА залізнична подія давала «Завантажений на потяг» —
        # і вивіз з порту, і прибуття в сухий порт (угода 224).
        st = ((TRANSSHIP if sea_ahead else ARRIVED) if mode == "VESSEL"
              else DRY_PORT if mode == "RAIL" else load_st)
    elif code == "DISC":
        if not is_vessel:
            # вивантаження З ПОТЯГА — це вже сухий порт (правило 25.08.2026)
            st = DRY_PORT if mode == "RAIL" else load_st
        elif sea_ahead:
            # вивантаження на ПЕРЕВАЛЦІ — вантаж чекає наступного судна
            st = TRANSSHIP
        else:
            # вивантаження в порту ПРИЗНАЧЕННЯ
            st = DELIVERED if ends_at_pod else DISCHARGED
    elif code == "GTOT":
        st = load_st
    elif code == "GTIN":
        # GTIN = заїзд контейнера у ворота. Той самий код означає ПРОТИЛЕЖНЕ
        # залежно від того, ДЕ ми на маршруті:
        #   попереду ще морське плече — авто привезло контейнер У ПОРТ
        #     ВІДПРАВЛЕННЯ, це ПОЧАТОК шляху;
        #   моря попереду немає — авто привезло контейнер отримувачу, це КІНЕЦЬ.
        #
        # Було до 10.08.2026: «доставлено» для будь-якого GTIN+TRUCK. Зловили на
        # угоді 259 (експорт Солоницівка → Гданськ): 10.08 контейнер заїхав у
        # Гданськ, трекінг поставив «Вантаж доставлено» — за день до відплиття
        # (ETD факт 11.08) і за півтора місяця до прибуття (ETA 24.09). Помітила
        # користувачка на екрані, не код. Гірше: «доставлено» ще й заморожує
        # запис (умова was != DELIVERED нижче), тож угода простояла б так рейс.
        #
        # Виправлення 10.08 було НЕПОВНИМ: воно розрізняло експорт та імпорт за
        # колонкою «Напрямок». Але заїзд у порт відправлення буває і в імпорті —
        # там контейнер так само завозять авто в закордонний порт. Тобто та сама
        # помилка лишалась дзеркально для 253 імпортних угод, просто ще не
        # спрацювала. Тепер напрямок для цього рішення не потрібен взагалі:
        # питання не «експорт чи імпорт», а «море попереду чи вже позаду».
        # Це і є «В порту відправлення застосовувати і до імпорту»
        # (рішення користувачки 10.08.2026).
        if mode == "TRUCK":
            st = IN_POL if sea_ahead else DELIVERED
        else:
            st = load_st
    was = str(row.get("Статус") or "")
    # «Статус не виправлено» (користувачка 31.08.2026, угода 224): Maersk часто
    # ВЗАГАЛІ не надсилає фактичної події прибуття потяга в сухий порт — останнім
    # фактом лишається виїзд із Гданська, і «Завантажений на потяг» висить
    # тижнями. Якщо дата «ETA сухий порт» відома (факт трекінгу чи людська) і
    # вже настала — вантаж у сухому порту.
    dry_eff = str(out.get("ETA сухий порт", row.get("ETA сухий порт")) or "")[:10]
    if (dry_eff and dry_eff <= today_iso and rail_deal
            and (st or was) == "Завантажений на потяг"):
        st = DRY_PORT
    src = str(row.get("Статус (джерело)") or "").strip()
    if st and was != DELIVERED and st != was:
        if src == HUMAN_SRC and not _fact_newer_than_human(row, last_dt):
            # Статус виставила людина, і НОВІШОГО ФАКТУ в Maersk немає — автомат мовчить
            # (рішення користувачки 05.08.2026, звужене нею ж 16.08.2026 — див. нижче).
            pass
        else:
            out["Статус"] = st
            # джерело і дату пишемо ТІЛЬКИ разом зі зміною статусу, інакше дата
            # оновлювалася б щодня і кожен прогін давав би порожні «зміни»
            out["Статус (джерело)"] = STATUS_SRC
            out["Статус (оновлено)"] = today_iso

    out["Останнє оновлення"] = today_iso
    if str(row.get("Трекінг (стан)") or ""):
        out["Трекінг (стан)"] = ""        # дані знову приходять — позначка мовчання зайва
    if not str(row.get("Лінія") or ""):
        out["Лінія"] = "Maersk"
    return out


# ---------------------------------------------------------------- основний цикл
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="включно з доставленими (за замовчуванням лише активні)")
    a = ap.parse_args()
    tag = "[dry-run] " if a.dry_run else ""
    today_iso = datetime.date.today().isoformat()

    env = load_env()
    statuses = nc_status_options()
    cancelled = cancelled_numbers()
    rows = nc_records()
    # Запобіжник проти помилки 02.08.2026: логіка читає поля, яких може не бути
    # в READ_FIELDS — тоді вони мовчки порожні, і правило не працює. Перевіряємо
    # прямо: якщо поле не приїхало ЖОДНОГО разу — кажемо про це в лог голосно.
    for need in ("Напрямок",):
        if rows and all(need not in r for r in rows):
            log("WARN поле «%s» не приїхало з бази — перевір READ_FIELDS. "
                "Логіка, що на нього спирається, зараз НЕ працює." % need)
    # 31.07.2026: раніше брались ЛИШЕ угоди з коносаментом, тому десятки угод
    # Мірандора (133-139, 189, 201-204 …) взагалі не трекались — у них є тільки
    # номер контейнера. Тепер беремо і такі: Maersk віддає події й по контейнеру.
    todo, skipped, nokey = [], 0, 0
    for r in rows:
        bl = str(r.get("BL") or "").strip()
        cont = str(r.get("Контейнер") or "").split(",")[0].strip()
        if not BL_RE.match(bl):
            bl = ""                       # не коносамент Maersk — підемо по контейнеру
        if not bl and not CONT_RE.match(cont.upper()):
            nokey += 1
            continue
        if not a.all and str(r.get("Статус") or "") == DELIVERED:
            continue
        if deal_no(r.get("Угода")) in cancelled:
            skipped += 1
            continue
        todo.append((bl, r))
    if nokey:
        log("%sБез коносамента і без номера контейнера — не трекаються: %d" % (tag, nokey))
    if skipped:
        log("%sПропущено скасованих в Експедиторі: %d" % (tag, skipped))
    if a.limit:
        todo = todo[: a.limit]
    log("%sУгод для трекінгу: %d (усього в платформі %d)" % (tag, len(todo), len(rows)))
    if not todo:
        print("MAERSK_OK tracked=0 updated=0")
        return

    token = maersk_token(env)
    log("%sТокен Maersk отримано" % tag)

    # HTTP 400 на номер контейнера = контейнер належить іншій лінії (MSC, CMA, Hapag,
    # COSCO). Це не помилка нашого коду і не збій API — тому окремий список.
    patches, no_data, errors, foreign, changed_cols = [], [], [], [], {}
    how_stat = {}
    # 🔒 ЗАПОБІЖНИК ВІД «ДВІЙНИКА» (рішення користувачки 21.08.2026, угоди 280/287).
    # Той самий коносамент у двох рядках означає, що Maersk віддасть їм ОДНАКОВІ
    # судно, дати і статус — і в таблиці з'являться два нерозрізненні рядки-близнюки.
    # Саме так рядок 287 з чужим BL став копією 280, і помітила це людина, а не ми.
    # Тепер: якщо один BL стоїть у кількох рядках — НЕ заповнюємо жоден з них,
    # а в видиму колонку «Трекінг (стан)» обох пишемо, з ким конфлікт. Позначка
    # зітреться сама (див. parse_events), щойно конфлікт розв'яжуть і рядок
    # знову почне трекатись. Трекінг по контейнеру це не зачіпає.
    by_bl = {}
    for bl, r in todo:
        if bl:
            by_bl.setdefault(bl, []).append(r)
    dup_ids = set()
    for bl, rs in sorted(by_bl.items()):
        if len(rs) < 2:
            continue
        deals_all = sorted(str(x.get("Угода") or "") for x in rs)
        log("%s🔴 КОНФЛІКТ КОНОСАМЕНТА: BL %s одночасно в угодах %s — жодну не оновлюю"
            % (tag, bl, ", ".join(deals_all)))
        for r in rs:
            dup_ids.add(r["Id"])
            others = ", ".join(d for d in deals_all if d != str(r.get("Угода") or ""))
            state = "Конфлікт: той самий BL %s в угоді %s" % (bl, others)
            if str(r.get("Трекінг (стан)") or "") != state:
                patches.append({"Id": r["Id"], "Трекінг (стан)": state})
        if not a.dry_run:
            try:
                import journal_note
                journal_note.note("трекінг Maersk", "конфлікт коносамента",
                                  "угоди " + ", ".join(deals_all), "BL", bl,
                                  "жодну не оновлюю, приберіть зайвий BL")
            except Exception:  # noqa: BLE001 — журнал не має валити трекінг
                pass
    if dup_ids:
        todo = [(bl, r) for bl, r in todo if r["Id"] not in dup_ids]
    for bl, row in todo:
        cont = str(row.get("Контейнер") or "").split(",")[0].strip()
        events, how, note = collect_events(env, token, bl, cont)
        if not events:
            key = bl or str(row.get("Контейнер") or "").split(",")[0].strip()
            bucket = no_data if "404" in str(note) else (foreign if "400" in str(note) else errors)
            bucket.append("угода %s/%s" % (row.get("Угода"), key)
                          if bucket is foreign else
                          "угода %s/%s(%s)" % (row.get("Угода"), key, note or "порожньо"))
            # МОВЧАННЯ ТРЕКІНГУ ВИДНО В ПЛАТФОРМІ, а не тільки в журналі на сервері
            # (прохання користувачки 05.08.2026). Приклад, з якого це почалося: угода
            # 256 — Maersk віддає 404 з 04.08, статус «В морі» завис, а помітити це
            # можна було лише зайшовши в maersk.log на VPS.
            # Дату першого мовчання зберігаємо, щоб було видно, скільки днів воно триває.
            prev = str(row.get("Трекінг (стан)") or "")
            hit = re.search(r"\d{4}-\d{2}-\d{2}", prev)
            since = hit.group(0) if (hit and prev.startswith("Maersk")) else today_iso
            why = ("немає даних" if "404" in str(note)
                   else "інша лінія" if "400" in str(note) else "збій запиту")
            state = "Maersk: %s з %s" % (why, since)
            if prev != state:
                patches.append({"Id": row["Id"], "Трекінг (стан)": state})
            continue
        how_stat[how] = how_stat.get(how, 0) + 1
        want = parse_events(events, row, today_iso, statuses)
        if want.get("Статус") and statuses and want["Статус"] not in statuses:
            log("WARN статус «%s» не входить у варіанти колонки — не пишу (угода %s)"
                % (want["Статус"], row.get("Угода")))
            want.pop("Статус")
        patch = {}
        for col, val in want.items():
            old = str(row.get(col) or "")
            # будь-яку дату обрізаємо до YYYY-MM-DD: NocoDB може віддати її з часом,
            # і тоді порівняння з нашим 10-символьним значенням завжди давало б «змінилось»
            if re.match(r"^\d{4}-\d{2}-\d{2}", old):
                old = old[:10]
            # None = «очистити колонку» (послідовність дат, 31.08.2026): NocoDB
            # для дат приймає null, а не "". Порожнє при порожньому — пропуск,
            # інакше кожен прогін «чистив» би вже чисте.
            if val in ("", None) and not old:
                continue
            if old != ("" if val is None else str(val)):
                patch[col] = val
                changed_cols[col] = changed_cols.get(col, 0) + 1
        if patch:
            patch["Id"] = row["Id"]
            patches.append(patch)

    log("%sОновити угод: %d; без даних: %d; помилки: %d" % (tag, len(patches), len(no_data), len(errors)))
    if changed_cols:
        log("%sЗміни по колонках: %s" % (tag, ", ".join(
            "%s=%d" % (k, v) for k, v in sorted(changed_cols.items(), key=lambda x: -x[1]))))
    if how_stat:
        log("%sЯк знайшлись дані: %s" % (tag, ", ".join("%s=%d" % kv for kv in sorted(how_stat.items()))))
    if no_data:
        log("%sБез даних у Maersk: %s" % (tag, ", ".join(no_data[:20])))
    if foreign:
        log("%sКонтейнер іншої лінії — Maersk його не бачить (%d): %s"
            % (tag, len(foreign), ", ".join(foreign)))
    if errors:
        log("%sПомилки API: %s" % (tag, ", ".join(errors[:20])))

    if a.dry_run:
        for p in patches[:8]:
            log("DRY: %s" % json.dumps(p, ensure_ascii=False)[:220])
        print("MAERSK_DRY tracked=%d would_update=%d" % (len(todo), len(patches)))
        return

    fails = 0
    for i in range(0, len(patches), CHUNK):
        part = patches[i:i + CHUNK]
        st, js = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, part)
        if st in (200, 201):
            continue
        log("UPDATE_FAIL порція %d-%d: %s %s — пробую по одному" % (i, i + len(part), st, str(js)[:160]))
        for one in part:                     # щоб один поганий запис не блокував решту
            st1, js1 = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, [one])
            if st1 not in (200, 201):
                fails += 1
                log("UPDATE_FAIL угода Id=%s: %s %s" % (one.get("Id"), st1, str(js1)[:160]))
    log("DONE tracked=%d updated=%d nodata=%d foreign=%d api_errors=%d write_fails=%d"
        % (len(todo), len(patches), len(no_data), len(foreign), len(errors), fails))
    print("MAERSK_OK tracked=%d updated=%d nodata=%d foreign=%d api_errors=%d write_fails=%d"
          % (len(todo), len(patches), len(no_data), len(foreign), len(errors), fails))


# Замок «один запуск за раз» — див. direct_sync/runlock.py.
# Таймер, кнопка на платформі і ручний запуск можуть накластися;
# два паралельні прогони створюють дублікати угод у базі.
if __name__ == "__main__":
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from runlock import single_run
    with single_run("maersk"):
        main()
