#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Звірка дат і статусів у платформі з подіями перевізника. ТІЛЬКИ ЧИТАЄ.

Навіщо (03.08.2026, користувачка: «дуже багато помилок з датою прибуття та
статусами»): за один день знайшлися дві помилки одного типу — бралася подія
не того плеча маршруту (судно з останнього плеча замість першого; дата
прибуття потяга замість приходу судна в порт). Обидві були НЕ видні окремо:
статус виглядав правильним, а дата — ні.

Ця перевірка не виправляє нічого. Вона бере кожну угоду, дивиться на реальні
події Maersk і шукає СУПЕРЕЧНОСТІ — випадки, коли одне значення в платформі
не узгоджується з іншим або з подіями.

Запуск: python3 /root/direct-sync/audit_tracking.py [--limit N]
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import maersk_track_sync as M  # noqa: E402

TODAY = datetime.date.today().isoformat()


def d10(v):
    s = str(v or "").strip()
    return s[:10] if len(s) >= 10 else ""


def ev_rows(events):
    """Події у зручному вигляді: (дата, код, факт/прогноз, транспорт, місце, судно)."""
    out = []
    for e in events or []:
        tc = e.get("transportCall") or {}
        code = (e.get("transportEventTypeCode") or e.get("equipmentEventTypeCode")
                or e.get("shipmentEventTypeCode") or "")
        out.append({
            "date": M._dt(e)[:10],
            "code": code,
            "act": e.get("eventClassifierCode") == "ACT",
            "mode": (tc.get("modeOfTransport") or ""),
            "place": ((tc.get("location") or {}).get("locationName") or ""),
            "vessel": ((tc.get("vessel") or {}).get("vesselName") or ""),
        })
    out.sort(key=lambda x: x["date"])
    return out


def check(row, ev):
    """Список знайдених суперечностей для однієї угоди."""
    bad = []
    st = str(row.get("Статус") or "").strip()
    eta_port = d10(row.get("ETA порт (факт)")) or d10(row.get("ETA порт (план)"))
    disc = d10(row.get("Вивантаження в порту (факт)"))
    dry = d10(row.get("ETA сухий порт"))
    eta = d10(row.get("ETA"))
    vessel = str(row.get("Судно") or "").strip()

    act = [e for e in ev if e["act"] and e["date"] <= TODAY]
    arr_v = [e for e in ev if e["code"] == "ARRI" and e["mode"] == "VESSEL"]
    disc_v = [e for e in ev if e["code"] == "DISC" and e["mode"] == "VESSEL" and e["act"]]
    arr_rail = [e for e in ev if e["code"] == "ARRI" and e["mode"] == "RAIL"]
    ves_named = [e for e in ev if e["mode"] == "VESSEL" and e["vessel"]]

    # 1. статус каже «вивантажений», а фактичного вивантаження в подіях немає
    if st == "Вивантажений в порту прибуття" and not disc_v:
        bad.append("статус «вивантажений», але фактичної події DISC немає")

    # 2. статус «В морі», хоча фактичне вивантаження вже було
    if st == "В морі" and disc_v:
        bad.append("статус «В морі», хоча вивантаження вже було %s" % disc_v[-1]["date"])

    # 3. дата вивантаження в платформі не збігається з подією
    if disc_v and disc and disc != disc_v[-1]["date"]:
        bad.append("вивантаження в платформі %s, у подіях %s" % (disc, disc_v[-1]["date"]))

    # 4. ETA порт не збігається з прибуттям судна
    if arr_v and eta_port and eta_port != arr_v[-1]["date"]:
        bad.append("ETA порт %s, а прихід судна %s (%s)"
                   % (eta_port, arr_v[-1]["date"], arr_v[-1]["place"][:18]))

    # 5. вивантаження раніше за прихід у порт — так не буває
    if disc and eta_port and disc < eta_port:
        bad.append("вивантаження %s РАНІШЕ за прихід у порт %s" % (disc, eta_port))

    # 6. сухий порт раніше за вивантаження — так не буває
    if dry and disc and dry < disc:
        bad.append("сухий порт %s РАНІШЕ за вивантаження %s" % (dry, disc))

    # 7. дата прибуття потяга є в подіях, але в платформі порожньо
    if arr_rail and ves_named and not dry:
        bad.append("є прибуття потяга %s, а «ETA сухий порт» порожній"
                   % arr_rail[-1]["date"])

    # 8. судно в платформі не збігається з жодним судном у подіях
    if vessel and ves_named and vessel not in {e["vessel"] for e in ves_named}:
        bad.append("судно «%s» немає серед суден рейсу (%s)"
                   % (vessel, ", ".join(sorted({e["vessel"] for e in ves_named}))[:40]))

    # 9. ETA в майбутньому, хоча вантаж уже вивантажено
    if disc_v and eta and eta > TODAY:
        bad.append("ETA %s у майбутньому, хоча вивантаження було %s"
                   % (eta, disc_v[-1]["date"]))

    # 10. статус не оновлювався, хоча є свіжі фактичні події
    if act and st and st != M.DELIVERED:
        last = act[-1]
        upd = d10(row.get("Останнє оновлення"))
        if upd and last["date"] > upd:
            bad.append("є фактична подія %s (%s), новіша за останнє оновлення %s"
                       % (last["date"], last["code"], upd))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    env = M.load_env()
    token = M.maersk_token(env)
    rows = M.nc_records()
    cancelled = M.cancelled_numbers()

    todo = []
    for r in rows:
        if M.deal_no(r.get("Угода")) in cancelled:
            continue
        bl = str(r.get("BL") or "").strip()
        cont = str(r.get("Контейнер") or "").strip()
        if M.BL_RE.match(bl) or M.CONT_RE.match(cont):
            todo.append(r)
    if a.limit:
        todo = todo[:a.limit]

    print("перевіряю угод: %d (усього в платформі %d)" % (len(todo), len(rows)))
    problems, nodata, checked = [], 0, 0
    for r in todo:
        bl = str(r.get("BL") or "").strip()
        cont = str(r.get("Контейнер") or "").strip()
        ev = None
        if M.BL_RE.match(bl):
            ev, _ = M.maersk_events(env, token, bl)
        if not ev and M.CONT_RE.match(cont):
            ev, _ = M.maersk_events(env, token, cont, param="equipmentReference")
        if not ev:
            nodata += 1
            continue
        checked += 1
        bad = check(r, ev_rows(ev))
        if bad:
            problems.append((M.deal_no(r.get("Угода")), str(r.get("Статус") or ""), bad))

    print("звірено з подіями: %d, без даних у Maersk: %d" % (checked, nodata))
    print("угод із суперечностями: %d" % len(problems))
    print()
    for num, st, bad in sorted(problems, key=lambda x: int(x[0]) if x[0].isdigit() else 0):
        print("угода %-5s [%s]" % (num, st[:28]))
        for b in bad:
            print("    • %s" % b)
    # зведення за типами — щоб побачити, чи помилки СИСТЕМНІ
    print()
    print("ЗА ТИПАМИ:")
    kinds = {}
    for _, _, bad in problems:
        for b in bad:
            key = b.split(",")[0].split(" (")[0][:52]
            kinds[key] = kinds.get(key, 0) + 1
    for k, v in sorted(kinds.items(), key=lambda x: -x[1]):
        print("   %3d × %s" % (v, k))
    print("AUDIT_DONE problems=%d checked=%d nodata=%d" % (len(problems), checked, nodata))


if __name__ == "__main__":
    main()
