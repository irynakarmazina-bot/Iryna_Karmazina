#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Журнал дій конвеєра фінзвіту.

НАВІЩО
    До 11.08.2026 конвеєр не лишав сліду. Коли `cash_moves.csv` перестав оновлюватись,
    а довідник контрагентів приходив обрізаним, ніде не було запису про те, що саме
    відпрацювало, скільки записів прийшло і чи були помилки. Дізналися випадково.

ЩО ПИШЕТЬСЯ
    Один рядок JSON на подію у `logs/actions.jsonl`:
        ts     — час
        step   — що робили («Рухи грошей з API», «Інгест з API», …)
        status — start / ok / fail / warn
        detail — довільні числа й тексти: скільки записів, які файли, текст помилки

    Формат JSONL, а не таблиця, бо набір полів у кроків різний, а дописувати
    в кінець файлу можна безпечно з кількох процесів.

ЯК ДИВИТИСЬ
    python3 engine/journal.py            # останні 30 подій
    python3 engine/journal.py --tail 100
    python3 engine/journal.py --fail     # тільки помилки й попередження

НІЧОГО НЕ ВИДАЛЯЄ І НЕ ПЕРЕЗАПИСУЄ — тільки дописує в кінець.
"""
import argparse
import datetime
import json
import os

BASE = os.environ.get("FINREP_ROOT", "/root/unitex-finrep")
PATH = os.path.join(BASE, "logs", "actions.jsonl")
# Зведення для платформи. Лежить у computed/ і віддається тим самим захищеним
# шляхом /finrep-data?name=pipeline, що й фінансові дані, — там перевірка ролі
# (Адміністратор / Фінансист / Бухгалтер) уже працює, нових дірок не з'являється.
SUMMARY = os.path.join(BASE, "computed", "pipeline.json")
SUMMARY_LIMIT = 200


def record(step, status="ok", **detail):
    """Дописати подію. Ніколи не кидає виняток — журнал не має ламати розрахунок."""
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        row = {"ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "step": step, "status": status}
        row.update({k: v for k, v in detail.items() if v is not None})
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        _write_summary()
    except Exception:  # noqa: BLE001, S110
        pass


def _write_summary():
    """Перезбирає computed/pipeline.json після кожного запису.

    Робимо це тут, а не окремим кроком конвеєра: інакше зведення відставало б
    рівно на ті події, заради яких воно й потрібне — на помилки, що трапились
    під час прогону.
    """
    try:
        rows = read(SUMMARY_LIMIT)
        data = {
            "оновлено": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "подій": len(rows),
            "проблем": sum(1 for r in rows if r.get("status") in ("fail", "warn")),
            "події": rows[::-1],           # найсвіжіші згори
        }
        os.makedirs(os.path.dirname(SUMMARY), exist_ok=True)
        tmp = SUMMARY + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SUMMARY)
    except Exception:  # noqa: BLE001, S110
        pass


def read(limit=30, only_bad=False):
    if not os.path.exists(PATH):
        return []
    out = []
    with open(PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if only_bad and row.get("status") not in ("fail", "warn"):
                continue
            out.append(row)
    return out[-limit:]


MARK = {"ok": "✓", "fail": "✗", "warn": "!", "start": "·"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", type=int, default=30)
    ap.add_argument("--fail", action="store_true", help="тільки помилки й попередження")
    ap.add_argument("--summary", action="store_true", help="перезібрати computed/pipeline.json")
    a = ap.parse_args()
    if a.summary:
        _write_summary()
        print("зведення для платформи: %s" % SUMMARY)
        return
    rows = read(a.tail, a.fail)
    if not rows:
        print("Журнал порожній: %s" % PATH)
        return
    for r in rows:
        extra = {k: v for k, v in r.items() if k not in ("ts", "step", "status")}
        tail = "  " + json.dumps(extra, ensure_ascii=False) if extra else ""
        print("%s %s %-34s%s" % (r["ts"], MARK.get(r["status"], "?"), r["step"][:34], tail))


if __name__ == "__main__":
    main()
