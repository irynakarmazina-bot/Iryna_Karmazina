#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Спільна перевірка «хто це і чи можна йому» для службових адрес платформи.

НАВІЩО (аудит 02.08.2026, виправлення 03.08.2026):
маршрути /cash-refresh, /cash-sheet, /localcosts-refresh, /sync у Caddy були
зроблені так, що Caddy САМ підставляв службовий токен у запит:

    handle /cash-refresh { rewrite * /refresh?token=<секрет> ; reverse_proxy … }

Тобто перевірявся не користувач, а сам Caddy — і будь-хто, хто знав адресу сайту,
міг запускати перерахунки БЕЗ ВХОДУ в платформу. Токен при цьому нічого не захищав.

Тепер додатково перевіряється сам користувач: його особистий ключ сесії
(заголовок `xc-auth`, той самий, яким фасад ходить у базу) і роль у довіднику
«Користувачі». Логіка навмисно та сама, що вже працює у findata.py і docgen.py.

⚠️ ЦЕЙ ФАЙЛ КОПІЮЄТЬСЯ НА СЕРВЕР. Python шукає модуль у теці САМОГО скрипта,
тому копія має лежати поруч із кожним тригером, який її імпортує:
    /root/authcheck.py — обслуговує ОБИДВА тригери, бо обидва лежать у /root:
        /root/cash_trigger.py   (порт 8791: /refresh, /localcosts)
        /root/deals_trigger.py  (порт 8788: /run, /state)
Оновлюєш тут — копіюй в /root/authcheck.py, інакше правила розійдуться.

Виправлено 08.08.2026: тут раніше було написано «/root/direct-sync/authcheck.py
— для deals_trigger». Це НЕПРАВДА і збивало з пантелику: deals_trigger живе за
адресою /root/deals_trigger.py (див. ExecStart у deals-sync-trigger.service),
теки /root/direct-sync у його шляху пошуку немає взагалі. Перевірено на сервері:
файла /root/direct-sync/authcheck.py не існує, і при цьому перевірка ролі
ПРАЦЮЄ — у /root/authcheck.log є записи і для /run, і для /state.

НЕ ОБСЛУГОВУЄТЬСЯ цим файлом: /root/unitex-finrep/trigger.py (порт 8787,
маршрут /finrep-run). Він лежить в іншій теці, authcheck поруч немає, і ролі
він не перевіряє — його прикриває лише службовий токен, який підставляє Caddy.
"""
import json
import time
import urllib.error
import urllib.request

NC = "http://localhost:8080"
USERS_T = "meqpi0r197bz14n"
TOKEN_FILE = "/root/nocodb-token.txt"

# Ролі так само, як у фасаді (таблиця RC у www/index.html).
# ДВА РІЗНІ СПИСКИ, і це навмисно:
#   FIN_ROLES  — гроші: каса, локальні витрати, вивантаження. Вузьке коло.
#   SYNC_ROLES — оновлення таблиці диспетчеризації з Експедитора. Це робоча
#                дія менеджера, а не фінансова, тому коло ширше.
# 03.08.2026 користувачка: «має бути дозволено і сейлзу і операціоністу —
# оновлення таблиці диспетчеризації». Логіст і Перегляд не входять свідомо:
# у них і в фасаді sync:false.
FIN_ROLES = {"Адміністратор", "Фінансист", "Бухгалтер"}
SYNC_ROLES = {"Адміністратор", "Фінансист", "Бухгалтер",
              "Операційний менеджер", "Сейлз-менеджер"}

_TOK = None
_cache = {}          # ключ сесії -> (роль, коли перевірили)
CACHE_SEC = 60


def _admin_tok():
    global _TOK
    if _TOK is None:
        _TOK = open(TOKEN_FILE).read().strip()
    return _TOK


def get_role(jwt):
    """Роль користувача за його ключем сесії. None — не вдалося визначити.

    «__EXPIRED__» — ключ протух: це не «немає прав», а «увійди знову»,
    і фасад має показати різне.
    """
    if not jwt:
        return None
    hit = _cache.get(jwt)
    if hit and time.time() - hit[1] < CACHE_SEC:
        return hit[0]
    try:
        r = urllib.request.Request(NC + "/api/v1/auth/user/me", headers={"xc-auth": jwt})
        with urllib.request.urlopen(r, timeout=10) as resp:
            email = (json.loads(resp.read().decode()).get("email") or "").lower()
    except urllib.error.HTTPError as e:
        return "__EXPIRED__" if e.code in (401, 403) else None
    except Exception:
        return None
    try:
        r2 = urllib.request.Request(NC + "/api/v2/tables/%s/records?limit=1000" % USERS_T,
                                    headers={"xc-token": _admin_tok()})
        with urllib.request.urlopen(r2, timeout=10) as resp:
            users = json.loads(resp.read().decode()).get("list", [])
    except Exception:
        return None
    row = next((u for u in users
                if str(u.get("Email") or "").lower() == email
                and u.get("Активний") is not False), None)
    role = row.get("Роль") if row else None
    if role is not None:
        _cache[jwt] = (role, time.time())
    return role


# ── РЕЖИМ РОБОТИ ──────────────────────────────────────────────────────────
# ENFORCE = False → «попереджувальний режим» (рішення користувачки 03.08.2026):
#   перевірка виконується і пишеться в журнал, але НІКОГО НЕ БЛОКУЄ.
#   Навіщо: перевірку викотили, не маючи змоги випробувати її під живим
#   користувачем (потрібен був би чужий пароль), і кнопки перестали працювати.
#   Тепер кілька днів дивимось у журнал на РЕАЛЬНИХ запитах, чи проходили б вони.
# ENFORCE = True  → блокує, як і задумано. Перемикати ОДНИМ словом тут,
#   коли в журналі буде видно, що законні запити проходять.
#
# ⚡ УВІМКНЕНО 08.08.2026 — за даними журналу, а не «бо так треба».
# Прогін /root/authcheck.log за час попереджувального режиму (323 записи):
#     249 × ПРОПУЩЕНО    — усі з реальною роллю (Адміністратор тощо)
#      37 × ВІДМОВИВ БИ  — УСІ 37 із «роль=невідома», тобто запити взагалі без
#                          ключа сесії або з протермінованим
# Тобто жодного разу перевірка не відмовила б живій людині з реальною роллю.
# Це саме та відповідь, заради якої попереджувальний режим і вмикали.
# Якщо кнопки раптом почнуть відмовляти — повернути False, це один рядок,
# і подивитись у /root/authcheck.log, кому саме і чому відмовило.
ENFORCE = True
LOG_FILE = "/root/authcheck.log"


def _log(line):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (stamp, line))
    except Exception:
        pass
    print("AUTHCHECK %s" % line, flush=True)


def guard(headers, allowed, what=""):
    """Головна точка входу для тригерів.

    Повертає None — «пропускай далі», або (код, повідомлення) — «відмов».
    У попереджувальному режимі ЗАВЖДИ повертає None, але пише в журнал,
    що сталося б насправді.
    """
    ok, code, msg, role = check(headers, allowed)
    verdict = "ПРОПУЩЕНО" if ok else ("ВІДМОВИВ БИ %d" % code)
    _log("%-14s роль=%-22s %s%s" % (what or "?", role or "невідома", verdict,
                                    "" if ok else " (" + msg[:60] + ")"))
    if ok:
        return None
    if not ENFORCE:
        _log("%-14s ПОПЕРЕДЖУВАЛЬНИЙ РЕЖИМ — запит пропущено попри відмову" % (what or "?"))
        return None
    return code, msg


def check(headers, allowed):
    """Повертає (ok, код, повідомлення, роль).

    allowed — множина дозволених ролей (FIN_ROLES / SYNC_ROLES).
    """
    jwt = headers.get("xc-auth", "") or headers.get("Xc-Auth", "")
    role = get_role(jwt)
    if role == "__EXPIRED__":
        return False, 401, "Сесія завершилась — увійди в платформу знову.", None
    if not jwt or role is None:
        return False, 401, ("Цю дію можна запускати лише з платформи, після входу. "
                            "Онови сторінку і спробуй ще раз."), None
    if role not in allowed:
        return False, 403, ("Твоя роль «%s» не має права запускати цю дію. "
                            "Зверніться до адміністратора." % role), role
    return True, 200, "", role
