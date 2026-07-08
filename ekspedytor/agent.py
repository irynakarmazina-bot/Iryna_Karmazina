"""
Комп'ютерний агент для Експедитора — рознесення витратних рахунків Маерска.

Джерело даних — Excel-таблиця (див. invoices.py), НЕ PDF.
Для кожного рядка: знайти угоду за BL → вкладка «Рахунки» → перевірити дубль
(номер рахунку в коментарі витратного) → створити витратний рахунок і заповнити
постачальника / суму / валюту / коментар. Статтю НЕ чіпаємо (проставляється вручну).

Режими (mode):
  dry-run  — тільки знайти угоду й прочитати наявні витратні; НІЧОГО не створює
  create   — реально створює витратний рахунок

Claude бачить скріншоти (через API) і повертає ОДНУ дію за крок.
Прогрес пишеться у JSON-файл (progress_path), щоб його можна було читати ззовні.
"""
import base64
import json
import os
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .debug import upload_debug
from .invoices import read_invoices
from .session import RDPSession

load_dotenv()

SUPPLIER = "Maersk A/S"          # постачальник для демереджних рахунків Маерска
MAX_STEPS_PER_INVOICE = 60       # запобіжник від зациклення на одному рахунку


def _action_protocol() -> str:
    return """ФОРМАТ ВІДПОВІДІ — ТІЛЬКИ ОДИН РЯДОК, без пояснень:
ACTION: left_click X Y          — лівий клік (X,Y — центр елемента)
ACTION: double_click X Y        — подвійний клік
ACTION: right_click X Y         — правий клік
ACTION: type ТЕКСТ              — ввести текст (усе після «type » — текст)
ACTION: key KEYNAME             — клавіша: Return, Escape, Tab, Delete, BackSpace, ctrl+a, ctrl+v, F5
ACTION: scroll X Y down N       — прокрутка вниз N разів (або up)
ACTION: wait N                  — зачекати N секунд (для повільного завантаження 1С)
DONE: <статус> | <деталі>       — задача по ЦЬОМУ рахунку завершена
ERROR: <причина>                — неможливо продовжити (опиши, що на екрані)"""


def system_prompt(mode: str) -> str:
    create_block = (
        "═══ РЕЖИМ: СТВОРЕННЯ ═══\n"
        "Якщо дубля НЕМАЄ — створи витратний рахунок:\n"
        "  1. Натисни «+» ЗЛІВА ВІД НИЖНЬОЇ таблиці (витратні)\n"
        "  2. Постачальник → обери зі списку ТОЧНО «Maersk A/S»\n"
        "  3. Сума → введи суму з задачі\n"
        "  4. Валюта → обери валюту з задачі (напр. USD)\n"
        "  5. Коментар → встав номер рахунку Маерска з задачі\n"
        "  6. Статтю НЕ чіпай (лишається порожня)\n"
        "  7. «Записати» → «ОК»\n"
        "  8. DONE: СТВОРЕНО | угода <№>, сума <...> <валюта>\n"
        if mode == "create" else
        "═══ РЕЖИМ: СУХА ПРОГОНКА (нічого не створювати!) ═══\n"
        "НІЧОГО не створюй, не тисни «+», не редагуй. Тільки знайди й прочитай.\n"
        "Коли зайшов у вкладку «Рахунки» й побачив нижню (витратну) таблицю:\n"
        "  - якщо серед витратних Є рядок з цим номером рахунку в коментарі →\n"
        "    DONE: ДУБЛЬ | угода <№>, рахунок вже заведено\n"
        "  - якщо такого рахунку немає →\n"
        "    DONE: ГОТОВО_ДО_СТВОРЕННЯ | угода <№>, витратних рядків: <скільки бачиш>\n"
    )

    return f"""Ти — агент керування Windows-комп'ютером (1С «Експедитор») через скріншоти.
Екран 1920x1080. Отримуєш скріншот + задачу по ОДНОМУ рахунку + лог дій.

{_action_protocol()}

═══ ПРАВИЛА БЕЗПЕКИ ═══
- Працюй ТІЛЬКИ з угодою, знайденою за вказаним BL.
- НЕ видаляй, НЕ переміщуй, НЕ редагуй існуючі рахунки.
- Перед створенням ЗАВЖДИ перевіряй дубль (номер рахунку в коментарях витратних).
- Сумніваєшся, що на екрані — краще ERROR з описом, ніж навмання.

═══ ЗАПУСК 1С (спочатку!) ═══
Після входу ти бачиш РОБОЧИЙ СТІЛ Windows — 1С ЩЕ НЕ ВІДКРИТА.
1. Знайди у ЛІВОМУ ВЕРХНЬОМУ куті ЖОВТУ круглу іконку з символом «∞» і підписом «BAF»
   (приблизно X=37 Y=342) — це і є 1С «Експедитор».
2. Подвійний клік по «BAF».
3. 1С запускається ПОВІЛЬНО (20–60 сек): може бути заставка, порожнє або біле вікно.
   Це НЕ помилка. Роби «ACTION: wait 15» і дивись знову — повторюй, доки не побачиш
   ГОЛОВНЕ ВІКНО 1С (меню зверху, розділи/журнали).
4. Тільки якщо після ~6 разів «wait 15» (≈90 сек) вікна 1С немає — ERROR з описом екрана.
Якщо 1С вже відкрита (видно вікно програми) — нічого не запускай, працюй у ній.

═══ НАВІГАЦІЯ В ЕКСПЕДИТОРІ ═══
- Головний екран → блок «Журнали та обробки» (лівий низ) → «Угоди».
- Список угод: знайди поле фільтра для номера коносамента (BL) → введи BL → Enter.
  (Поле може називатись «BL», «Коносамент», «Bill of lading» або бути у панелі відбору.)
- Відкрити угоду: подвійний клік по знайденому рядку.
- У картці угоди — вкладка «Рахунки». Там ДВІ таблиці:
    ВЕРХНЯ = доходні рахунки, НИЖНЯ = витратні рахунки.
- Нас цікавить ТІЛЬКИ НИЖНЯ (витратна) таблиця.
- Дубль: у нижній таблиці подивись колонку «Коментар» — чи є там номер нашого рахунку.

{create_block}
═══ ЯКЩО УГОДУ ЗА BL НЕ ЗНАЙДЕНО ═══
DONE: НЕ_ЗНАЙДЕНО | угоди за BL немає

Відповідай СТРОГО одним рядком: ACTION: / DONE: / ERROR:"""


class EkspedytorAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.session = RDPSession(
            host=os.getenv("RDP_HOST", "unitex.rdport.net:31230"),
            user=os.getenv("RDP_USER", "karmazina.i"),
            password=os.environ["RDP_PASSWORD"],
        )

    # ── Публічний вхід ────────────────────────────────────────────────────────

    def process_invoices(self, xlsx_path: str, mode: str = "dry-run",
                         limit: int | None = None, only_bl: str | None = None,
                         progress_path: str | None = None) -> str:
        invoices = read_invoices(xlsx_path)
        if only_bl:
            invoices = [i for i in invoices if i["bl"] == only_bl]
        if limit:
            invoices = invoices[:limit]

        if not invoices:
            return "ПОМИЛКА: немає рахунків для обробки (перевір BL/ліміт/файл)"

        progress = {
            "mode": mode, "total": len(invoices), "done": 0,
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "results": [], "finished": False,
        }
        self._write_progress(progress_path, progress)

        try:
            self.session.start()
            for inv in invoices:
                res = self._process_one(inv, mode)
                progress["results"].append(res)
                progress["done"] = len(progress["results"])
                self._write_progress(progress_path, progress)
        except Exception as e:
            progress["error"] = str(e)
        finally:
            self.session.stop()
            progress["finished"] = True
            progress["ended"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._write_progress(progress_path, progress)

        return self._format_report(progress)

    # ── Обробка одного рахунку ────────────────────────────────────────────────

    def _process_one(self, inv: dict, mode: str) -> dict:
        task = (
            f"Рахунок Маерска для рознесення:\n"
            f"  BL (коносамент): {inv['bl']}\n"
            f"  Номер рахунку (у коментар): {inv['invoice_number']}\n"
            f"  Постачальник: {SUPPLIER}\n"
            f"  Сума: {inv['amount']}\n"
            f"  Валюта: {inv['currency']}\n"
            f"Знайди угоду за BL, відкрий вкладку «Рахунки», працюй з НИЖНЬОЮ (витратною) таблицею."
        )
        action_log: list[str] = []
        result_text = "ERROR: не завершено (ліміт кроків)"
        last_raw = b""

        for step in range(MAX_STEPS_PER_INVOICE):
            last_raw = self.session.screenshot()
            screenshot = base64.standard_b64encode(last_raw).decode()
            recent = "\n".join(action_log[-15:]) or "Початок роботи."
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/png", "data": screenshot}},
                    {"type": "text", "text": (
                        f"ЗАДАЧА:\n{task}\n\n"
                        f"ВИКОНАНІ ДІЇ ({len(action_log)}):\n{recent}\n\n"
                        "Що на екрані? Наступна дія — одним рядком.")},
                ],
            }]
            response = self.client.messages.create(
                model="claude-opus-4-8", max_tokens=256,
                system=system_prompt(mode), messages=messages,
            )
            text = next((b.text.strip() for b in response.content
                         if hasattr(b, "text")), "")

            if text.startswith("DONE:"):
                result_text = text[5:].strip()
                break
            if text.startswith("ERROR:"):
                result_text = "ERROR: " + text[6:].strip()
                break
            if text.startswith("ACTION:"):
                action_str = text[7:].strip()
                action_log.append(f"[{step}] {action_str}")
                self._execute(action_str)
                time.sleep(1.2)
            else:
                action_log.append(f"[{step}] (без дії) {text[:80]}")

        # Вивантажити останній екран цього рахунку — щоб бачити, де зупинились
        shot_status = upload_debug(f"bl_{inv['bl']}_last.png", last_raw) if last_raw else "no-shot"

        return {
            "bl": inv["bl"], "invoice_number": inv["invoice_number"],
            "amount": inv["amount"], "currency": inv["currency"],
            "steps": len(action_log), "result": result_text,
            "shot": shot_status,
        }

    # ── Виконання дій на екрані ───────────────────────────────────────────────

    def _execute(self, action_str: str):
        parts = action_str.split(None, 4)
        if not parts:
            return
        verb = parts[0].lower()
        try:
            if verb in ("left_click", "click") and len(parts) >= 3:
                self.session.click(int(parts[1]), int(parts[2]))
            elif verb == "double_click" and len(parts) >= 3:
                self.session.double_click(int(parts[1]), int(parts[2]))
            elif verb == "right_click" and len(parts) >= 3:
                self.session.right_click(int(parts[1]), int(parts[2]))
            elif verb == "type" and len(parts) >= 2:
                self.session.type_text(" ".join(parts[1:]))
            elif verb == "key" and len(parts) >= 2:
                self.session.key(parts[1])
            elif verb == "scroll" and len(parts) >= 5:
                self.session.scroll(int(parts[1]), int(parts[2]), parts[3], int(parts[4]))
            elif verb == "wait" and len(parts) >= 2:
                time.sleep(min(int(parts[1]), 20))  # стеля 20 сек на один крок
        except (ValueError, IndexError):
            pass

    # ── Прогрес і звіт ────────────────────────────────────────────────────────

    @staticmethod
    def _write_progress(path: str | None, progress: dict):
        if not path:
            return
        Path(path).write_text(
            json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _format_report(progress: dict) -> str:
        lines = [f"РЕЖИМ: {progress['mode']} | оброблено {progress['done']}/{progress['total']}"]
        for r in progress["results"]:
            lines.append(f"  BL {r['bl']} (рах. {r['invoice_number']}): "
                         f"{r['result']}  [{r['steps']} кроків]")
        if progress.get("error"):
            lines.append(f"ЗБІЙ СЕСІЇ: {progress['error']}")
        return "\n".join(lines)
