# -*- coding: utf-8 -*-
"""Запис у «Журнал дій» платформи від імені автоматики.

Навіщо: 21.08.2026 користувачка попросила, щоб конфлікт коносаментів
«підсвічувався, а не мовчки», — а серверний журнал вона не читає.
«Журнал дій» видно прямо в платформі, тож автоматика пише туди.

Правила цього модуля:
  * тільки ДОДАЄ записи в журнал — нічого не редагує і не видаляє;
  * будь-яка помилка тут НЕ має валити синк чи трекінг, тому все у try
    і назовні йде лише True/False.
"""
import datetime
import json
import urllib.request

BASE_ID = "pbhr1qkpvx09z8m"          # база платформи в NocoDB
_journal_tid = None                   # кеш: id таблиці «Журнал дій»


def _nc(method, path, body=None):
    tok = open("/root/nocodb-token.txt").read().strip()
    req = urllib.request.Request(
        "http://localhost:8080" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"xc-token": tok, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def note(user, action, obj, field="", before="", after=""):
    """Один запис у «Журнал дій». user — хто діяв (напр. «трекінг Maersk»)."""
    global _journal_tid
    try:
        if _journal_tid is None:
            for t in _nc("GET", "/api/v2/meta/bases/%s/tables" % BASE_ID).get("list", []):
                if t.get("title") == "Журнал дій":
                    _journal_tid = t.get("id")
                    break
        if not _journal_tid:
            return False
        _nc("POST", "/api/v2/tables/%s/records" % _journal_tid, [{
            "Час": datetime.datetime.utcnow().isoformat() + "Z",
            "Користувач": user,
            "Роль": "автоматика",
            "Дія": action,
            # ʼ у назві колонки — саме такий (U+02BC), як у фасаді (logAction)
            "Обʼєкт": str(obj)[:200],
            "Поле": str(field)[:100],
            "Було": str(before)[:500],
            "Стало": str(after)[:500],
        }])
        return True
    except Exception:  # noqa: BLE001 — журнал не має валити основну роботу
        return False
