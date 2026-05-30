"""
Computer Use agent for Ekspeditor — batch income invoice processing.
Reads PDF files from a folder on the remote server's desktop,
extracts container numbers and amounts, creates matching income invoices.
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

# Load nomenclature mapping table
_NOMENCLATURE_FILE = Path(__file__).parent / "nomenclature.json"
_nomenclature_raw = json.loads(_NOMENCLATURE_FILE.read_text(encoding="utf-8"))
NOMENCLATURE_MAPPINGS = _nomenclature_raw["mappings"]

# Build readable table for system prompt
def _mapping_table() -> str:
    lines = []
    for m in NOMENCLATURE_MAPPINGS:
        keywords = " / ".join(m["match"][:3])  # show first 3 keywords
        lines.append(f'  - якщо є «{keywords}...» → «{m["ekspedytor"]}»')
    return "\n".join(lines)


SYSTEM_PROMPT = f"""Ти — агент автоматизації в системі Експедитор (1С:Підприємство, конфігурація логістики).
Ти обробляєш ПАКЕТ офіційних рахунків (PDF) і вносиш їх як доходні рахунки в Експедитор.

═══ СУВОРІ ПРАВИЛА БЕЗПЕКИ ═══
1. Виконуй ТІЛЬКИ задачу з повідомлення користувача
2. Відкривай ТІЛЬКИ угоди що відповідають знайденому контейнеру
3. НЕ видаляй, НЕ переміщуй файли крім: перемістити оброблений PDF у підпапку "Готово"
4. НЕ редагуй існуючі рахунки — тільки СТВОРЮЙ нові
5. ПЕРЕД створенням — ОБОВ'ЯЗКОВО перевір дублі. Якщо знайдено → пропусти цей файл

═══ АЛГОРИТМ ДЛЯ КОЖНОГО PDF ═══

Крок 1 — ВІДКРИТИ PDF:
  - Двічі клікни на PDF файл у папці
  - Дочекайся відкриття PDF-переглядача
  - Зроби скріншоти всіх сторінок (гортай якщо потрібно)

Крок 2 — ПРОЧИТАТИ З PDF:
  Структура документу: "Рахунок на оплату № [N] від [дата]"
  - НОМЕР РАХУНКУ: після знаку "№" (напр. № 74) — запиши в поле "Номер О" при створенні
  - ДАТА: після слова "від" (напр. 20 квітня 2026 р.)
  - КОНТЕЙНЕР: шукай рядок "Контейнер:" або "контейнер:" — значення після двокрапки (4 літери + 7 цифр, напр. MRKU2048060)
    Увага: номер контейнера також зустрічається всередині опису послуг — але шукай окремий рядок "Контейнер:"
  - ПОСЛУГИ: таблиця "Товари (роботи, послуги)" — зчитай кожен рядок: опис і суму в колонці "Сума"
  - ВАЛЮТА: завжди UAH (гривня) — одиниця виміру "грн."
  - ЗАГАЛЬНА СУМА: рядок "Всього:" — для перевірки

  Приклад що шукати:
    "Відшкодування навантажувально-розвантажувальних робіт... контейнер: MRKU2048060" → 15 501,50
    "Відшкодування міжнародного залізничного перевезення..." → 73 078,50
    "Винагорода експедитора на території України" → 2 000,00

Крок 3 — ЗАКРИТИ PDF:
  - Alt+F4 або кнопка X

Крок 4 — ПЕРЕМКНУТИСЯ НА ЕКСПЕДИТОР:
  - Клікни на іконку Експедитора на панелі задач або відкрий через Пуск

Крок 5 — ЗНАЙТИ УГОДУ:
  - Головний екран → "Угоди" (в розділі "Журнали та обробки")
  - Поле "Контейнер" (вгорі праворуч, мітка "містить") → введи номер контейнера → Enter
  - Якщо не знайдено → запиши в журнал помилок, перейди до наступного PDF

Крок 6 — ПЕРЕВІРКА ДУБЛІВ:
  - Подвійний клік по знайденій угоді
  - Вкладка "Рахунки" → верхня таблиця (доходні)
  - Перевір чи є вже рахунок з такою самою датою або сумою
  - Якщо ДУБЛЬ знайдено → запиши в журнал, перейди до наступного PDF

Крок 7 — СТВОРИТИ ДОХОДНИЙ РАХУНОК:
  - Вкладка "Рахунки" → "+" зліва від ВЕРХНЬОЇ таблиці
  - Форма відкриється (можливо з даними з плану — їх ІГНОРУЙ, введи з PDF)
  - Заповни рядки по послугах з PDF, використовуючи ТАБЛИЦЮ ВІДПОВІДНОСТІ нижче
  - Валюта: UAH, суми точно як в PDF
  - Натисни "Записати" → "ОК"

Крок 8 — ПОЗНАЧИТИ PDF ЯК ОБРОБЛЕНИЙ:
  - Поверніись у папку з PDF
  - Перемісти оброблений файл у підпапку "Готово" (створи якщо немає)

═══ ТАБЛИЦЯ ВІДПОВІДНОСТІ НОМЕНКЛАТУРИ ═══
Якщо в PDF зустрічаєш такий текст → використовуй в Експедиторі:
{_mapping_table()}
  - якщо відповідності немає → залиш поле "Стаття" порожнім, але введи правильну суму і продовжуй

═══ СТРУКТУРА ФІНАЛЬНОГО ЗВІТУ ═══
Після обробки ВСІХ файлів надай звіт:
ОБРОБЛЕНО: [N] файлів
УСПІШНО: [список: "назва_файлу.pdf → угода №XXXXX, рахунок на [сума] UAH"]
ДУБЛІ (пропущено): [список файлів]
ПОМИЛКИ: [список: "назва_файлу.pdf → причина"]
СТАТТІ БЕЗ НАЗВИ (порожнє поле): [список: "назва_файлу.pdf → невідомий текст з PDF"]
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
        """
        Process all PDF invoices in the specified folder on the remote desktop.

        Args:
            folder_name: Name of the folder on the remote server's Desktop

        Returns:
            Summary report string
        """
        try:
            self.session.start()
            return self._agent_loop(folder_name)
        except Exception as e:
            return f"ПОМИЛКА: {e}"
        finally:
            self.session.stop()

    def _agent_loop(self, folder_name: str) -> str:
        task = (
            f"Обробити всі PDF рахунки у папці «{folder_name}» на Робочому столі сервера.\n\n"
            "1. Відкрий папку на Робочому столі\n"
            "2. Для кожного PDF файлу виконай алгоритм з інструкцій\n"
            "3. Після всіх файлів надай звіт"
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": self._screenshot_b64(),
                        },
                    },
                    {"type": "text", "text": task},
                ],
            }
        ]

        # Batch processing needs more steps (many PDFs × many actions each)
        for _ in range(200):
            response = self.client.beta.messages.create(
                model="claude-opus-4-8",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                betas=["computer-use-2025-01-24"],
                tools=[
                    {
                        "type": "computer_20250124",
                        "name": "computer",
                        "display_width_px": 1920,
                        "display_height_px": 1080,
                        "display_number": 99,
                    }
                ],
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return "Завдання завершено"

            tool_results = []
            for block in response.content:
                if block.type != "tool_use" or block.name != "computer":
                    continue

                action = block.input.get("action")
                if action == "screenshot":
                    img = self._screenshot_b64()
                else:
                    self._execute(action, block.input)
                    time.sleep(1.2)
                    img = self._screenshot_b64()

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img,
                                },
                            }
                        ],
                    }
                )

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

        return "ПОМИЛКА: досягнуто ліміт кроків (200)"

    def _screenshot_b64(self) -> str:
        return base64.standard_b64encode(self.session.screenshot()).decode()

    def _execute(self, action: str, params: dict):
        coord = params.get("coordinate", [0, 0])
        if action == "left_click":
            self.session.click(coord[0], coord[1])
        elif action == "double_click":
            self.session.double_click(coord[0], coord[1])
        elif action == "right_click":
            self.session.right_click(coord[0], coord[1])
        elif action == "left_click_drag":
            sc = params.get("start_coordinate", [0, 0])
            self.session.drag(sc[0], sc[1], coord[0], coord[1])
        elif action == "type":
            self.session.type_text(params.get("text", ""))
        elif action == "key":
            self.session.key(params.get("key", ""))
        elif action == "scroll":
            self.session.scroll(
                coord[0], coord[1],
                params.get("direction", "down"),
                params.get("amount", 3),
            )
        elif action == "mouse_move":
            pass
