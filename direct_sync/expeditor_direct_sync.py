#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пряма синхронізація: Експедитор (OData) → платформа (NocoDB, таблиця «Диспетчеризація»).

ОКРЕМА автоматизація, паралельна до старого ланцюга через Google-таблицю
(вимога користувачки 30.07.2026). Майстер-таблицю не читає і не пише.

Політика запису:
  * ДОВІДНИКОВІ поля (Клієнт, Напрямок, Лінія, Менеджер, Агент, POL, POD, FD,
    «Митне оформлення», «Маршрут») — Експедитор авторитетний, перезаписуються завжди;
  * РЕШТА (BL, Контейнер, Кількість, дати, Коментар) — тільки якщо в платформі
    порожньо АБО там стоїть значення, яке цей самий скрипт записав минулого разу
    (файл станів written_state.json). Тобто чужі дані — трекінг Maersk, ручні
    правки — ніколи не затираються; конфлікти лише пишуться в лог;
  * порожнє значення в Експедиторі НІКОЛИ не стирає заповнене в платформі;
  * поля, яких в Експедиторі НЕМАЄ (Судно, Вояж, Тип, Перевізник,
    авто/водій/ЦМР, чекбокси документів, коментарі клієнту, «Зміни ETA») — не чіпає;
  * «Маршрут» більше НЕ вільний текст: він збирається з POL → POD → DR → FD
    (03.08.2026, вимога користувачки). Пишеться лише тоді, коли зібралося
    щонайменше дві ланки — інакше однослівний маршрут затер би нормальний;
  * нові угоди створює, наявні знаходить за номером угоди;
  * нічого не видаляє.

Чому так з ETA: перевірка 30.07.2026 показала, що в 126 угодах ETA в платформі
(з трекінгу Maersk через майстер-таблицю) СВІЖІША за ETA в Експедиторі — сліпе
перезаписування відкотило б реальні затримки назад. Жива океанська ETA має
приходити з API Maersk окремою автоматизацією.

Запуск:  python3 /root/direct-sync/expeditor_direct_sync.py [--dry-run] [--limit N]
Лог:     /root/direct-sync/sync.log
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

FINREP = "/root/unitex-finrep"
WORKDIR = "/root/direct-sync"
NAMES = os.path.join(WORKDIR, "names.json")
STATE = os.path.join(WORKDIR, "written_state.json")   # що саме цей скрипт записав минулого разу
LOG = os.path.join(WORKDIR, "sync.log")
NAMES_TTL = 6 * 3600

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"          # Диспетчеризація
TOKEN_FILE = "/root/nocodb-token.txt"
CHUNK = 25                          # NocoDB не любить великі bulk-порції

EMPTY_DATE = "0001-01-01T00:00:00"
NULL_GUID = "00000000-0000-0000-0000-000000000000"

# Експедитор → колонка платформи. Ключ = колонка NocoDB.
KIND_MAP = {"Импорт": "Імпорт", "Экспорт": "Експорт", "Транзит": "Транзит"}
LINE_MAP = {"MAE": "Maersk", "MSC": "MSC", "CMA": "CMA CGM"}

# Дати: колонка платформи ← поле Експедитора
DATE_FIELDS = [
    ("ETA", "ЕТА"),
    ("ETA порт (план)", "ЕТА_ПОД"),
    ("ETA порт (факт)", "Факт_ПОД"),
    ("ETD (план)", "ЕТА_ПОЛ"),
    ("ETD (факт)", "Факт_ПОЛ"),
    ("Планова до клієнта (план)", "ЕТА_ФД"),
    ("Планова до клієнта (факт)", "Факт_ФД"),
]
# Текст: колонка платформи ← поле Експедитора
TEXT_FIELDS = [
    ("BL", "Коносамент"),
    # домашній коносамент: компанія його не випускає, дають агенти, але в Експедиторі
    # він фіксується — реквізит «ДомашнийКоносамент», заповнений у 17 угодах з 266.
    # У кабінеті клієнта показуємо HBL, а якщо порожній — лінійний BL.
    ("HBL", "ДомашнийКоносамент"),
    # для авіа документ перевезення — авіанакладна, а не коносамент
    ("Авіанакладна", "СписокАвиаНакладных"),
    ("Контейнер", "СписокКонтейнеров"),
    ("Вантаж", "Груз"),
]
# Довідникові колонки: Експедитор — єдине джерело правди, пишемо завжди
AUTHORITATIVE = {"Клієнт", "Напрямок", "Лінія", "Менеджер", "Агент", "Статус", "Контейнер",
                 "Етап (Експедитор)",
                 "POL", "POD", "FD", "Митне оформлення", "Маршрут"}

# ---- МАРШРУТ ЗІ СТРУКТУРОВАНИХ ПОЛІВ (вимога користувачки 03.08.2026) ----
# «треба брати дані не з поля Маршрут, а з полей POL, POD, FD».
# Раніше «Маршрут» був вільним текстом: приїжджав із майстер-таблиці або
# вписувався руками, тому писався по-різному й нізвідки не перевірявся.
# Тепер кожна ланка — окремий реквізит угоди в Експедиторі, а «Маршрут» —
# похідне від них значення, яке збирає цей скрипт.
#
# Колонка платформи ← реквізит угоди. Усі чотири вказують на `Catalog_Города`:
# перевірено 04.08.2026 — 268 угод, 53 різних коди, розшифровано 53 з 53.
CITY_FIELDS = [
    ("POL", "ПОЛ_Key"),                          # порт завантаження
    ("POD", "ПОД_Key"),                          # порт вивантаження
    ("FD", "ФД_Key"),                            # кінцева точка доставки
    ("Митне оформлення", "ПунктПересеченияГраницы_Key"),   # митний перехід
]
# Сухий порт (DR) в Експедиторі ще не заведено — користувачка 03.08.2026:
# «Ще додамо пізніше DR — dry port в Експедитор». Тому не пишемо назву реквізиту
# намертво, а щоразу беремо ПЕРШИЙ, який реально є в угоді. Щойно Софт Про його
# заведе, колонка «Сухий порт» почне заповнюватись сама, без правок коду.
DRY_KEYS = ("ДР_Key", "Др_Key", "ДрайПорт_Key", "СухойПорт_Key", "СухойПорт")
DRY_COL = "Сухий порт"
# Порядок ланок у маршруті: звідки → куди → сухий порт → до клієнта.
ROUTE_ORDER = ["POL", "POD", DRY_COL, "FD"]
# Маршрут пишемо, лише якщо зібралося щонайменше дві ланки. Інакше «Gdansk»
# без продовження затер би нормальний маршрут, який уже стоїть у платформі.
ROUTE_MIN_PARTS = 2
# службовий ключ: map_deal кладе сюди список ланок, основний цикл забирає його
# і перетворює на «Маршрут». У базу цей ключ не потрапляє.
ROUTE_PARTS = "__route_parts"
# «Контейнер» додано 31.07.2026: перевірка по коносаментах показала, що правий Експедитор,
# а в платформі сиділи застарілі номери з майстер-таблиці (угоди 113, 219, 223, 224),
# і політика «не чіпати чуже» не давала їх виправити.

# Стадія перевезення в Експедиторі → статус у платформі (рішення користувачки 30.07.2026).
# Мапимо ЛИШЕ однозначне: «Завершена» = вантаж доставлено (дата завершення є у всіх таких угод).
# «Выполняется» і «ВыставленСчет» надто загальні (друге взагалі про оплату) — не чіпаємо,
# точний етап дає трекінг перевізника.
# Мапінг етапу Експедитора → статус платформи (рішення користувачки 31.07.2026):
#   «Завершена»     → Вантаж доставлено
#   «Выполняется»   → Виконується
#   «ВыставленСчет» → Виконується («рахунок виставлено, робота йде»)
# ДВА ВИНЯТКИ, які переважають мапінг:
#   1) ДАТА ВИКОНАННЯ РОБІТ — вантаж доставлено, але лише якщо вона:
#        * уже МИНУЛА (уточнення користувачки 31.07.2026), і
#        * НЕ РАНІШЕ за ETA — інакше це неможливо (доставка до прибуття).
#      Друга умова з'явилась після реальної помилки: у 15 угодах ця дата раніша
#      за їхню ж ETA (напр. угода 227: роботи 22.12.2025, ETA 26.07.2026),
#      і без перевірки вони помилково ставали «доставлено».
#   2) якщо в платформі вже стоїть «Вантаж доставлено» — не понижуємо.
# Увага: ДатаЗавершения для цього НЕ годиться — це закриття періоду
# (120 із 123 значень — останній день місяця), а не факт вивезення.
#   3) «Виконується» НЕ перекриває конкретний статус (рішення користувачки 02.08.2026).
#      Це статус-заглушка: «Выполняется»/«ВыставленСчет» не кажуть нічого ні про етап
#      перевезення, ні про спосіб. Ставимо його лише тоді, коли інших даних немає —
#      тобто в платформі порожньо або там уже «Виконується». Якщо статус змінили
#      вручну або його поставив трекінг («В морі», «Завантажений на потяг» тощо) —
#      він головніший. Привід: користувачка тричі поспіль міняла статус на «В морі»,
#      а щоденна синхронізація о 07:00 повертала «Виконується».
STAGE_MAP = {"Завершена": "Вантаж доставлено",
             "Выполняется": "Виконується",
             "ВыставленСчет": "Виконується"}
DELIVERED = "Вантаж доставлено"
VAGUE = "Виконується"          # статус-заглушка: не перекриває конкретний (див. виняток 3)
WORKS_DONE_FIELD = "ДатаВыполненияРабот"

# Комерційний етап Експедитора пишемо в платформу ЯК Є, окремою колонкою.
# Навіщо: він потрібен логіці алертів. Користувачка 31.07.2026: «ВыставленСчет»
# виставляють, як правило, вже ПІСЛЯ завантаження на авто — тож угоду з таким етапом
# не можна вважати простоєм у порту, навіть якщо дані про авто в Експедитор не внесли.
STAGE_COL = "Етап (Експедитор)"

# Скасовані угоди в таблицю не вносяться взагалі (рішення користувачки 30.07.2026):
# не створюються, не оновлюються; їхні номери пишемо у файл, щоб трекери їх не питали.
CANCELLED_STAGE = "Отменена"
CANCELLED_FILE = os.path.join(WORKDIR, "cancelled.json")
# 01.08.2026: раніше скасовані просто пропускались, і в платформі в них лишався
# останній робочий статус — тому вони й далі висіли в таблиці й у показниках.
# Тепер проставляємо їм окремий статус, а фасад ховає такі угоди скрізь.
CANCELLED_STATUS = "Скасована"

WRITTEN_COLS = (
    ["Клієнт", "Напрямок", "Лінія", "Менеджер", "Агент", "Кількість", "Коментар", "Статус",
     "Етап (Експедитор)", "Маршрут", DRY_COL]
    + [c for c, _ in TEXT_FIELDS]
    + [c for c, _ in DATE_FIELDS]
    + [c for c, _ in CITY_FIELDS]
)


def log(msg):
    line = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(msg, flush=True)


# ---------------------------------------------------------------- NocoDB
TOK = open(TOKEN_FILE).read().strip()


def nc(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = urllib.request.Request(
        NC + path, data=body, method=method,
        headers={"Content-Type": "application/json", "xc-token": TOK},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"err": e.read().decode()[:300]}
    except Exception as e:  # noqa: BLE001
        return 0, {"err": str(e)[:300]}


def nc_meta():
    st, js = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        raise SystemExit("META_FAIL %s %s" % (st, js))
    return js


def nc_records(fields):
    out, off = [], 0
    q = urllib.parse.quote(",".join(fields), safe=",")
    while True:
        st, js = nc("GET", "/api/v2/tables/%s/records?limit=200&offset=%d&fields=%s" % (TABLE, off, q))
        if st != 200:
            raise SystemExit("READ_FAIL %s %s" % (st, js))
        out += js.get("list", [])
        if js.get("pageInfo", {}).get("isLastPage"):
            return out
        off += 200


def ensure_options(meta, col_title, values, dry):
    """Додати відсутні варіанти в SingleSelect (тільки додає, нічого не прибирає)."""
    col = next((c for c in meta["columns"] if c["title"] == col_title), None)
    if not col or col["uidt"] != "SingleSelect":
        return set()
    opts = [o for o in (col.get("colOptions") or {}).get("options", [])]
    have = {o["title"] for o in opts}
    missing = sorted(v for v in values if v and v not in have)
    if not missing:
        return have
    if dry:
        log("DRY: у «%s» бракує варіантів: %s" % (col_title, ", ".join(missing)))
        return have | set(missing)
    new_opts = [{k: o[k] for k in ("id", "title", "color", "order") if k in o} for o in opts]
    base = len(new_opts)
    for i, t in enumerate(missing):
        new_opts.append({"title": t, "order": base + i + 1})
    st, js = nc("PATCH", "/api/v2/meta/columns/%s" % col["id"],
                {"title": col_title, "uidt": "SingleSelect", "colOptions": {"options": new_opts}})
    if st in (200, 201):
        log("Додано варіанти в «%s»: %s" % (col_title, ", ".join(missing)))
        return have | set(missing)
    log("WARN не вдалося додати варіанти в «%s» (%s %s) — ці значення не пишу" % (col_title, st, js))
    return have


# ---------------------------------------------------------------- Експедитор
def odata_client():
    os.chdir(FINREP)
    sys.path.insert(0, os.path.join(FINREP, "engine"))
    from odata_client import ODataClient  # noqa: PLC0415
    return ODataClient()


def load_names(c, force=False):
    names = {}
    if os.path.exists(NAMES) and not force:
        try:
            names = json.load(open(NAMES, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            names = {}
    fresh = names.get("ts", 0) + NAMES_TTL > datetime.datetime.now().timestamp()
    need = {"client", "line", "man", "contr", "city"} - set(names)
    if fresh and not need:
        return names
    cats = (("client", "Catalog_Клиенты"), ("line", "Catalog_Линии"),
            ("man", "Catalog_ФизическиеЛица"), ("contr", "Catalog_Контрагенты"),
            # міста — для POL/POD/FD/митного переходу (див. CITY_FIELDS)
            ("city", "Catalog_Города"))
    for key, ent in cats:
        try:
            names[key] = {r["Ref_Key"]: (r.get("Description") or "").strip()
                          for r in c.list(ent, select=["Ref_Key", "Description"])}
        except Exception as e:  # noqa: BLE001
            log("WARN довідник %s не оновився: %s" % (ent, str(e)[:120]))
            names.setdefault(key, {})
    names["ts"] = datetime.datetime.now().timestamp()
    json.dump(names, open(NAMES, "w", encoding="utf-8"), ensure_ascii=False)
    log("Довідники: клієнти %d, лінії %d, фізособи %d, контрагенти %d, міста %d"
        % tuple(len(names[k]) for k in ("client", "line", "man", "contr", "city")))
    if not names.get("city"):
        # без міст маршрут зібрати неможливо — краще сказати прямо, ніж мовчки
        # писати порожні POL/POD/FD і виглядати, ніби в Експедиторі даних нема
        log("WARN довідник міст порожній — POL/POD/FD і «Маршрут» цього разу не пишу")
    return names


def num(n):
    s = str(n or "").strip()
    try:
        return str(int(s))
    except ValueError:
        return s


def d10(v):
    s = str(v or "")
    if not s or s.startswith("0001-01-01"):
        return None
    return s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", s) else None


def txt(v):
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    return s or None


def containers(v):
    parts = [p for p in re.split(r"[\s,;]+", str(v or "")) if p]
    return ", ".join(parts) or None


def qty(d):
    parts = []
    for fld, label in (("Кол20", "20"), ("Кол40", "40")):
        try:
            n = int(float(d.get(fld) or 0))
        except (TypeError, ValueError):
            n = 0
        if n:
            parts.append("%d×%s" % (n, label))
    return ", ".join(parts) or None


def manager(v):
    s = str(v or "")
    if s.startswith(("Ірина", "Iryna", "Ирина")):
        return "Ірина"
    if s.startswith(("Віталій", "Vitalii", "Виталий")):
        return "Віталій"
    return None


def line_option(raw):
    """Назва лінії з довідника Експедитора → варіант колонки «Лінія» (коди → повні назви)."""
    s = str(raw or "").strip()
    if not s:
        return None
    return LINE_MAP.get(s.upper(), s)


def line_name(v, allowed):
    s = line_option(v)
    return s if s and s in allowed else None


def ref(names, key, guid):
    g = str(guid or "")
    if not g or g == NULL_GUID:
        return None
    return txt(names.get(key, {}).get(g))


def dry_field(d):
    """Назва реквізиту сухого порту в угоді, або None, якщо його ще не завели."""
    return next((k for k in DRY_KEYS if k in d), None)


def route_seq(parts):
    """Ланки маршруту з Експедитора, по порядку: POL → POD → сухий порт → FD.

    parts — {колонка: назва міста}. Дві поспіль однакові ланки склеюються
    (буває, коли POD і FD — те саме місто), порожні пропускаються.
    """
    seq = []
    for col in ROUTE_ORDER:
        v = (parts.get(col) or "").strip()
        if v and (not seq or seq[-1] != v):
            seq.append(v)
    return seq


def split_route(text):
    """Наявний маршрут → список ланок. Ділимо ТІЛЬКИ по стрілці: у назвах міст
    бувають дефіси («Рава-Руська»), і поділ по дефісу розірвав би їх навпіл."""
    return [x.strip() for x in str(text or "").split("→") if x.strip()]


def merge_route(seq, old_text):
    """Маршрут для запису + перелік ланок, які довелося б втратити.

    ГОЛОВНЕ ПРАВИЛО: жодна ланка, яка вже є в платформі, не має зникнути.
    Навіщо саме так (перевірено на живих даних 04.08.2026): в Експедиторі ще
    немає реквізиту сухого порту (DR), а в платформі він стоїть третьою ланкою —
    «Мостиська» у 124 угодах, «Тернопіль» у 1. Просте перезаписування маршруту
    даними Експедитора стерло б цю ланку у 131 угоді з 268.

    Тому: беремо ланки Експедитора, а з наявного маршруту дописуємо в кінець
    усе, що йшло ПІСЛЯ останньої спільної ланки. Якщо після цього бодай одна
    стара ланка все одно зникає — НЕ ПИШЕМО НІЧОГО і повертаємо її в списку
    втрат, щоб вона потрапила в лог, а не пропала мовчки.

    Приклади:
        Експедитор [Chennai, Gdansk] + платформа «Gdansk → Мостиська»
            → «Chennai → Gdansk → Мостиська»   (додали POL, зберегли сухий порт)
        Експедитор [Gdansk]          + платформа «Felixstowe → Gdansk → Мостиська»
            → нічого не пишемо, у втратах «Felixstowe»
    """
    old = split_route(old_text)
    if not old:
        return (" → ".join(seq) if len(seq) >= ROUTE_MIN_PARTS else None), []
    common = [i for i, v in enumerate(old) if v in seq]
    merged = seq + [v for v in old[common[-1] + 1:] if v not in seq] if common else list(seq)
    merged = [v for i, v in enumerate(merged) if i == 0 or merged[i - 1] != v]
    lost = [v for v in old if v not in merged]
    if lost:
        return None, lost
    return (" → ".join(merged) if len(merged) >= ROUTE_MIN_PARTS else None), []


def mark_cancelled(cancelled, by_num, allowed_statuses, dry):
    """Проставляє статус «Скасована» тим угодам, які Експедитор позначив «Отменена».

    Пишемо навіть поверх «Вантаж доставлено»: скасування — рішення людини в
    Експедиторі, воно старше за будь-який автоматичний статус. Нових записів не
    створюємо і нічого не видаляємо — тільки міняємо статус наявним.
    """
    if CANCELLED_STATUS not in allowed_statuses:
        log("WARN статусу «%s» немає серед варіантів колонки — скасовані не позначаю"
            % CANCELLED_STATUS)
        return
    patch = [{"Id": r["Id"], "Статус": CANCELLED_STATUS}
             for r in (by_num.get(num(d.get("Number"))) for d in cancelled)
             if r and str(r.get("Статус") or "").strip() != CANCELLED_STATUS]
    if not patch:
        return
    if dry:
        log("DRY позначити скасованими: %d" % len(patch))
        return
    for i in range(0, len(patch), CHUNK):
        st, js = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, patch[i:i + CHUNK])
        if st not in (200, 201):
            log("CANCEL_FAIL %s %s" % (st, str(js)[:200]))
            return
    log("Позначено скасованими: %d" % len(patch))


def map_deal(d, names, allowed_lines, allowed_kinds, allowed_statuses=frozenset()):
    """Повертає {колонка NocoDB: значення} лише з непорожніх даних Експедитора."""
    o = {}
    raw_stage = str(d.get("Статус") or "").strip()
    if raw_stage:
        o[STAGE_COL] = raw_stage
    stage = STAGE_MAP.get(raw_stage)
    works = d10(d.get(WORKS_DONE_FIELD))
    if works and works <= datetime.date.today().isoformat():
        eta = d10(d.get("ЕТА"))
        if not eta or works >= eta:          # роботи виконані вже після прибуття
            stage = DELIVERED
    if stage and (not allowed_statuses or stage in allowed_statuses):
        o["Статус"] = stage
    kind = KIND_MAP.get(str(d.get("Вид") or "").strip())
    if kind and kind in allowed_kinds:
        o["Напрямок"] = kind
    for col, val in (("Клієнт", ref(names, "client", d.get("Клиент_Key"))),
                     ("Агент", ref(names, "contr", d.get("Агент_Key"))),
                     ("Менеджер", manager(ref(names, "man", d.get("Менеджер_Key")))),
                     ("Лінія", line_name(ref(names, "line", d.get("Линия_Key")), allowed_lines)),
                     ("Кількість", qty(d)),
                     ("Коментар", txt(d.get("Примечание")))):
        if val:
            o[col] = val
    for col, fld in TEXT_FIELDS:
        v = containers(d.get(fld)) if col == "Контейнер" else txt(d.get(fld))
        if v:
            o[col] = v
    for col, fld in DATE_FIELDS:
        v = d10(d.get(fld))
        if v:
            o[col] = v
    # ланки маршруту — кожна окремою колонкою; сам «Маршрут» збирається пізніше,
    # в основному циклі, бо для злиття потрібен маршрут, який уже стоїть у платформі
    if names.get("city"):
        parts = {}
        for col, fld in CITY_FIELDS:
            v = ref(names, "city", d.get(fld))
            if v:
                parts[col] = v
                o[col] = v
        dk = dry_field(d)
        if dk:
            v = ref(names, "city", d.get(dk))
            if v:
                parts[DRY_COL] = v
                o[DRY_COL] = v
        o[ROUTE_PARTS] = route_seq(parts)
    return o


# ---------------------------------------------------------------- основний цикл
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="показати зміни, нічого не писати")
    ap.add_argument("--limit", type=int, default=0, help="обробити лише перші N угод (тест)")
    ap.add_argument("--refresh-names", action="store_true", help="перечитати довідники")
    a = ap.parse_args()
    dry = a.dry_run
    tag = "[dry-run] " if dry else ""

    c = odata_client()
    names = load_names(c, force=a.refresh_names)

    posted = [d for d in c.list("Document_Сделка") if d.get("Posted")]
    cancelled = [d for d in posted if str(d.get("Статус") or "").strip() == CANCELLED_STAGE]
    deals = [d for d in posted if d not in cancelled]
    if a.limit:
        deals = deals[: a.limit]
    log("%sУгод з Експедитора (проведених): %d" % (tag, len(posted)))
    if cancelled:
        nums = sorted(num(d.get("Number")) for d in cancelled)
        log("%sСкасованих (в таблицю не вносимо і не оновлюємо): %d — угоди %s"
            % (tag, len(cancelled), ", ".join(nums)))
        if not dry:
            json.dump(nums, open(CANCELLED_FILE, "w", encoding="utf-8"), ensure_ascii=False)

    meta = nc_meta()
    line_values = {v for v in (line_option(ref(names, "line", d.get("Линия_Key"))) for d in deals) if v}
    allowed_lines = ensure_options(meta, "Лінія", line_values, dry)
    kind_values = {KIND_MAP[k] for k in
                   {str(d.get("Вид") or "").strip() for d in deals} if k in KIND_MAP}
    allowed_kinds = ensure_options(meta, "Напрямок", kind_values, dry)
    # «Скасована» має бути серед варіантів колонки — інакше запис не пройде
    allowed_statuses = ensure_options(meta, "Статус", {CANCELLED_STATUS}, dry)

    rows = nc_records(["Id", "Угода"] + WRITTEN_COLS)
    by_num = {}
    for r in rows:
        by_num.setdefault(num(r.get("Угода")), r)
    log("%sЗаписів у платформі: %d" % (tag, len(rows)))

    mark_cancelled(cancelled, by_num, allowed_statuses, dry)

    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            state = {}
    date_cols = {c for c, _ in DATE_FIELDS}

    to_create, to_update, eta_changes, route_lost = [], [], [], []
    field_hits, conflicts = {}, {}
    new_state = {}
    for d in deals:
        n = num(d.get("Number"))
        if not n:
            continue
        want = map_deal(d, names, allowed_lines, allowed_kinds, allowed_statuses)
        mine = state.get(n, {})
        cur = by_num.get(n)
        # «Маршрут» збираємо тут, бо треба бачити, що вже стоїть у платформі:
        # ланку, якої Експедитор ще не знає (сухий порт), не можна втрачати.
        seq = want.pop(ROUTE_PARTS, [])
        r, lost = merge_route(seq, (cur or {}).get("Маршрут"))
        if r:
            want["Маршрут"] = r
        if lost:
            route_lost.append("угода %s: %s" % (n, ", ".join(lost)))
        if cur is None:
            rec = dict(want)
            rec["Угода"] = n
            rec.setdefault("Статус", "Букінг")
            to_create.append(rec)
            for k in want:
                field_hits[k] = field_hits.get(k, 0) + 1
            new_state[n] = dict(want)
        else:
            patch, keep = {}, {}
            for col, val in want.items():
                old = cur.get(col)
                old_s = "" if old in (None, "") else (str(old)[:10] if col in date_cols else str(old))
                if old_s == str(val):
                    keep[col] = val          # уже збігається — вважаємо нашим
                    continue
                if col == "Статус" and old_s == CANCELLED_STATUS:
                    # угоду позначили скасованою вручну — Експедитор її не «воскрешає»
                    # (01.08.2026: інакше статус відкочувався назад за годину)
                    conflicts["Статус (скасована, не чіпаю)"] = \
                        conflicts.get("Статус (скасована, не чіпаю)", 0) + 1
                    continue
                if col == "Статус" and old_s == DELIVERED and val != DELIVERED:
                    # людина (або трекінг) уже позначила доставку — не понижуємо
                    conflicts["Статус (доставлено, не понижую)"] = \
                        conflicts.get("Статус (доставлено, не понижую)", 0) + 1
                    continue
                if col == "Статус" and val == VAGUE and old_s and old_s != VAGUE:
                    # «Виконується» — заглушка Експедитора, вона нічого не каже про етап.
                    # У платформі вже стоїть конкретний статус (ручна правка або трекінг) —
                    # він головніший (рішення користувачки 02.08.2026).
                    conflicts["Статус (Виконується не перекриває конкретний)"] = \
                        conflicts.get("Статус (Виконується не перекриває конкретний)", 0) + 1
                    continue
                if col not in AUTHORITATIVE and old_s and old_s != str(mine.get(col, "")):
                    # у платформі чуже значення (трекінг або ручна правка) — не чіпаємо
                    conflicts[col] = conflicts.get(col, 0) + 1
                    continue
                patch[col] = val
                keep[col] = val
                field_hits[col] = field_hits.get(col, 0) + 1
            if patch:
                patch["Id"] = cur["Id"]
                to_update.append(patch)
            if keep:
                new_state[n] = keep
        new_eta = want.get("ETA")
        old_eta = mine.get("ETA")
        if new_eta and old_eta and new_eta != old_eta:
            eta_changes.append("угода %s: ETA %s → %s" % (n, old_eta, new_eta))

    log("%sНових угод: %d, оновити наявних: %d" % (tag, len(to_create), len(to_update)))
    if field_hits:
        log("%sЗапис по колонках: %s" % (tag, ", ".join(
            "%s=%d" % (k, v) for k, v in sorted(field_hits.items(), key=lambda x: -x[1]))))
    if conflicts:
        log("%sНЕ чіпала (у платформі чужі значення): %s" % (tag, ", ".join(
            "%s=%d" % (k, v) for k, v in sorted(conflicts.items(), key=lambda x: -x[1]))))
    if route_lost:
        # маршрут з Експедитора виявився БІДНІШИЙ за той, що в платформі —
        # нічого не переписали, лише показуємо, де саме розходження
        log("%sМаршрут НЕ переписано, бо зникли б ланки (%d): %s"
            % (tag, len(route_lost), "; ".join(route_lost[:15])))
    if eta_changes:
        log("%sETA змінилась в Експедиторі (%d): %s" % (tag, len(eta_changes), "; ".join(eta_changes[:15])))
    elif not state:
        log("%sETA: перший прогін — базу зафіксовано, зміни відслідковуються з наступного разу" % tag)

    if dry:
        for r in to_create[:5]:
            log("DRY створити: %s" % json.dumps(r, ensure_ascii=False)[:220])
        for r in to_update[:8]:
            log("DRY оновити: %s" % json.dumps(r, ensure_ascii=False)[:220])
        log("DRY_DONE nothing_written")
        return

    errors = 0
    for i in range(0, len(to_create), CHUNK):
        st, js = nc("POST", "/api/v2/tables/%s/records" % TABLE, to_create[i:i + CHUNK])
        if st not in (200, 201):
            errors += 1
            log("CREATE_FAIL %s %s" % (st, str(js)[:200]))
    for i in range(0, len(to_update), CHUNK):
        st, js = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, to_update[i:i + CHUNK])
        if st not in (200, 201):
            errors += 1
            log("UPDATE_FAIL %s %s" % (st, str(js)[:200]))

    if errors == 0:
        json.dump(new_state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    else:
        log("WARN стан не збережено через помилки запису — наступний прогін повторить спробу")
    log("DONE deals=%d new=%d updated=%d errors=%d" % (len(deals), len(to_create), len(to_update), errors))
    print("SYNC_OK deals=%d new=%d updated=%d errors=%d"
          % (len(deals), len(to_create), len(to_update), errors))


# Замок «один запуск за раз» — див. direct_sync/runlock.py.
# Таймер, кнопка на платформі і ручний запуск можуть накластися;
# два паралельні прогони створюють дублікати угод у базі.
if __name__ == "__main__":
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from runlock import single_run
    with single_run("expeditor"):
        main()
