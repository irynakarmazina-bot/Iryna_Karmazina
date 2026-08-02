#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ДІАГНОСТИКА: чому в угоді порожня колонка «Судно».

Нічого не змінює — тільки читає платформу і, для угод Maersk, питає їхнє API,
щоб побачити справжню причину, а не здогадуватись. Питання користувачки
02.08.2026: «ще дуже багато угод без назви судна, чому ти не можеш його взяти?»

Причини, які скрипт розрізняє:
  АВІА/АВТО   — судна немає за визначенням;
  НЕ MAERSK   — у нас є API тільки в Maersk; MSC / CMA CGM / Hapag / COSCO / EMC
                тягнемо руками (рішення користувачки — агрегаторів не беремо);
  БЕЗ НОМЕРА  — немає ні коносамента, ні контейнера, шукати нічим;
  404         — Maersk не віддає цю відправку (ми не сторона по коносаменту);
  БЕЗ VESSEL  — події є, але жодна з них не має назви судна;
  Є СУДНО     — API назву віддає, значить її просто не записали (це вже мій баг).

Запуск: python3 why_no_vessel.py [--limit N]   (тільки читання)
"""
import argparse
import sys

sys.path.insert(0, "/root/direct-sync")
sys.path.insert(0, "/root/Iryna_Karmazina/direct_sync")
import maersk_track_sync as M  # noqa: E402


def s(row, key):
    return str(row.get(key) or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="скільки угод Maersk перевірити в API")
    a = ap.parse_args()

    # READ_FIELDS трекера не містить «Вид перевезення» — без нього неможливо
    # відокремити авіа й авто, де судна немає за визначенням. Додаємо на час
    # діагностики (сам трекер не чіпаємо).
    for extra in ("Вид перевезення", "Напрямок"):
        if extra not in M.READ_FIELDS:
            M.READ_FIELDS.append(extra)

    cancelled = M.cancelled_numbers()
    rows = [r for r in M.nc_records() if M.deal_no(r.get("Угода")) not in cancelled]
    empty = [r for r in rows if not s(r, "Судно")]
    print("Усього угод (без скасованих): %d" % len(rows))
    print("З них БЕЗ назви судна: %d" % len(empty))
    print()

    groups = {"АВІА/АВТО": [], "НЕ MAERSK": [], "БЕЗ НОМЕРА": [], "MAERSK — перевіряємо": []}
    for r in empty:
        mode = s(r, "Вид перевезення").lower()
        line = s(r, "Лінія")
        if "авіа" in mode or mode == "авто":
            groups["АВІА/АВТО"].append(r)
        elif line and line.lower() != "maersk":
            groups["НЕ MAERSK"].append(r)
        elif not s(r, "BL") and not s(r, "Контейнер"):
            groups["БЕЗ НОМЕРА"].append(r)
        else:
            groups["MAERSK — перевіряємо"].append(r)

    for name in ("АВІА/АВТО", "НЕ MAERSK", "БЕЗ НОМЕРА"):
        g = groups[name]
        print("%-12s %3d  %s" % (name, len(g),
              ", ".join(sorted((M.deal_no(x.get("Угода")) for x in g), key=lambda v: (len(v), v)))[:400]))
    if groups["НЕ MAERSK"]:
        by_line = {}
        for r in groups["НЕ MAERSK"]:
            by_line.setdefault(s(r, "Лінія"), []).append(M.deal_no(r.get("Угода")))
        print("      ↳ по лініях: " + "; ".join(
            "%s — %d" % (k, len(v)) for k, v in sorted(by_line.items(), key=lambda kv: -len(kv[1]))))
    print()

    todo = groups["MAERSK — перевіряємо"]
    if a.limit:
        todo = todo[:a.limit]
    print("MAERSK з номером — питаємо API: %d угод" % len(todo))
    print("-" * 74)
    env = M.load_env()
    token = M.maersk_token(env)
    tally = {"404": [], "БЕЗ VESSEL": [], "Є СУДНО": [], "ІНШЕ": []}
    for r in todo:
        num = M.deal_no(r.get("Угода"))
        events, how, note = M.collect_events(env, token, s(r, "BL"), s(r, "Контейнер"))
        if not events:
            key = "404" if "404" in note else "ІНШЕ"
            tally[key].append((num, note))
            print("%-6s %-11s %s" % (num, key, note))
            continue
        names = []
        for e in events:
            v = ((e.get("transportCall") or {}).get("vessel") or {}).get("vesselName")
            if v and v not in names:
                names.append(v)
        if names:
            tally["Є СУДНО"].append((num, names[-1]))
            print("%-6s %-11s %s   (подій %d, знайшли по: %s)" % (num, "Є СУДНО", names[-1], len(events), how))
        else:
            tally["БЕЗ VESSEL"].append((num, "подій %d" % len(events)))
            print("%-6s %-11s подій %d, жодна не має vesselName" % (num, "БЕЗ VESSEL", len(events)))

    print("-" * 74)
    for k, v in tally.items():
        if v:
            print("%-11s %3d  %s" % (k, len(v), ", ".join(x[0] for x in v)[:300]))


if __name__ == "__main__":
    main()
