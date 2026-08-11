#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Підключення рухів грошей і журналу дій до конвеєра (engine/update_all_api.py).

ЩО РОБИТЬ
    1. Додає крок «Рухи грошей з API» (`cash_moves_from_odata.py`) одразу після
       інгесту з API. До цього рухи не оновлювались узагалі: їх будував лише
       `parse.py`, а `run.sh` кличе `update_all_api.py --skip-parse`.
       Порядок важливий: рухи мають бути готові ДО кроків, які їх читають
       (`pnl_cf.py`, `retro_nwc.py`, `build_dashboard_data.py`).
    2. Дописує в `run()` запис у журнал дій (`logs/actions.jsonl`) на кожен крок:
       початок, успіх із останнім рядком виводу, або помилка з текстом.

БЕЗПЕКА
    Нічого не видаляє. Перед правкою робить копію `update_all_api.py.bak-<дата-час>`.
    `--check` лише показує стан.

ЗАПУСК
    python3 wire_cash_moves.py --check
    python3 wire_cash_moves.py
"""
import argparse
import datetime
import os
import shutil

TARGET = os.environ.get("UPDATE_ALL_API",
                        "/root/unitex-finrep/engine/update_all_api.py")

OLD_STEPS = """STEPS = [
    ("Інгест з API (рахунки/витрати/угоди)", "odata_ingest.py"),
    ("Реєстри AR/AP/WIP",                    "registers.py"),"""

NEW_STEPS = """STEPS = [
    ("Інгест з API (рахунки/витрати/угоди)", "odata_ingest.py"),
    # Рухи грошей. Мають бути ПІСЛЯ інгесту (беруть довідники з тієї самої бази)
    # і ДО кроків, які їх читають: pnl_cf, retro_nwc, build_dashboard_data.
    # Раніше цього кроку не було зовсім: cash_moves.csv будував тільки parse.py,
    # а run.sh кличе update_all_api.py --skip-parse — тож рухи не оновлювались
    # із 23.07.2026 і ніхто про це не знав.
    ("Рухи грошей з API",                    "cash_moves_from_odata.py"),
    ("Реєстри AR/AP/WIP",                    "registers.py"),"""

OLD_RUN = """def run(label, script, args=None):
    print(f"→ {label} ({script}) ...", flush=True)
    cmd = [PY, os.path.join(ENGINE, script)] + (args or [])
    r = subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
    if r.returncode != 0:
        print(f"  ✗ ПОМИЛКА «{label}»:\\n{r.stderr[-2000:]}", file=sys.stderr)
        sys.exit(1)
    tail = (r.stdout or "").strip().splitlines()
    if tail:
        print("   " + tail[-1])"""

NEW_RUN = """def _journal():
    \"\"\"Журнал дій. Якщо модуля немає — працюємо як раніше, без записів.\"\"\"
    try:
        sys.path.insert(0, ENGINE)
        import journal  # noqa: PLC0415
        return journal
    except Exception:  # noqa: BLE001
        class _Null:
            @staticmethod
            def record(*_a, **_kw):
                pass
        return _Null()


def run(label, script, args=None):
    print(f"→ {label} ({script}) ...", flush=True)
    j = _journal()
    j.record(label, "start", скрипт=script)
    cmd = [PY, os.path.join(ENGINE, script)] + (args or [])
    r = subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
    if r.returncode != 0:
        print(f"  ✗ ПОМИЛКА «{label}»:\\n{r.stderr[-2000:]}", file=sys.stderr)
        j.record(label, "fail", скрипт=script, код=r.returncode,
                 помилка=(r.stderr or "").strip()[-500:])
        sys.exit(1)
    tail = (r.stdout or "").strip().splitlines()
    if tail:
        print("   " + tail[-1])
    j.record(label, "ok", скрипт=script, підсумок=tail[-1][:200] if tail else "")"""

MARK = '("Рухи грошей з API",                    "cash_moves_from_odata.py"),'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="лише показати стан")
    a = ap.parse_args()

    if not os.path.exists(TARGET):
        raise SystemExit("НЕ ЗНАЙДЕНО %s" % TARGET)
    src = open(TARGET, encoding="utf-8").read()

    has_step = MARK in src
    has_journal = "_journal()" in src
    if has_step and has_journal:
        print("Вже підключено — %s" % TARGET)
        return
    if a.check:
        print("НЕ підключено — %s" % TARGET)
        print("   крок «Рухи грошей з API»: %s" % ("є" if has_step else "немає"))
        print("   журнал дій у run():      %s" % ("є" if has_journal else "немає"))
        return

    out = src
    if not has_step:
        if OLD_STEPS not in out:
            raise SystemExit("Список STEPS не такий, як очікувалось — правку НЕ застосовано.")
        out = out.replace(OLD_STEPS, NEW_STEPS)
    if not has_journal:
        if OLD_RUN not in out:
            raise SystemExit("Функція run() не така, як очікувалось — правку НЕ застосовано.")
        out = out.replace(OLD_RUN, NEW_RUN)

    bak = TARGET + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M")
    shutil.copy2(TARGET, bak)
    tmp = TARGET + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, TARGET)
    print("Копія попереднього файлу: %s" % bak)
    print("Підключено: %s" % TARGET)


if __name__ == "__main__":
    main()
