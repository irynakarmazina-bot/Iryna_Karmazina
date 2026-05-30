"""
Computer Use agent for Ekspeditor (1C logistics system).
Uses Anthropic's computer_20241022 tool to navigate the UI as a human would.
"""
import base64
import os
import time

import anthropic
from dotenv import load_dotenv

from .session import RDPSession

load_dotenv()

SYSTEM_PROMPT = """Ти — агент автоматизації в системі Експедитор (1С:Підприємство, конфігурація логістики).

═══ СУВОРІ ПРАВИЛА БЕЗПЕКИ ═══
1. Виконуй ТІЛЬКИ задачу з повідомлення користувача
2. Відкривай ТІЛЬКИ угоду що відповідає пошуковому номеру
3. Переходь ТІЛЬКИ: Список Угод → Знайдена угода → Вкладка "Рахунки"
4. НЕ видаляй жодних записів
5. НЕ копіюй і НЕ переміщуй файли
6. НЕ відкривай інші угоди, папки або розділи крім потрібних
7. НЕ редагуй існуючі рахунки — тільки СТВОРЮЙ нові
8. ПЕРЕД створенням — ОБОВ'ЯЗКОВО перевір дублі. Якщо знайдено → ЗУПИНИСЬ

═══ НАВІГАЦІЯ В ЕКСПЕДИТОРІ ═══
Список угод:
  - Головний екран → "Угоди" в розділі "Журнали та обробки" (лівий нижній блок)
  - Фільтр по КОНТЕЙНЕРУ: поле "Контейнер" з міткою "містить" (правий верхній кут)
  - Фільтр по КОНОСАМЕНТУ: поле "B/L" з міткою "містить" (правий верхній кут)
  - Після вводу номера натисни Enter або кнопку оновлення (кругла стрілка)
  - Відкрити угоду: подвійний клік по рядку

Всередині угоди є вкладки:
  Загальна інформація | Букінг | План/Калькуляція | Дохід/витрати | Рахунки | Витрати | Файли | Коносаменти | Наряди | Доручення | CMR

═══ ДОХОДНИЙ РАХУНОК (тип: income) ═══
1. Відкрий вкладку "Рахунки"
2. ПЕРЕВІР ДУБЛІ: у верхній таблиці перегляди колонку "Документ" і дати — чи є вже рахунок?
3. Якщо дублю немає → натисни "+" (зелений плюс) зліва від ВЕРХНЬОЇ таблиці
4. Форма відкриється з автоматично заповненими даними з плану/калькуляції
5. Перевір що дані коректні (послуги, суми, платник)
6. Натисни "Записати" → "ОК"

═══ ВИТРАТНИЙ РАХУНОК (тип: expense) ═══
1. Відкрий вкладку "Рахунки"
2. ПЕРЕВІР ДУБЛІ: у нижній таблиці перегляди колонку "Номер рахунку" — чи є вже такий номер?
3. Якщо дублю немає → відкрий PDF файл на робочому столі (подвійний клік)
4. Зчитай з PDF: Контрагент (постачальник), Послуга, Валюта, Номер рахунку, Дата, Сума
5. Закрий PDF (Alt+F4 або кнопка X)
6. Повернись в угоду → вкладка "Рахунки" → "+" зліва від НИЖНЬОЇ таблиці
7. Заповни форму:
   - Контрагент: назва постачальника з PDF
   - Послуга: тип послуги з PDF
   - Валюта: USD або UAH (з PDF)
   - Номер рахунку: номер з PDF (поле праворуч від дати)
   - Дата рахунку постач.: дата з PDF
   - Сума: сума з PDF
8. Натисни "Записати" → "ОК"

═══ ФОРМАТ ВІДПОВІДІ ═══
Успіх:    "ГОТОВО: [тип] рахунок [номер] від [дата] на суму [сума] [валюта] створено в угоді [номер угоди]"
Дубль:    "ДУБЛЬ: рахунок [номер або деталі] вже існує в угоді [номер угоди]"
Не знайдено: "НЕ ЗНАЙДЕНО: угоду по номеру [номер] не знайдено"
Помилка:  "ПОМИЛКА: [що саме пішло не так]"
"""


class EkspedytorAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.session = RDPSession(
            host=os.getenv("RDP_HOST", "unitex.rdport.net:31230"),
            user=os.getenv("RDP_USER", "karmazina.i"),
            password=os.environ["RDP_PASSWORD"],
        )

    def run(self, search_number: str, invoice_type: str, pdf_filename: str = None) -> str:
        """
        Create an invoice in Ekspeditor.

        Args:
            search_number: Container or Bill of Lading number
            invoice_type: 'income' (доходний) or 'expense' (витратний)
            pdf_filename: PDF filename on the remote server's desktop (for expense)

        Returns:
            Status string starting with ГОТОВО/ДУБЛЬ/НЕ ЗНАЙДЕНО/ПОМИЛКА
        """
        try:
            self.session.start()
            return self._agent_loop(search_number, invoice_type, pdf_filename)
        except Exception as e:
            return f"ПОМИЛКА: {e}"
        finally:
            self.session.stop()

    def _build_task(self, search_number: str, invoice_type: str, pdf_filename: str) -> str:
        type_ua = "доходний" if invoice_type == "income" else "витратний"
        pdf_line = ""
        if invoice_type == "expense":
            pdf_line = (
                f"\nPDF файл на робочому столі: {pdf_filename}"
                if pdf_filename
                else "\nЗнайди відповідний PDF файл на робочому столі."
            )
        return (
            f"Створи {type_ua} рахунок в Експедиторі.\n"
            f"Пошуковий номер: {search_number}{pdf_line}\n\n"
            "Формат номера визнач сам: контейнер (літери+цифри, напр. MSCU1234567) "
            "або коносамент (зазвичай тільки цифри або специфічний формат лінії)."
        )

    def _screenshot_b64(self) -> str:
        return base64.standard_b64encode(self.session.screenshot()).decode()

    def _agent_loop(self, search_number: str, invoice_type: str, pdf_filename: str) -> str:
        task = self._build_task(search_number, invoice_type, pdf_filename)

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

        for _ in range(60):
            response = self.client.messages.create(
                model="claude-opus-4-8",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=[
                    {
                        "type": "computer_20241022",
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
                return "Завдання завершено без результату"

            tool_results = []
            for block in response.content:
                if block.type != "tool_use" or block.name != "computer":
                    continue

                action = block.input.get("action")

                if action == "screenshot":
                    img = self._screenshot_b64()
                else:
                    self._execute(action, block.input)
                    time.sleep(1.0)
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

        return "ПОМИЛКА: досягнуто ліміт кроків (60), завдання не завершено"

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
