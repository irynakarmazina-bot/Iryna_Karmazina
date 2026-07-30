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
DELIVERED = "Вантаж доставлено"
# У n8n-логіці статус «Завантажений» розділений на авто/потяг, а в платформі
# затверджена 8-модель з одним варіантом. Зводимо до наявного варіанта.
STATUS_MAP = {
    "Завантажений на потяг": "Завантажений на авто/потяг",
    "Завантажений на авто": "Завантажений на авто/потяг",
}
READ_FIELDS = ["Id", "Угода", "BL", "Контейнер", "Контейнер (лінія)", "ETA",
               "ETA порт (план)", "ETA порт (факт)", "Статус", "Судно", "Вояж",
               "Зміни ETA (історія)", "Звірка", "Лінія",
               "Остання зміна", "Останнє оновлення"]


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


def maersk_events(env, token, value, param="carrierBookingReference", url=EVENTS_URL):
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
def _dt(e):
    return str(e.get("eventDateTime") or "")


def parse_events(events, row, today_iso):
    """Портована логіка вузла «Розбір». Повертає {колонка: значення}."""
    out = {}
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
    last_ves = ves[-1] if ves else None
    arr = sorted([e for e in events if e.get("transportEventTypeCode") == "ARRI"
                  or e.get("equipmentEventTypeCode") == "ARRI"], key=_dt)
    last_arr = arr[-1] if arr else None

    eta_iso, actual = "", False
    if last_arr:
        eta_iso = _dt(last_arr)[:10]
        actual = last_arr.get("eventClassifierCode") == "ACT"

    days = 999
    if re.match(r"^\d{4}-\d{2}-\d{2}$", eta_iso):
        d0 = datetime.date.fromisoformat(today_iso)
        days = (datetime.date.fromisoformat(eta_iso) - d0).days
    else:
        eta_iso = ""

    if last_ves and days <= 7:
        tc = last_ves.get("transportCall") or {}
        vessel = (tc.get("vessel") or {}).get("vesselName") or ""
        voyage = tc.get("carrierVoyageNumber") or tc.get("exportVoyageNumber") or tc.get("importVoyageNumber") or ""
        if vessel:
            out["Судно"] = vessel
        if voyage:
            out["Вояж"] = voyage

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
    st = STATUS_MAP.get(st, st)
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
    rows = nc_records()
    todo = []
    for r in rows:
        bl = str(r.get("BL") or "").strip()
        if not BL_RE.match(bl):
            continue
        if not a.all and str(r.get("Статус") or "") == DELIVERED:
            continue
        todo.append((bl, r))
    if a.limit:
        todo = todo[: a.limit]
    log("%sУгод для трекінгу: %d (усього в платформі %d)" % (tag, len(todo), len(rows)))
    if not todo:
        print("MAERSK_OK tracked=0 updated=0")
        return

    token = maersk_token(env)
    log("%sТокен Maersk отримано" % tag)

    patches, no_data, errors, changed_cols = [], [], [], {}
    by_container = []
    for i, (bl, row) in enumerate(todo):
        if i:
            time.sleep(THROTTLE)
        events, note = maersk_events(env, token, bl)
        if not events:
            # запасні шляхи: по номеру контейнера, потім публічний ендпойнт
            cont = str(row.get("Контейнер") or "").split(",")[0].strip()
            if cont:
                time.sleep(THROTTLE)
                events, note2 = maersk_events(env, token, cont, "equipmentReference")
                if events:
                    by_container.append("%s→%s" % (bl, cont))
                    note = note2
            if not events:
                time.sleep(THROTTLE)
                events, note3 = maersk_events(env, token, bl, "carrierBookingReference", EVENTS_URL_PUBLIC)
                note = note or note3
        if events is None:
            (no_data if "404" in str(note) else errors).append("%s(%s)" % (bl, note))
            continue
        if not events:
            no_data.append("%s(порожньо)" % bl)
            continue
        want = parse_events(events, row, today_iso)
        if want.get("Статус") and statuses and want["Статус"] not in statuses:
            log("WARN статус «%s» не входить у варіанти колонки — не пишу (угода %s)"
                % (want["Статус"], row.get("Угода")))
            want.pop("Статус")
        patch = {}
        for col, val in want.items():
            old = str(row.get(col) or "")
            old = old[:10] if col.startswith("ETA") or col in ("Остання зміна", "Останнє оновлення") else old
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
    if by_container:
        log("%sЗнайдено по номеру контейнера (букінг Maersk не знає): %s" % (tag, ", ".join(by_container[:20])))
    if no_data:
        log("%sБез даних у Maersk: %s" % (tag, ", ".join(no_data[:20])))
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
    log("DONE tracked=%d updated=%d nodata=%d api_errors=%d write_fails=%d"
        % (len(todo), len(patches), len(no_data), len(errors), fails))
    print("MAERSK_OK tracked=%d updated=%d nodata=%d api_errors=%d write_fails=%d"
          % (len(todo), len(patches), len(no_data), len(errors), fails))


if __name__ == "__main__":
    main()
