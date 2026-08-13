#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кабінет на 127.0.0.1:8899 з підробленими угодами — для перевірки в браузері.

Живої бази не торкається: угоди задані тут у коді, сховище документів
підмінене. Потрібен для scripts/cabinet_browser.mjs.
Порт міняється через CABINET_DEMO_PORT.
"""
import importlib.util
import os
import tempfile
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CABINET = os.path.join(HERE, os.pardir, "server", "cabinet.py")
TMP = os.environ.get("CABINET_TMP") or tempfile.mkdtemp(prefix="cabdemo-")
os.environ["CABINET_DB"] = os.path.join(TMP, "b.db")
os.environ["CABINET_SECRET"] = os.path.join(TMP, "b.secret")
os.environ["CABINET_LOG"] = os.path.join(TMP, "b.log")
os.environ["CABINET_INSECURE"] = "1"
for f in ("b.db", "b.secret", "b.log", "b.db-wal", "b.db-shm"):
    p = os.path.join(TMP, f)
    if os.path.exists(p):
        os.remove(p)

spec = importlib.util.spec_from_file_location("cabinet", CABINET)
CAB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CAB)

ROWS = [
    {"Угода": "201", "Клієнт": "Мірандор", "Статус": "В морі", "Напрямок": "Імпорт",
     "Вид перевезення": "Море", "Тип": "Фрахт+ТЕО", "FCL/LCL": "FCL",
     "Маршрут": "Shanghai - Gdansk - Одеса", "Лінія": "Maersk", "BL": "274014640",
     "HBL": "UNX-2026-201", "Контейнер": "MRKU1111111", "Судно": "MAERSK ATHABASCA",
     "Вояж": "512W", "Гейт ін": "2026-06-20", "ETD (факт)": "2026-06-25",
     "ETA": "2026-08-20", "ETA порт (план)": "2026-08-20", "Вантаж": "Меблі",
     "Кількість": "1x40'HC", "Коментар клієнту": "Судно в дорозі, затримок немає",
     "Порт перевалки": "Tanjung Pelepas", "Перевалка (прибуття)": "2026-07-18",
     "Перевалка (відправлення)": "2026-07-21",
     "Файли": [{"title": "[Лінійний коносамент] bl-201.pdf",
                "path": "download/noco/a/bl-201.pdf", "mimetype": "application/pdf"},
               {"title": "[Рахунок] inv-201.pdf", "path": "download/noco/a/inv-201.pdf"},
               {"title": "[Внутрішній] margin.xlsx", "path": "download/noco/a/margin.xlsx"}]},
    {"Угода": "202", "Клієнт": "Мірандор", "Статус": "Вантаж доставлено",
     "Напрямок": "Імпорт", "Вид перевезення": "Авіа", "Маршрут": "Bangkok - Kyiv",
     "ETD (факт)": "2026-05-20", "ETA": "2026-05-28",
     "Планова до клієнта (факт)": "2026-06-01", "Вантаж": "Електроніка",
     "Кількість": "220 кг", "Коментар клієнту": "Доставлено, документи в кабінеті",
     "Файли": [{"title": "[ЦМР] cmr-202.pdf", "path": "download/noco/a/cmr-202.pdf"}]},
    {"Угода": "203", "Клієнт": "Мірандор", "Статус": "Завантажений на авто",
     "Напрямок": "Експорт", "Вид перевезення": "Авто", "Маршрут": "Одеса - Gdansk",
     "ETA": "2026-08-16", "Вантаж": "Соняшникова олія", "Кількість": "20 т",
     "Файли": []},
    {"Угода": "999", "Клієнт": "Чужа Фірма", "Статус": "В морі",
     "Маршрут": "СЕКРЕТ - СЕКРЕТ", "Вантаж": "ЧУЖИЙ ВАНТАЖ", "Файли": []},
]
CAB.BP.nc_all = lambda: ROWS


class FakeResp:
    headers = {"Content-Type": "application/pdf"}

    def __init__(self, url):
        self.url = url

    def read(self):
        return b"%PDF-1.4 fake " + self.url.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


CAB.urllib.request.urlopen = lambda req, timeout=0: FakeResp(req.full_url)
CAB.TOKEN_FILE = os.path.join(TMP, "b.token")
open(CAB.TOKEN_FILE, "w").write("faketoken")

# Журнал трекінгу теж підроблений — щоб позначку «оновлено» було видно в макеті.
import datetime as _dt
_lg = os.path.join(TMP, "maersk.log")
open(_lg, "w").write(_dt.datetime.now().replace(hour=7, minute=22, second=46)
                     .strftime("%Y-%m-%d %H:%M:%S") + " Оновити угод: 25; без даних: 2; помилки: 0\n")
CAB.TRACK_LOG = _lg

CAB.init_db()
con = CAB.db()
con.execute("DELETE FROM accounts")
con.execute("INSERT INTO accounts(email,client,name,pwd,active,must_change,created) "
            "VALUES(?,?,?,?,1,1,?)",
            ("new@m.ua", "Мірандор", "Новий", CAB.hash_pwd("temp-pass-1"), CAB.now()))
con.execute("INSERT INTO accounts(email,client,name,pwd,active,must_change,created) "
            "VALUES(?,?,?,?,1,0,?)",
            ("ivan@m.ua", "Мірандор", "Іван", CAB.hash_pwd("робочий-пароль-1"), CAB.now()))
con.commit()
con.close()
print("READY", flush=True)
ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("CABINET_DEMO_PORT", "8899"))), CAB.Handler).serve_forever()
