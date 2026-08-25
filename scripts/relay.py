#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Виконати команду на сервері через Git Relay — БЕЗПЕЧНО.

Навіщо цей скрипт існує
-----------------------
Реле працює так: записати `cmds/pending.json`, закомітити, запушити; сервер
виконає і покладе відповідь у `cmds/result.json`. Щоб пуш не впав через
розбіжність гілок, раніше кожен такий блок починався з

    git fetch origin main && git reset --hard origin/main

і це двічі за одну сесію (25.08.2026) ЗНИЩИЛО незакомічені правки в
`client_cabinet/build_preview.py`. Перший раз гірше за все: після втрати я
прогнала шлюз, він показав «CABINET_OK» — але вже на коді БЕЗ правки, тобто
перевірка не перевіряла нічого.

Помилка була не в неуважності, а в тому, що небезпечна команда стояла в
шаблоні, яким користуються десятки разів на день. Тому шаблон замінено на цей
скрипт, і він РОБИТЬ НЕМОЖЛИВИМ саме цей випадок:

  • якщо в робочому дереві є незакомічені зміни — скрипт зупиняється і нічого
    не чіпає, а не «прибирає їх з дороги»;
  • історію переписує тільки `--rebase`, який на брудному дереві теж падає;
  • `reset --hard` тут не викликається взагалі.

Запуск
------
    python3 scripts/relay.py "systemctl is-active unitex-cabinet"
    python3 scripts/relay.py --file /шлях/до/скрипта.sh
    python3 scripts/relay.py --timeout 600 "довга команда"

Якщо треба виконати команду, НЕ комітячи наявні правки, — спершу закоміть їх.
Обходу немає навмисно: саме обхід і коштував двох втрат.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PENDING = os.path.join(ROOT, "cmds", "pending.json")


def git(*args, check=True):
    r = subprocess.run(["git", "-C", ROOT] + list(args),
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit("git %s → %s\n%s" % (" ".join(args), r.returncode,
                                              (r.stderr or r.stdout).strip()))
    return r.stdout.strip()


def dirty():
    """Незакомічені зміни, крім самого cmds/ — його пише цей же скрипт."""
    out = git("status", "--porcelain")
    return [ln for ln in out.split("\n")
            if ln.strip() and not ln[3:].startswith("cmds/")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", help="команда для сервера")
    ap.add_argument("--file", help="взяти команду з файла")
    ap.add_argument("--timeout", type=int, default=300, help="скільки чекати, с")
    a = ap.parse_args()

    cmd = open(a.file, encoding="utf-8").read() if a.file else a.cmd
    if not cmd:
        raise SystemExit("немає команди: передай рядком або через --file")

    # ── ЗАМОК. Саме він і є сенсом цього скрипта ──────────────────────────
    bad = dirty()
    if bad:
        print("СТОП: у робочому дереві є незакомічені зміни.\n")
        for ln in bad:
            print("   " + ln)
        print("\nСпершу закоміть їх — інакше синхронізація з origin/main їх зітре.")
        print("Саме так 25.08.2026 двічі зникли правки схеми руху.")
        raise SystemExit(2)

    git("fetch", "origin", "main")
    git("rebase", "origin/main")          # на брудному дереві впаде сам

    ident = uuid.uuid4().hex[:12]
    os.makedirs(os.path.dirname(PENDING), exist_ok=True)
    with open(PENDING, "w", encoding="utf-8") as f:
        json.dump({"id": ident, "cmd": cmd}, f, ensure_ascii=False)

    git("add", "cmds/pending.json")
    git("commit", "-q", "-m", "relay: %s" % cmd.strip().split("\n")[0][:60])
    for attempt in range(4):
        r = subprocess.run(["git", "-C", ROOT, "push", "origin", "HEAD:main"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
        git("fetch", "origin", "main")
        git("rebase", "origin/main")
        time.sleep(2 ** attempt)
    else:
        raise SystemExit("не вдалося запушити команду")

    print("надіслано (%s), чекаю відповідь…" % ident, file=sys.stderr)
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        time.sleep(12)
        git("fetch", "origin", "main")
        raw = subprocess.run(["git", "-C", ROOT, "show", "origin/main:cmds/result.json"],
                             capture_output=True, text=True).stdout
        if not raw.strip():
            continue
        try:
            js = json.loads(raw)
        except ValueError:
            continue
        if js.get("id") != ident:
            continue
        print(js.get("stdout", ""), end="")
        err = (js.get("stderr") or "").strip()
        if err:
            print("\n--- stderr ---\n" + err[-2000:])
        code = js.get("returncode")
        if code:
            print("\nкод виходу: %s" % code)
        return 0 if not code else 1
    print("відповіді немає за %d с — подивись cmds/result.json пізніше" % a.timeout)
    return 3


if __name__ == "__main__":
    sys.exit(main())
