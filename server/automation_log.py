#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Журнал роботи АВТОМАТИКИ у вигляді, придатному для показу в платформі.

НАВІЩО (вимога користувачки 11.08.2026): «маю бачити, зроби в налаштуваннях».
Журнал дій ЛЮДЕЙ у платформі є, а журнал роботи автоматики лежав тільки на
сервері у файлі. Через це збої були невидимі: 11.08 трекінг чесно записав
«угода 251 / 274014640 — 404 немає даних», а на екрані стояло просто
«застаріло», тобто «дані старі» — зовсім інше за змістом.

ЩО РОБИТЬ: читає /root/direct-sync/maersk.log, збирає з нього останні прогони
і складає короткий JSON. Платформа читатиме його тим самим захищеним шляхом,
яким уже бере фінансові дані (/finrep-data), — там перевірка ролі вже працює,
нових дірок не з'являється.

Нічого не змінює і не видаляє: тільки читає журнал і пише один файл-підсумок.

Запуск: python3 /root/automation_log.py [--out <файл>] [--runs N]
"""
import json
import os
import re
import sys

LOG = "/root/direct-sync/maersk.log"
FINDATA = "/root/findata.py"
DEFAULT_RUNS = 20

TS = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
RE_START = re.compile(TS + r" Угод для трекінгу: (\d+)")
RE_DONE = re.compile(TS + r" Оновити угод: (\d+); без даних: (\d+); помилки: (\d+)")
RE_NODATA = re.compile(TS + r" Без даних у Maersk: (.+)")
RE_OTHER_LINE = re.compile(TS + r" Контейнер іншої лінії[^:]*: (.+)")
# «угода 251/274014640(404 немає даних)»
RE_ITEM = re.compile(r"угода (\d+)/([^()]+)\(([^)]+)\)")


def computed_dir():
    """Тека, з якої findata.py віддає файли. Беремо з нього самого, не вгадуємо."""
    try:
        src = open(FINDATA, encoding="utf-8").read()
        m = re.search(r'^COMPUTED\s*=\s*["\']([^"\']+)["\']', src, re.M)
        if m:
            return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return "/root/unitex-finrep/computed"


def parse(path, limit):
    runs, cur = [], None
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except FileNotFoundError:
        return []
    for ln in lines:
        if "[dry-run]" in ln:
            continue                      # прогони вхолосту в журнал не показуємо
        m = RE_START.match(ln)
        if m:
            cur = {"почався": m.group(1), "угод": int(m.group(2)),
                   "оновлено": None, "без_даних": 0, "помилки": 0, "деталі": []}
            runs.append(cur)
            continue
        if cur is None:
            continue
        m = RE_DONE.match(ln)
        if m:
            cur["завершився"] = m.group(1)
            cur["оновлено"] = int(m.group(2))
            cur["без_даних"] = int(m.group(3))
            cur["помилки"] = int(m.group(4))
            continue
        m = RE_NODATA.match(ln) or RE_OTHER_LINE.match(ln)
        if m:
            kind = "немає даних" if RE_NODATA.match(ln) else "інша лінія"
            for deal, ref, why in RE_ITEM.findall(m.group(2)):
                cur["деталі"].append({"угода": deal, "номер": ref.strip(),
                                      "причина": why.strip(), "вид": kind})
            # «інша лінія» перелічується без дужок з причиною
            if not RE_ITEM.search(m.group(2)):
                for part in m.group(2).split(","):
                    p = part.strip()
                    if p.startswith("угода "):
                        num, _, ref = p[6:].partition("/")
                        cur["деталі"].append({"угода": num.strip(), "номер": ref.strip(),
                                              "причина": "контейнер іншої лінії",
                                              "вид": kind})
    runs = [r for r in runs if r.get("оновлено") is not None]
    return runs[-limit:][::-1]            # найсвіжіші згори


def main():
    runs = DEFAULT_RUNS
    if "--runs" in sys.argv:
        runs = int(sys.argv[sys.argv.index("--runs") + 1])
    out = (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
           else os.path.join(computed_dir(), "automation.json"))

    data = {"джерело": LOG, "прогонів": 0, "runs": []}
    data["runs"] = parse(LOG, runs)
    data["прогонів"] = len(data["runs"])

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print("записано: %s (прогонів: %d)" % (out, data["прогонів"]))
    for r in data["runs"][:3]:
        print("   %s  угод %s · оновлено %s · без даних %s · помилки %s · деталей %d"
              % (r.get("завершився") or r["почався"], r["угод"], r["оновлено"],
                 r["без_даних"], r["помилки"], len(r["деталі"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
