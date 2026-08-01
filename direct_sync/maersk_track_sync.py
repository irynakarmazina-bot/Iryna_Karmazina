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
# Статус «Завантажений» РОЗДІЛЕНИЙ на авто і потяг (рішення користувачки 30.07.2026):
# у колонці «Статус» є варіанти «Завантажений на авто» і «Завантажений на потяг»,
# старий об'єднаний «Завантажений на авто/потяг» прибрано на її прохання
# (жоден запис його не використовував; бекап варіантів — status_options.bak.json).
# Читаємо з платформи ВСІ колонки, які потім пишемо, інакше порівняння «старе != нове»
# завжди істинне і скрипт переписує ті самі значення щопрогону. Саме так було до
# 01.08.2026 з «Гейт ін», «Гейт аут», «ETD (факт)/(план)» і «Вивантаження в порту (факт)»:
# лог показував 156 «змін» при нулі нових даних.
READ_FIELDS = ["Id", "Угода", "BL", "Контейнер", "Контейнер (лінія)", "ETA",
               "ETA порт (план)", "ETA порт (факт)", "Статус", "Судно", "Вояж",
               "Зміни ETA (історія)", "Звірка", "Лінія",
               "Гейт ін", "Гейт аут", "ETD (факт)", "ETD (план)",
               "Вивантаження в порту (факт)",
               "Порт перевалки", "Перевалка (прибуття)", "Перевалка (відправлення)",
               "Остання зміна", "Останнє оновлення"]


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
TOK = open(TOKEN_FILE).read().strip()


def nc(method, path, data=None):
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
    arr = sorted([e for e in events if e.get("transportEventTypeCode") == "ARRI"
                  or e.get("equipmentEventTypeCode") == "ARRI"], key=_dt)
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
    named_ves = [e for e in ves
                 if ((e.get("transportCall") or {}).get("vessel") or {}).get("vesselName")]
    if named_ves:
        tc = named_ves[-1].get("transportCall") or {}
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
        sea_legs.append((code, _dt(e)[:10], (tc.get("location") or {}).get("locationName") or ""))
    disc_idx = [i for i, l in enumerate(sea_legs) if l[0] == "DISC"]
    if len(disc_idx) > 1:
        ports, arr, dep = [], "", ""
        for i in disc_idx[:-1]:                      # усі, крім порту призначення
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
    disc = pick(("DISC",), "ACT", "VESSEL", last=True)
    if disc:
        out["Вивантаження в порту (факт)"] = disc
    # виїзд із порту — контейнер забрали
    gtot = pick(("GTOT",), "ACT", last=True)
    if gtot:
        out["Гейт аут"] = gtot

    # статус: 8-модель, «Завантажений» розділений на авто/потяг
    last = sorted(events, key=_dt)[-1]
    mode = (last.get("transportCall") or {}).get("modeOfTransport") or ""
    code = (last.get("equipmentEventTypeCode") or last.get("transportEventTypeCode")
            or last.get("shipmentEventTypeCode") or "")
    is_vessel = mode in ("VESSEL", "")
    load_st = "Завантажений на потяг" if mode == "RAIL" else "Завантажений на авто"
    st = ""
    if code in ("LOAD", "DEPA"):
        st = "В морі" if is_vessel else load_st
    elif code == "ARRI":
        st = "В морі" if mode == "VESSEL" else load_st
    elif code == "DISC":
        st = "Вивантажений в порту прибуття" if is_vessel else load_st
    elif code == "GTOT":
        st = load_st
    elif code == "GTIN":
        st = DELIVERED if mode == "TRUCK" else load_st
    if st and str(row.get("Статус") or "") != DELIVERED:
        out["Статус"] = st

    out["Останнє оновлення"] = today_iso
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
    for bl, row in todo:
        cont = str(row.get("Контейнер") or "").split(",")[0].strip()
        events, how, note = collect_events(env, token, bl, cont)
        if not events:
            key = bl or str(row.get("Контейнер") or "").split(",")[0].strip()
            bucket = no_data if "404" in str(note) else (foreign if "400" in str(note) else errors)
            bucket.append("угода %s/%s" % (row.get("Угода"), key)
                          if bucket is foreign else
                          "угода %s/%s(%s)" % (row.get("Угода"), key, note or "порожньо"))
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
            if val == "" and not old:
                continue
            if old != str(val):
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


if __name__ == "__main__":
    main()
