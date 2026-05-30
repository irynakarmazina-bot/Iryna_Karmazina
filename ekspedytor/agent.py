"""
Computer vision agent for Ekspeditor — batch income invoice processing.
Uses regular Claude vision (images in messages) instead of Computer Use API.
Claude analyzes each screenshot and returns a single structured action.
"""
import base64
import json
import os
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .session import RDPSession

load_dotenv()

_NOMENCLATURE_FILE = Path(__file__).parent / "nomenclature.json"
_nomenclature_raw = json.loads(_NOMENCLATURE_FILE.read_text(encoding="utf-8"))
NOMENCLATURE_MAPPINGS = _nomenclature_raw["mappings"]


def _mapping_table() -> str:
    lines = []
    for m in NOMENCLATURE_MAPPINGS:
        keywords = " / ".join(m["match"][:3])
        lines.append(f'  - «{keywords}...» → «{m["ekspedytor"]}»')
    return "\n".join(lines)


AGENT_SYSTEM = f"""Ти — агент управління Windows комп'ютером через скріншоти.
Екран: 1920x1080 пікселів. Ти отримуєш скріншот + задачу + лог дій.
Твоя відповідь — ТІЛЬКИ ОДИН рядок, без пояснень.

ФОРМАТ ВІДПОВІДІ:
ACTION: left_click X Y          — лівий клік (X,Y — центр елемента)
ACTION: double_click X Y        — подвійний клік
ACTION: right_click X Y         — правий клік
ACTION: type ТЕКСТ              — ввести текст (все після «type » — текст)
ACTION: key KEYNAME             — клавіша: Return, Escape, Tab, Delete, BackSpace,
                                   ctrl+v, ctrl+a, ctrl+z, alt+F4, F5
ACTION: scroll X Y down N       — прокрутка вниз N разів
ACTION: scroll X Y up N         — прокрутка вгору N разів
DONE: повідомлення              — задача повністю виконана
ERROR: причина                  — неможливо продовжити

═══ ПРАВИЛА БЕЗПЕКИ ═══
- Відкривай ТІЛЬКИ угоду по знайденому контейнеру
- НЕ видаляй і НЕ переміщуй нічого крім: перемісти оброблений PDF у підпапку «Готово»
- НЕ редагуй існуючі рахунки
- Перевіряй дублі перед створенням

═══ НАВІГАЦІЯ В ЕКСПЕДИТОРІ ═══
- Головний екран → клікни «Угоди» в лівому нижньому блоці «Журнали та обробки»
- Список угод: поле «Контейнер» (вгорі праворуч, мітка «містить») → введи номер → Enter
- Відкрити угоду: подвійний клік по рядку
- Вкладки угоди: Загальна інформація | Рахунки | Файли | ...
- Вкладка «Рахунки»: верхня таблиця = доходні, нижня = витратні
- Перевірка дублів: подивись чи є вже рядки у верхній таблиці
- Додати доходний рахунок: «+» зліва від ВЕРХНЬОЇ таблиці
- Форма рахунку: заповни рядки послуг і суми з PDF → «Записати» → «ОК»

═══ ЯК ЧИТАТИ PDF ═══
- Шукай рядок «Контейнер:» — після нього номер (4 літери + 7 цифр, напр. MRKU2048060)
- Таблиця «Товари (роботи, послуги)» — кожен рядок: опис послуги + сума
- Рядок «Всього:» — загальна сума для перевірки
- «Рахунок на оплату № X від дата» — номер рахунку (→ поле «Номер О»)

═══ ТАБЛИЦЯ ВІДПОВІДНОСТІ НОМЕНКЛАТУРИ ═══
{_mapping_table()}
  - якщо немає відповідності → залиш поле «Стаття» порожнім, введи правильну суму

═══ ФОРМАТ ЗВІТУ (у DONE) ═══
ОБРОБЛЕНО: N файлів
УСПІШНО: назва.pdf → угода №XXXXX, рахунок на [сума] UAH
ДУБЛІ: назва.pdf (вже існує)
ПОМИЛКИ: назва.pdf → причина
"""


class EkspedytorAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.session = RDPSession(
            host=os.getenv("RDP_HOST", "unitex.rdport.net:31230"),
            user=os.getenv("RDP_USER", "karmazina.i"),
            password=os.environ["RDP_PASSWORD"],
        )

    def process_folder(self, folder_name: str) -> str:
        try:
            self.session.start()
            return self._agent_loop(folder_name)
        except Exception as e:
            return f"ПОМИЛКА: {e}"
        finally:
            self.session.stop()

    def _screenshot_b64(self) -> str:
        return base64.standard_b64encode(self.session.screenshot()).decode()

    def _agent_loop(self, folder_name: str) -> str:
        task = (
            f"Обробити всі PDF рахунки у папці «{folder_name}» на Робочому столі.\n"
            "1. Відкрий папку → для кожного PDF: відкрий, прочитай контейнер і суми, закрий\n"
            "2. Знайди угоду в Експедиторі → перевір дублі → створи доходний рахунок\n"
            "3. Перемісти PDF у підпапку «Готово» → перейди до наступного\n"
            "4. Після всіх файлів → DONE з повним звітом"
        )
        action_log = []

        for step in range(200):
            screenshot = self._screenshot_b64()
            recent = "\n".join(action_log[-20:]) or "Початок роботи."

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f"ЗАДАЧА: {task}\n\n"
                                f"ВИКОНАНІ ДІЇ ({len(action_log)} кроків):\n{recent}\n\n"
                                "Що зараз на екрані? Яка наступна дія?\n"
                                "Відповідай ТІЛЬКИ одним рядком: ACTION: або DONE: або ERROR:"
                            ),
                        },
                    ],
                }
            ]

            response = self.client.messages.create(
                model="claude-opus-4-8",
                max_tokens=256,
                system=AGENT_SYSTEM,
                messages=messages,
            )

            text = next(
                (b.text.strip() for b in response.content if hasattr(b, "text")), ""
            )

            if text.startswith("DONE:"):
                return text[5:].strip()
            if text.startswith("ERROR:"):
                return f"ПОМИЛКА: {text[6:].strip()}"

            if text.startswith("ACTION:"):
                action_str = text[7:].strip()
                action_log.append(f"[{step}] {action_str}")
                self._execute(action_str)
                time.sleep(1.2)
            else:
                # Unexpected response — log and continue
                action_log.append(f"[{step}] (відповідь без дії) {text[:80]}")

        return "ПОМИЛКА: досягнуто ліміт 200 кроків"

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
                self.session.scroll(
                    int(parts[1]), int(parts[2]), parts[3], int(parts[4])
                )
        except (ValueError, IndexError):
            pass
