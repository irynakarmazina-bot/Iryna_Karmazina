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

⚠️ ЦЕЙ ФАЙЛ КОПІЮЄТЬСЯ НА СЕРВЕР У КІЛЬКА МІСЦЬ (поруч із кожним тригером):
    /root/authcheck.py              — для /root/cash_trigger.py
    /root/direct-sync/authcheck.py  — для deals_trigger
Оновлюєш тут — копіюй в УСІ місця, інакше правила розійдуться.
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
