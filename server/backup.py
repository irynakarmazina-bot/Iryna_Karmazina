#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Щоденна резервна копія платформи «Юнітекс OS».

НАВІЩО (08.08.2026): резервних копій бази НЕ ІСНУВАЛО ВЗАГАЛІ. Уся ЕРП —
це один файл /root/nocodb-data/noco.db на ~10 МБ: 277 угод, клієнти,
калькуляції, журнал дій. Жодної копії ніде. Один помилковий скрипт міграції,
одне зайве видалення або збій диска — і відновлювати нема з чого.
Вимога користувачки від 07.2026 (MEMORY.md): «резервні копії ОБОВ'ЯЗКОВО
поза основним VPS (інший сервер)».

ЯК РОБИТЬСЯ КОПІЯ БАЗИ — це головне місце скрипта.
Звичайне `cp noco.db` НЕ ГОДИТЬСЯ: NocoDB пише в базу постійно, і копіювання
може зловити половину транзакції — файл буде побитий, а дізнаєшся про це
тільки тоді, коли він знадобиться. Тому використовується вбудований механізм
SQLite `Connection.backup()` — «гаряча» копія: SQLite сам стежить за
узгодженістю і віддає зліпок, який гарантовано відкривається.
Після копіювання копія ще й перевіряється (`PRAGMA integrity_check`).
Якщо перевірка не сказала «ok» — копія НЕ зараховується, скрипт падає.

ЩО ВСЕРЕДИНІ АРХІВУ:
  * noco.db          — сама база (найважливіше)
  * вкладення        — файли, прикріплені до угод, ЯКЩО вони вже з'явились
  * конфігурація     — Caddyfile, юніти systemd, тригери й authcheck.py,
                       тобто те, чого НЕМАЄ в git і що доведеться відновлювати руками

ЩО НЕ ВСЕРЕДИНІ (свідомо):
  * www/            — фасад лежить у git і має власні бекапи deploy_ui.sh
  * unitex-finrep/  — окремий репозиторій; якщо треба — додати в PATHS нижче

ШИФРУВАННЯ: архів шифрується gpg із паролем із /root/.backup-pass.
⚠️ КОПІЯ ЦЬОГО ПАРОЛЯ МАЄ ЛЕЖАТИ НЕ НА ЦЬОМУ СЕРВЕРІ. Якщо сервер згорить,
а пароль був лише на ньому — вивантажені назовні копії неможливо розшифрувати,
і вся ця робота марна.

ВИДАЛЕННЯ: скрипт НІЧОГО НЕ ВИДАЛЯЄ. Старі копії накопичуються. При ~3 МБ на
добу це ~1 ГБ на рік при 16 ГБ вільних. Прибирання старих копій — окреме
рішення користувачки (правило 6 у CLAUDE.md: жодних видалень без дозволу).

ЗАПУСК:  python3 /root/Iryna_Karmazina/server/backup.py
         --dry-run  — показати, що робив би, нічого не створюючи
"""
import datetime
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile

DB = "/root/nocodb-data/noco.db"
ATTACH_DIRS = ["/root/nocodb-data/nc"]      # тека вкладень NocoDB; з'явиться з першим файлом
OUT_DIR = "/root/backups"
LOG = "/root/backup_log.tsv"
PASS_FILE = "/root/.backup-pass"

# Файли поза git, які доведеться відновлювати руками, якщо їх втратити.
PATHS = [
    "/root/Caddyfile",
    "/root/authcheck.py",
    "/root/deals_trigger.py",
    "/root/cash_trigger.py",
    "/root/unitex-finrep/trigger.py",
    "/etc/systemd/system/deals-sync-trigger.service",
    "/etc/systemd/system/finrep-trigger.service",
    "/etc/systemd/system/cashtrigger.service",
    "/etc/systemd/system/maersk-track-sync.service",
    "/etc/systemd/system/maersk-track-sync.timer",
    "/etc/systemd/system/cosco-track-sync.service",
    "/etc/systemd/system/cosco-track-sync.timer",
    "/etc/ssh/sshd_config.d/00-hardening.conf",
]

DRY = "--dry-run" in sys.argv


def log(msg):
    print(msg, flush=True)


def hot_copy(src, dst):
    """Узгоджена копія бази, поки NocoDB у неї пише.

    `Connection.backup()` — вбудований механізм SQLite саме для цього.
    Повертає розмір копії в байтах.
    """
    src_con = sqlite3.connect("file:%s?mode=ro" % src, uri=True, timeout=30)
    try:
        dst_con = sqlite3.connect(dst)
        try:
            src_con.backup(dst_con)
        finally:
            dst_con.close()
    finally:
        src_con.close()
    return os.path.getsize(dst)


def integrity_ok(path):
    """Перевірка, що копія справді ціла. Без неї бекап — це віра, а не факт."""
    con = sqlite3.connect(path)
    try:
        res = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    return res == "ok", res


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_passphrase():
    """Пароль шифрування. Створюється один раз і більше не змінюється."""
    if os.path.exists(PASS_FILE):
        return open(PASS_FILE).read().strip()
    import secrets
    p = secrets.token_urlsafe(32)
    if DRY:
        log("   [dry-run] створив би %s" % PASS_FILE)
        return p
    with open(PASS_FILE, "w") as f:
        f.write(p + "\n")
    os.chmod(PASS_FILE, 0o600)
    log("   СТВОРЕНО НОВИЙ ПАРОЛЬ ШИФРУВАННЯ: %s (права 600)" % PASS_FILE)
    log("   ⚠️  ЗБЕРЕЖИ ЙОГО КОПІЮ ПОЗА СЕРВЕРОМ — без нього копії не розшифрувати")
    return p


def offsite(path):
    """Вивантаження назовні. Вмикається САМО, щойно з'явиться rclone і remote.

    Доки їх немає — чесно пише, що копія лежить лише на цьому сервері,
    а не мовчить, створюючи враження, що все зроблено.

    ⚠️ Вивантажується ВСЯ тека копій, а не лише свіжий файл (змінено 10.08.2026).
    Причина: якщо одного дня інтернет підвів або Drive відмовив, той файл так і
    лишився б назавжди тільки на сервері — і ніхто б не помітив. rclone пропускає
    те, що вже там є, тож зайвого трафіку немає, а пропущені дні наздоганяються
    самі при наступному прогоні.
    """
    path = OUT_DIR if os.path.isdir(OUT_DIR) else path
    if not shutil.which("rclone"):
        return ["rclone не встановлено — копія ЛИШЕ на цьому сервері"]
    try:
        remotes = subprocess.run(["rclone", "listremotes"], capture_output=True,
                                 text=True, timeout=30).stdout.split()
    except Exception as e:
        return ["rclone не відповів: %s" % str(e)[:80]]
    if not remotes:
        return ["rclone є, але жодного сховища не налаштовано — копія ЛИШЕ тут"]
    out = []
    for r in remotes:
        dest = "%sunitex-backups/" % r
        if DRY:
            out.append("[dry-run] вивантажив би у %s" % dest)
            continue
        try:
            p = subprocess.run(["rclone", "copy", path, dest, "--timeout", "300s"],
                               capture_output=True, text=True, timeout=900)
            out.append(("вивантажено у %s" % dest) if p.returncode == 0
                       else ("ЗБІЙ вивантаження у %s: %s" % (dest, p.stderr[-120:])))
        except Exception as e:
            out.append("ЗБІЙ вивантаження у %s: %s" % (dest, str(e)[:80]))
    return out


def main():
    started = datetime.datetime.now()
    ts = started.strftime("%Y%m%d-%H%M%S")
    log("== резервна копія %s ==" % ts)

    if not os.path.exists(DB):
        log("ПОМИЛКА: немає файла бази %s" % DB)
        return 1
    if not DRY:
        os.makedirs(OUT_DIR, exist_ok=True)

    work = tempfile.mkdtemp(prefix="unitex-bk-")
    try:
        # 1. гаряча копія бази
        snap = os.path.join(work, "noco.db")
        size = hot_copy(DB, snap)
        log("   база скопійована: %.1f МБ" % (size / 1048576.0))

        # 2. перевірка цілості — без неї це не бекап, а сподівання
        ok, res = integrity_ok(snap)
        log("   перевірка цілості: %s" % res)
        if not ok:
            log("ПОМИЛКА: копія бази пошкоджена — бекап НЕ зараховано")
            return 1

        # 3. службові файли поза git
        added = 0
        cfg = os.path.join(work, "config")
        os.makedirs(cfg, exist_ok=True)
        for p in PATHS:
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(cfg, os.path.basename(p)))
                added += 1
        log("   службових файлів додано: %d із %d" % (added, len(PATHS)))

        # 4. вкладення — щойно з'являться, потраплять сюди самі
        att = 0
        for d in ATTACH_DIRS:
            if os.path.isdir(d):
                dst = os.path.join(work, "attachments", os.path.basename(d))
                shutil.copytree(d, dst)
                att += sum(len(f) for _, _, f in os.walk(dst))
        log("   вкладень: %s" % (att if att else "поки немає (з'являться — увійдуть автоматично)"))

        # 5. архів
        tar_path = os.path.join(work, "unitex-%s.tar.gz" % ts)
        with tarfile.open(tar_path, "w:gz") as t:
            t.add(snap, arcname="noco.db")
            t.add(cfg, arcname="config")
            ap = os.path.join(work, "attachments")
            if os.path.isdir(ap):
                t.add(ap, arcname="attachments")
        log("   архів: %.1f МБ" % (os.path.getsize(tar_path) / 1048576.0))

        # 6. шифрування
        passphrase = ensure_passphrase()
        enc = os.path.join(OUT_DIR, "unitex-%s.tar.gz.gpg" % ts)
        if DRY:
            log("   [dry-run] зашифрував би у %s" % enc)
            digest, encsize = "dry-run", 0
        else:
            p = subprocess.run(
                ["gpg", "--batch", "--yes", "--symmetric", "--cipher-algo", "AES256",
                 "--passphrase-fd", "0", "-o", enc, tar_path],
                input=passphrase, capture_output=True, text=True, timeout=600)
            if p.returncode != 0:
                log("ПОМИЛКА шифрування: %s" % p.stderr[-200:])
                return 1
            digest, encsize = sha256(enc), os.path.getsize(enc)
            log("   зашифровано: %s (%.1f МБ)" % (enc, encsize / 1048576.0))

        # 7. назовні
        for line in offsite(enc if not DRY else tar_path):
            log("   %s" % line)

        # 8. журнал
        took = (datetime.datetime.now() - started).total_seconds()
        row = "\t".join([started.isoformat(timespec="seconds"), "OK",
                         str(encsize), digest[:16], "%.1f" % took, os.path.basename(enc)])
        if not DRY:
            with open(LOG, "a") as f:
                f.write(row + "\n")
        log("   журнал: %s" % row)
        log("ГОТОВО за %.1f с" % took)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
