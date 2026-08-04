#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Замок «один запуск за раз».

Навіщо (аудит 02.08.2026): жодна синхронізація не мала захисту від паралельного
запуску. А запустити її можна ТРЬОМА способами одночасно — таймер systemd о 07:00,
кнопка «⟳ Оновити з Експедитора» на платформі і ручний запуск через реле.
Два процеси, що читають Експедитор і пишуть у NocoDB одночасно, створюють ту саму
нову угоду ДВІЧІ; далі оновлюється лише перший рядок, а другий назавжди застигає
зі старими даними — і про це ніхто не дізнається.

Замок беремо через flock: ядро саме зніме його, якщо процес уб'ють або він упаде,
тому «залиплих» замків після падіння не буває (на відміну від файла-прапорця).

Використання:

    from runlock import single_run
    with single_run("expeditor"):
        ...  # тіло скрипта

Якщо замок зайнятий — скрипт чесно каже про це і завершується кодом 0:
це НЕ помилка, це «вже виконується», і сигналізувати збоєм не треба.
"""
import fcntl
import os
import sys
import time
from contextlib import contextmanager

LOCK_DIR = os.environ.get("RUNLOCK_DIR", "/var/lock")


class AlreadyRunning(SystemExit):
    pass


@contextmanager
def single_run(name, wait=0, quiet=False):
    """name — коротке ім'я процесу; wait — скільки секунд чекати на звільнення."""
    path = os.path.join(LOCK_DIR, "unitex-%s.lock" % name)
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
    except Exception:
        pass
    fh = open(path, "w")
    deadline = time.time() + max(0, wait)
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.time() >= deadline:
                fh.close()
                if not quiet:
                    # ALREADY_RUNNING — мітка для того, хто нас запустив
                    # (deals_trigger.py): «це не помилка, просто зайнято».
                    # Без мітки тригер бачив лише «скрипт нічого не сказав» і
                    # показував користувачці помилку там, де її не було.
                    print("ALREADY_RUNNING %s" % name, file=sys.stderr)
                    print("ВЖЕ ВИКОНУЄТЬСЯ: інший запуск «%s» ще працює (%s). "
                          "Цей запуск пропускаю — це не помилка." % (name, path),
                          file=sys.stderr)
                raise AlreadyRunning(0)
            time.sleep(1)
    try:
        fh.write("%d\n" % os.getpid())
        fh.flush()
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()
