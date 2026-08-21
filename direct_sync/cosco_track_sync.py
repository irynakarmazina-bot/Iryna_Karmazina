#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Трекінг COSCO → платформа (NocoDB «Диспетчеризація») напряму, без ключів і посередників.

Джерело: публічний ендпойнт трекінгу COSCO, той самий, яким користується їхній сайт:
    https://elines.coscoshipping.com/ebtracking/public/bill/<номер>
ВАЖЛИВО (перевірено 30.07.2026): номер треба передавати БЕЗ префікса «COSU» —
з префіксом ендпойнт відповідає «无数据» (немає даних).

Чому саме сайтовий шлях: користувачка попросила спершу спробувати забір «через сайт
та трекінг», без агрегаторів. З перевірених ліній лише COSCO віддає дані з сервера;
Maersk / MSC / CMA CGM / Hapag-Lloyd з нашого IP повертають 403 (захист від ботів),
для них потрібні їхні власні API (MSC і Hapag — окремою задачею).

Що пише: Судно, Вояж, ETA, ETA порт (план/факт), ETD (план/факт),
Вивантаження в порту (факт), Контейнер (лінія), Статус, Зміни ETA (історія),
Остання зміна, Останнє оновлення. Статус «Вантаж доставлено» не перезаписує.

Запуск: python3 /root/direct-sync/cosco_track_sync.py [--dry-run]
Лог:    /root/direct-sync/cosco.log
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
LOG = os.path.join(WORKDIR, "cosco.log")

NC = "http://localhost:8080"
TABLE = "m58xsjo6at01ohl"
TOKEN_FILE = "/root/nocodb-token.txt"
CHUNK = 25

API = "https://elines.coscoshipping.com/ebtracking/public/bill/%s"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
THROTTLE = 2.0
LINE = "COSCO"
DELIVERED = "Вантаж доставлено"
# Автомат перебиває лише те, що поставив автомат: якщо статус виставила
# людина, трекінг його не чіпає (рішення користувачки 05.08.2026).
STATUS_SRC = "трекінг COSCO"
HUMAN_SRC = "людина"
READ_FIELDS = ["Id", "Угода", "Лінія", "BL", "Контейнер", "Контейнер (лінія)", "ETA",
               "ETA порт (план)", "ETA порт (факт)", "ETD (план)", "ETD (факт)",
               "Вивантаження в порту (факт)", "Статус", "Судно", "Вояж",
               "Зміни ETA (історія)", "Остання зміна", "Останнє оновлення",
               # 05.08.2026: хто поставив статус — див. STATUS_SRC нижче
               "Статус (джерело)", "Статус (оновлено)"]
DATE_COLS = {"ETA", "ETA порт (план)", "ETA порт (факт)", "ETD (план)", "ETD (факт)",
             "Вивантаження в порту (факт)"}


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


def statuses_allowed():
    st, js = nc("GET", "/api/v2/meta/tables/%s" % TABLE)
    if st != 200:
        return set()
    col = next((c for c in js["columns"] if c["title"] == "Статус"), None)
    return {o["title"] for o in ((col or {}).get("colOptions") or {}).get("options", [])}


def cosco_bill(number):
    """Дані по коносаменту. Номер — без префікса «COSU»."""
    ref = re.sub(r"^[A-Za-z]+", "", str(number or "").strip())
    if not ref:
        return None, "порожній номер"
    req = urllib.request.Request(API % urllib.parse.quote(ref),
                                 headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            js = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return None, "HTTP %d" % e.code
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:80]
    content = ((js.get("data") or {}).get("content") or {})
    if not content or not content.get("isbillOfLadingExist"):
        return None, "немає даних (%s)" % (js.get("message") or "")
    return content, ""


def d10(v):
    s = str(v or "")
    return s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", s) else None


def parse_content(content, row, today_iso, allowed):
    out = {}
    legs = [l for l in (content.get("actualShipment") or []) if isinstance(l, dict)]
    path = content.get("trackingPath") or {}
    first, last = (legs[0] if legs else {}), (legs[-1] if legs else {})

    vessel = last.get("vesselName") or path.get("vslNme")
    voyage = last.get("voyageNo") or path.get("voyNumber")
    if vessel:
        out["Судно"] = str(vessel).strip()
    if voyage:
        out["Вояж"] = str(voyage).strip()

    conts = [c.get("cntrNum") for c in (content.get("cargoTrackingContainer") or [])
             if isinstance(c, dict) and c.get("cntrNum")]
    if conts:
        out["Контейнер (лінія)"] = ", ".join(conts)
        if not str(row.get("Контейнер") or "").strip():
            out["Контейнер"] = conts[0]

    for col, val in (("ETD (план)", first.get("expectedDateOfDeparture")),
                     ("ETD (факт)", first.get("actualDepartureDate")),
                     ("ETA порт (план)", last.get("estimatedDateOfArrival")),
                     ("ETA порт (факт)", last.get("actualArrivalDate")),
                     ("Вивантаження в порту (факт)", last.get("actualDischargeDate"))):
        v = d10(val)
        if v:
            out[col] = v

    eta = out.get("ETA порт (факт)") or out.get("ETA порт (план)")
    if eta:
        out["ETA"] = eta
        old = str(row.get("ETA порт (план)") or "")[:10]
        new_plan = out.get("ETA порт (план)")
        if new_plan and old and old != new_plan:
            hist = str(row.get("Зміни ETA (історія)") or "")
            out["Зміни ETA (історія)"] = (hist + "\n" if hist else "") + \
                "%s: ETA порт: %s → %s (COSCO)" % (today_iso, old, new_plan)
            out["Остання зміна"] = today_iso

    st = ""
    if out.get("Вивантаження в порту (факт)") or out.get("ETA порт (факт)"):
        st = "Вивантажений в порту прибуття"
    elif out.get("ETD (факт)"):
        st = "В морі"
    was = str(row.get("Статус") or "")
    if (st and st in allowed and was != DELIVERED and st != was
            and str(row.get("Статус (джерело)") or "").strip() != HUMAN_SRC):
        out["Статус"] = st
        # джерело і дату пишемо тільки разом зі зміною статусу, інакше дата
        # оновлювалася б щодня і давала б порожні «зміни» щопрогону
        out["Статус (джерело)"] = STATUS_SRC
        out["Статус (оновлено)"] = today_iso

    out["Останнє оновлення"] = today_iso
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    tag = "[dry-run] " if a.dry_run else ""
    today_iso = datetime.date.today().isoformat()

    allowed = statuses_allowed()
    cancelled = cancelled_numbers()
    rows = nc_records()
    todo = [r for r in rows
            if str(r.get("Лінія") or "") == LINE
            and str(r.get("BL") or "").strip()
            and str(r.get("Статус") or "") != DELIVERED
            and deal_no(r.get("Угода")) not in cancelled]
    # 🔒 ЗАПОБІЖНИК ВІД «ДВІЙНИКА» (21.08.2026) — те саме правило, що в Maersk-трекінгу:
    # один BL у кількох рядках → не заповнюємо жоден, конфлікт іде в лог і в
    # «Журнал дій». Видимої позначки в «Трекінг (стан)» тут НЕ ставимо: цей скрипт
    # її ніколи не стирає, і позначка лишилась би висіти після розв'язання конфлікту.
    by_bl = {}
    for r in todo:
        by_bl.setdefault(str(r.get("BL")).strip(), []).append(r)
    dup_ids = set()
    for bl, rs in sorted(by_bl.items()):
        if len(rs) < 2:
            continue
        deals_all = sorted(str(x.get("Угода") or "") for x in rs)
        log("%s🔴 КОНФЛІКТ КОНОСАМЕНТА: BL %s одночасно в угодах %s — жодну не оновлюю"
            % (tag, bl, ", ".join(deals_all)))
        dup_ids.update(r["Id"] for r in rs)
        if not a.dry_run:
            try:
                import journal_note
                journal_note.note("трекінг COSCO", "конфлікт коносамента",
                                  "угоди " + ", ".join(deals_all), "BL", bl,
                                  "жодну не оновлюю, приберіть зайвий BL")
            except Exception:  # noqa: BLE001 — журнал не має валити трекінг
                pass
    if dup_ids:
        todo = [r for r in todo if r["Id"] not in dup_ids]
    log("%sУгод COSCO для трекінгу: %d (усього в платформі %d)" % (tag, len(todo), len(rows)))
    if not todo:
        print("COSCO_OK tracked=0 updated=0")
        return

    patches, no_data, changed = [], [], {}
    for i, row in enumerate(todo):
        if i:
            time.sleep(THROTTLE)
        content, note = cosco_bill(row.get("BL"))
        if not content:
            no_data.append("%s(%s)" % (row.get("BL"), note))
            continue
        want = parse_content(content, row, today_iso, allowed)
        patch = {}
        for col, val in want.items():
            old = str(row.get(col) or "")
            old = old[:10] if col in DATE_COLS else old
            if old != str(val):
                patch[col] = val
                changed[col] = changed.get(col, 0) + 1
        if patch:
            patch["Id"] = row["Id"]
            patches.append(patch)

    log("%sОновити: %d; без даних: %d" % (tag, len(patches), len(no_data)))
    if changed:
        log("%sЗміни по колонках: %s" % (tag, ", ".join(
            "%s=%d" % kv for kv in sorted(changed.items(), key=lambda x: -x[1]))))
    if no_data:
        log("%sБез даних у COSCO: %s" % (tag, ", ".join(no_data[:15])))

    if a.dry_run:
        for p in patches[:5]:
            log("DRY: %s" % json.dumps(p, ensure_ascii=False)[:250])
        print("COSCO_DRY tracked=%d would_update=%d" % (len(todo), len(patches)))
        return

    fails = 0
    for i in range(0, len(patches), CHUNK):
        part = patches[i:i + CHUNK]
        st, js = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, part)
        if st in (200, 201):
            continue
        log("UPDATE_FAIL порція: %s %s — пробую по одному" % (st, str(js)[:150]))
        for one in part:
            st1, js1 = nc("PATCH", "/api/v2/tables/%s/records" % TABLE, [one])
            if st1 not in (200, 201):
                fails += 1
                log("UPDATE_FAIL Id=%s: %s %s" % (one.get("Id"), st1, str(js1)[:150]))
    log("DONE tracked=%d updated=%d nodata=%d write_fails=%d"
        % (len(todo), len(patches), len(no_data), fails))
    print("COSCO_OK tracked=%d updated=%d nodata=%d write_fails=%d"
          % (len(todo), len(patches), len(no_data), fails))


# Замок «один запуск за раз» — див. direct_sync/runlock.py.
# Таймер, кнопка на платформі і ручний запуск можуть накластися;
# два паралельні прогони створюють дублікати угод у базі.
if __name__ == "__main__":
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from runlock import single_run
    with single_run("cosco"):
        main()
