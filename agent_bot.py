import asyncio
import io
import os, logging, base64, json, math, re, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

for v in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(v, None)

from dotenv import load_dotenv
import anthropic
import httpx
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

import finance

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

NOTES_DIR = Path(__file__).parent / "notes"
NOTES_DIR.mkdir(exist_ok=True)

HISTORY_FILE = Path(__file__).parent / "chat_history.json"


def load_history() -> dict[int, list[dict]]:
    if HISTORY_FILE.exists():
        try:
            raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return {int(k): v for k, v in raw.items()}
        except Exception:
            log.exception("Не вдалося завантажити chat_history.json")
    return {}


def save_history(h: dict[int, list[dict]]):
    try:
        saveable = {}
        for uid, msgs in h.items():
            clean = []
            for m in msgs:
                if isinstance(m["content"], str):
                    clean.append(m)
                elif isinstance(m["content"], list):
                    # Зберігаємо тільки текстові блоки — пропускаємо великі зображення/PDF
                    text_parts = [
                        p.get("text", "") for p in m["content"]
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    placeholder = " ".join(text_parts) if text_parts else "[медіа]"
                    clean.append({"role": m["role"], "content": placeholder})
                else:
                    # tool_use/tool_result блоки — пропускаємо, вони технічні
                    pass
            if clean:
                saveable[str(uid)] = clean
        HISTORY_FILE.write_text(
            json.dumps(saveable, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        log.exception("Не вдалося зберегти chat_history.json")


history: dict[int, list[dict]] = load_history()

STATS_FILE = Path(__file__).parent / "stats.json"

# Ціни claude-opus-4-7 ($ за 1 млн токенів)
PRICE_INPUT_PER_M = 15.0
PRICE_OUTPUT_PER_M = 75.0


def load_stats() -> dict[int, dict]:
    if STATS_FILE.exists():
        try:
            raw = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            return {int(k): v for k, v in raw.items()}
        except Exception:
            log.exception("Не вдалося завантажити stats.json")
    return {}


def save_stats(s: dict[int, dict]):
    try:
        STATS_FILE.write_text(
            json.dumps({str(k): v for k, v in s.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        log.exception("Не вдалося зберегти stats.json")


def add_usage(uid: int, input_tokens: int, output_tokens: int):
    entry = user_stats.setdefault(uid, {"input_tokens": 0, "output_tokens": 0, "requests": 0})
    entry["input_tokens"] += input_tokens
    entry["output_tokens"] += output_tokens
    entry["requests"] += 1
    save_stats(user_stats)


user_stats: dict[int, dict] = load_stats()

VOICE_FILE = Path(__file__).parent / "voice_prefs.json"


def load_voice_prefs() -> dict[int, bool]:
    if VOICE_FILE.exists():
        try:
            raw = json.loads(VOICE_FILE.read_text(encoding="utf-8"))
            return {int(k): v for k, v in raw.items()}
        except Exception:
            pass
    return {}


def save_voice_prefs(v: dict[int, bool]):
    VOICE_FILE.write_text(
        json.dumps({str(k): val for k, val in v.items()}, ensure_ascii=False),
        encoding="utf-8",
    )


voice_prefs: dict[int, bool] = load_voice_prefs()


def strip_markdown(text: str) -> str:
    # Жирний/курсив: **text** → text, *text* → text, __text__ → text
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}(.*?)_{1,2}', r'\1', text)
    # Заголовки: ## Заголовок → Заголовок
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Маркери списків: - item / * item / • item → item
    text = re.sub(r'^[\-\*•]\s+', '', text, flags=re.MULTILINE)
    # Нумеровані списки: 1. item → item
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    # Inline code: `code` → code
    text = re.sub(r'`{1,3}(.*?)`{1,3}', r'\1', text, flags=re.DOTALL)
    # Посилання: [текст](url) → текст
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Горизонтальні лінії: --- / *** → пауза
    text = re.sub(r'^[-\*]{3,}\s*$', '.', text, flags=re.MULTILINE)
    # Подвійний/потрійний дефіс → пауза
    text = re.sub(r'-{2,}', '.', text)
    # Залишкові символи
    text = re.sub(r'[~>]', '', text)
    return text.strip()


def text_to_ogg(text: str) -> bytes:
    from gtts import gTTS
    clean = strip_markdown(text)
    chunk = clean[:3000]
    tts = gTTS(text=chunk, lang="uk", slow=False)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3f:
        mp3_path = mp3f.name
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as oggf:
        ogg_path = oggf.name
    try:
        tts.save(mp3_path)
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-c:a", "libopus", "-b:a", "32k", ogg_path],
            check=True, capture_output=True,
        )
        return Path(ogg_path).read_bytes()
    finally:
        for p in (mp3_path, ogg_path):
            try: os.unlink(p)
            except: pass

SYSTEM_PROMPT = """Ти — AI бізнес-асистент для підприємців.

Твої сильні сторони:
• Стратегічне мислення — аналіз ідей
• Управління — пріоритети, делегування
• Комунікація — листи, презентації
• Фінанси — unit-економіка, ROI

Будь конкретним, давай цифри та плани.

📒 Фінансовий облік:
Коли користувач згадує дохід або витрату («витратила 500 грн на пальне»,
«отримала 20000 за фрахт») — ОДРАЗУ зберігай через add_transaction.
Категорію підбирай сам: коротка, одним-двома словами (Пальне, Фрахт, Зарплата,
Продукти, Оренда...). Валюта за замовчуванням UAH. Після збереження коротко підтверди.
На питання про фінанси («скільки я витратила на пальне?») відповідай через
finance_summary або list_transactions.
Звіти користувач отримує командами: /report (P&L за місяць), /cashflow (рух грошей),
/dashboard (інтерактивні графіки) — підказуй їх, коли доречно.

Маєш інструменти: calculate, save_note, list_notes, delete_note, get_datetime,
read_url, get_youtube_transcript, add_transaction, delete_transaction,
list_transactions, finance_summary.
Використовуй їх коли це доречно. Відповідай завжди українською."""

TOOLS = [
    {
        "name": "calculate",
        "description": "Виконує математичні розрахунки. Підтримує +, -, *, /, **, sqrt, round тощо.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Математичний вираз, наприклад: '2 + 2 * 10' або 'sqrt(144)'"}
            },
            "required": ["expression"],
        },
    },
    {
        "name": "save_note",
        "description": "Зберігає нотатку для користувача.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "ID користувача"},
                "text": {"type": "string", "description": "Текст нотатки"},
            },
            "required": ["user_id", "text"],
        },
    },
    {
        "name": "list_notes",
        "description": "Повертає список нотаток користувача.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "ID користувача"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "delete_note",
        "description": "Видаляє нотатку за номером.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "ID користувача"},
                "note_id": {"type": "string", "description": "Номер нотатки (починається з 1)"},
            },
            "required": ["user_id", "note_id"],
        },
    },
    {
        "name": "get_datetime",
        "description": "Повертає поточну дату і час українською.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_url",
        "description": "Читає вміст веб-сторінки за URL і повертає текст. НЕ використовуй для YouTube — для відео використовуй get_youtube_transcript.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL сторінки"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "add_transaction",
        "description": "Зберігає фінансову операцію (дохід або витрату) користувача. Викликай одразу, коли користувач згадує що заробив/отримав/витратив гроші.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["income", "expense"], "description": "income — дохід, expense — витрата"},
                "amount": {"type": "number", "description": "Сума (додатне число)"},
                "category": {"type": "string", "description": "Коротка категорія: Пальне, Фрахт, Зарплата, Продукти, Оренда тощо"},
                "description": {"type": "string", "description": "Необов'язковий опис деталей"},
                "currency": {"type": "string", "description": "Код валюти: UAH (за замовчуванням), USD, EUR..."},
                "date": {"type": "string", "description": "Дата у форматі YYYY-MM-DD. Не вказуй — буде сьогодні. Якщо користувач каже «вчора» — порахуй дату через get_datetime"},
            },
            "required": ["type", "amount", "category"],
        },
    },
    {
        "name": "delete_transaction",
        "description": "Видаляє фінансову операцію за її номером (#id зі списку транзакцій).",
        "input_schema": {
            "type": "object",
            "properties": {
                "transaction_id": {"type": "string", "description": "Номер транзакції"},
            },
            "required": ["transaction_id"],
        },
    },
    {
        "name": "list_transactions",
        "description": "Показує список фінансових операцій користувача (останні або за конкретний місяць).",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "Місяць у форматі MM.YYYY, наприклад 06.2026. Не вказуй — покаже останні операції"},
            },
            "required": [],
        },
    },
    {
        "name": "finance_summary",
        "description": "Підсумок фінансів за місяць: доходи, витрати, прибуток, розбивка за категоріями. Використовуй для відповідей на питання про фінанси.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "Місяць у форматі MM.YYYY. Не вказуй — поточний місяць"},
            },
            "required": [],
        },
    },
    {
        "name": "get_youtube_transcript",
        "description": "Отримує субтитри (транскрипт) YouTube-відео. Використовуй завжди, коли бачиш youtube.com або youtu.be посилання.",
        "input_schema": {
            "type": "object",
            "properties": {
                "video_url": {"type": "string", "description": "URL відео YouTube (youtu.be/... або youtube.com/watch?v=...)"},
            },
            "required": ["video_url"],
        },
    },
]


# ── Реалізація інструментів ──────────────────────────────────────────────────

def tool_calculate(expression: str) -> str:
    safe_names = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
    safe_names["abs"] = abs
    safe_names["round"] = round
    expression = re.sub(r"[^\d\s\+\-\*\/\(\)\.\,\%\^a-zA-Z_]", "", expression)
    expression = expression.replace("^", "**").replace(",", ".")
    try:
        result = eval(expression, {"__builtins__": {}}, safe_names)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Помилка розрахунку: {e}"


def _user_notes_dir(user_id: str) -> Path:
    d = NOTES_DIR / str(user_id)
    d.mkdir(exist_ok=True)
    return d


def tool_save_note(user_id: str, text: str) -> str:
    d = _user_notes_dir(user_id)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (d / f"{ts}.txt").write_text(text, encoding="utf-8")
    return f"Нотатку збережено."


def tool_list_notes(user_id: str) -> str:
    d = _user_notes_dir(user_id)
    files = sorted(d.glob("*.txt"))
    if not files:
        return "Нотаток немає."
    lines = []
    for i, f in enumerate(files, 1):
        text = f.read_text(encoding="utf-8").strip()
        ts = datetime.strptime(f.stem, "%Y%m%d_%H%M%S").strftime("%d.%m.%Y %H:%M")
        lines.append(f"{i}. [{ts}] {text}")
    return "\n".join(lines)


def tool_delete_note(user_id: str, note_id: str) -> str:
    d = _user_notes_dir(user_id)
    files = sorted(d.glob("*.txt"))
    try:
        idx = int(note_id) - 1
        if idx < 0 or idx >= len(files):
            return "Нотатку не знайдено."
        files[idx].unlink()
        return f"Нотатку #{note_id} видалено."
    except ValueError:
        return "Вкажи номер нотатки цифрою."


def tool_get_datetime() -> str:
    MONTHS = ["січня","лютого","березня","квітня","травня","червня",
              "липня","серпня","вересня","жовтня","листопада","грудня"]
    DAYS = ["понеділок","вівторок","середа","четвер","п'ятниця","субота","неділя"]
    now = datetime.now()
    return (f"{DAYS[now.weekday()]}, {now.day} {MONTHS[now.month-1]} {now.year} р., "
            f"{now.strftime('%H:%M')}")


def tool_read_url(url: str) -> str:
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l for l in text.splitlines() if l.strip()]
        return "\n".join(lines[:200])
    except Exception as e:
        return f"Помилка читання URL: {e}"


def tool_get_youtube_transcript(video_url: str) -> str:
    m = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([\w-]+)', video_url)
    video_id = m.group(1) if m else video_url.strip()
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        fetcher = YouTubeTranscriptApi()
        try:
            transcript_obj = fetcher.fetch(video_id, languages=['uk', 'ru', 'en'])
        except Exception:
            listing = fetcher.list(video_id)
            first = next(iter(listing))
            transcript_obj = first.fetch()
        full_text = ' '.join(item.text for item in transcript_obj)
        if len(full_text) > 15000:
            full_text = full_text[:15000] + "\n\n[...транскрипт скорочено до 15 000 символів...]"
        return full_text if full_text else "Транскрипт порожній."
    except Exception as e:
        return f"Не вдалося отримати транскрипт: {e}"


def execute_tool(name: str, inputs: dict, uid: int) -> str:
    if name == "calculate":
        return tool_calculate(inputs["expression"])
    elif name == "save_note":
        return tool_save_note(str(uid), inputs["text"])
    elif name == "list_notes":
        return tool_list_notes(str(uid))
    elif name == "delete_note":
        return tool_delete_note(str(uid), inputs["note_id"])
    elif name == "get_datetime":
        return tool_get_datetime()
    elif name == "read_url":
        return tool_read_url(inputs["url"])
    elif name == "get_youtube_transcript":
        return tool_get_youtube_transcript(inputs["video_url"])
    elif name == "add_transaction":
        return finance.add_transaction(
            uid,
            inputs["type"],
            inputs["amount"],
            inputs["category"],
            description=inputs.get("description", ""),
            currency=inputs.get("currency", "UAH"),
            tx_date=inputs.get("date"),
        )
    elif name == "delete_transaction":
        return finance.delete_transaction(uid, inputs["transaction_id"])
    elif name == "list_transactions":
        return finance.list_transactions(uid, month=inputs.get("month"))
    elif name == "finance_summary":
        return finance.finance_summary(uid, month=inputs.get("month"))
    return "Невідомий інструмент."


# ── Агентний цикл ────────────────────────────────────────────────────────────

async def run_agent(uid: int, messages: list) -> str:
    for iteration in range(10):
        resp = claude.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        add_usage(uid, resp.usage.input_tokens, resp.usage.output_tokens)
        log.info(f"run_agent iter={iteration} stop_reason={resp.stop_reason} in={resp.usage.input_tokens} out={resp.usage.output_tokens}")

        if resp.stop_reason == "end_turn":
            for block in resp.content:
                if hasattr(block, "text"):
                    return block.text
            return "Готово."

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input, uid)
                    log.info(f"Tool {block.name} result (перші 200): {result[:200]}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        log.warning(f"Неочікуваний stop_reason={resp.stop_reason}")
        for block in resp.content:
            if hasattr(block, "text"):
                return block.text
        break
    return "Не вдалося отримати відповідь."


# ── Helpers ─────────────────────────────────────────────────────────────────

async def send_long(update: Update, text: str):
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i + 4000])


async def send_response(update: Update, text: str, uid: int):
    if voice_prefs.get(uid):
        try:
            loop = asyncio.get_event_loop()
            ogg_bytes = await loop.run_in_executor(None, text_to_ogg, text)
            await update.message.reply_voice(io.BytesIO(ogg_bytes))
            return
        except Exception:
            log.exception("TTS помилка — відправляємо текст")
    await send_long(update, text)


# ── Telegram handlers ────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я бізнес-асистент з інструментами.\n\n"
        "Що вмію:\n"
        "🔢 Рахую: «скільки буде 15% від 42000»\n"
        "📝 Нотатки: «запиши: зателефонувати Іванову»\n"
        "📅 Дата/час: «яке сьогодні число»\n"
        "🌐 Читаю сайти: «прочитай example.com»\n"
        "🖼 Аналізую фото\n"
        "📄 Читаю PDF\n"
        "💰 Веду фінанси: «витратила 500 грн на пальне», «отримала 20000 за фрахт»\n\n"
        "Фінансові звіти:\n"
        "/report — P&L за місяць (доходи/витрати/прибуток)\n"
        "/cashflow — рух грошей за 6 місяців\n"
        "/dashboard — інтерактивний дашборд з графіками\n\n"
        "Інші команди: /notes — нотатки | /stats — витрати на API | /voice — голос вкл/викл | /reset — очистити розмову"
    )

async def cmd_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    current = voice_prefs.get(uid, False)
    voice_prefs[uid] = not current
    save_voice_prefs(voice_prefs)
    if voice_prefs[uid]:
        await update.message.reply_text("🔊 Голосовий режим увімкнено! Бот відповідатиме голосом.\nВимкнути: /voice")
    else:
        await update.message.reply_text("🔇 Голосовий режим вимкнено. Бот відповідає текстом.\nУвімкнути: /voice")


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    s = user_stats.get(uid, {"input_tokens": 0, "output_tokens": 0, "requests": 0})
    inp = s["input_tokens"]
    out = s["output_tokens"]
    reqs = s["requests"]
    cost_usd = (inp * PRICE_INPUT_PER_M + out * PRICE_OUTPUT_PER_M) / 1_000_000
    cost_uah = cost_usd * 41  # орієнтовний курс
    await update.message.reply_text(
        f"📊 Статистика використання\n\n"
        f"Запитів: {reqs}\n"
        f"Токени вхідні: {inp:,}\n"
        f"Токени вихідні: {out:,}\n"
        f"Разом токенів: {inp + out:,}\n\n"
        f"💰 Приблизна вартість:\n"
        f"  ~${cost_usd:.4f} USD\n"
        f"  ~{cost_uah:.2f} грн\n\n"
        f"Модель: claude-opus-4-7\n"
        f"(Точний рахунок — console.anthropic.com)"
    )

async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """P&L-звіт за місяць. /report — поточний, /report 06.2026 — конкретний."""
    uid = update.effective_user.id
    month = ctx.args[0] if ctx.args else None
    await send_long(update, finance.pnl_report(uid, month))


async def cmd_cashflow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cash Flow — рух грошей за останні 6 місяців."""
    uid = update.effective_user.id
    await send_long(update, finance.cashflow_report(uid))


async def cmd_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Генерує HTML-дашборд з графіками і надсилає файлом."""
    uid = update.effective_user.id
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")
    try:
        path = finance.build_dashboard(uid)
    except Exception:
        log.exception("dashboard error")
        await update.message.reply_text("Помилка при побудові дашборда. Спробуй ще раз.")
        return
    if path is None:
        await update.message.reply_text(
            "Даних для дашборда поки немає.\n"
            "Додай першу операцію — просто напиши, наприклад:\n"
            "«витратила 500 грн на пальне»"
        )
        return
    with path.open("rb") as f:
        await update.message.reply_document(
            document=f,
            filename="finance_dashboard.html",
            caption="📈 Твій фінансовий дашборд.\nВідкрий файл у браузері — графіки інтерактивні.",
        )


async def cmd_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    result = tool_list_notes(str(uid))
    await update.message.reply_text(f"📝 Твої нотатки:\n\n{result}")

async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"Твій Telegram ID: `{uid}`", parse_mode="Markdown")

async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_user.id, None)
    save_history(history)
    await update.message.reply_text("Розмову очищено.")

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    photo = update.message.photo[-1]
    tg_file = await ctx.bot.get_file(photo.file_id)
    import io
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    img_b64 = base64.standard_b64encode(buf.getvalue()).decode()

    caption = update.message.caption or "Опиши що на фото."
    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
        {"type": "text", "text": caption},
    ]
    msgs = history.setdefault(uid, [])
    msgs.append({"role": "user", "content": user_content})

    try:
        text = await run_agent(uid, msgs)
        msgs.append({"role": "assistant", "content": text})
        history[uid] = msgs[-20:]
        save_history(history)
        await send_response(update, text, uid)
    except Exception:
        log.exception("photo error")
        await update.message.reply_text("Помилка обробки фото.")

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    doc = update.message.document

    if doc.mime_type != "application/pdf":
        await update.message.reply_text("Надішли, будь ласка, PDF-файл.")
        return

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await update.message.reply_text("Читаю PDF...")

    tg_file = await ctx.bot.get_file(doc.file_id)
    import io
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    pdf_b64 = base64.standard_b64encode(buf.getvalue()).decode()

    caption = update.message.caption or "Проаналізуй цей документ."
    user_content = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
        {"type": "text", "text": caption},
    ]
    msgs = history.setdefault(uid, [])
    msgs.append({"role": "user", "content": user_content})

    try:
        text = await run_agent(uid, msgs)
        msgs.append({"role": "assistant", "content": text})
        history[uid] = msgs[-10:]
        save_history(history)
        await send_response(update, text, uid)
    except Exception:
        log.exception("document error")
        await update.message.reply_text("Помилка обробки документа.")

async def cmd_invoice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /invoice <назва_папки>
    Запускає пакетну обробку PDF рахунків з вказаної папки на Робочому столі сервера.
    """
    if update.message.from_user.is_bot:
        return

    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Вкажи назву папки з рахунками на Робочому столі.\n\n"
            "Приклад:\n/invoice Рахунки_травень_2026"
        )
        return

    folder_name = " ".join(args)
    await update.message.reply_text(
        f"Починаю обробку папки «{folder_name}»...\n"
        "Це може зайняти кілька хвилин (залежно від кількості PDF)."
    )

    try:
        from ekspedytor.agent import EkspedytorAgent
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(
                pool,
                lambda: EkspedytorAgent().process_folder(folder_name),
            )
    except Exception as e:
        result = f"ПОМИЛКА запуску агента: {e}"

    # Telegram limit 4096 chars per message
    for chunk_start in range(0, len(result), 4000):
        await update.message.reply_text(result[chunk_start:chunk_start + 4000])


async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msgs = history.setdefault(uid, [])
    msgs.append({"role": "user", "content": update.message.text})
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        text = await run_agent(uid, msgs)
        msgs.append({"role": "assistant", "content": text})
        history[uid] = msgs[-20:]
        save_history(history)
        await send_response(update, text, uid)
    except Exception:
        log.exception("chat error")
        await update.message.reply_text("Помилка. Спробуй ще раз.")


def main():
    app = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("voice", cmd_voice))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("notes", cmd_notes))
    app.add_handler(CommandHandler("invoice", cmd_invoice))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("cashflow", cmd_cashflow))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    log.info("Agent bot started with tools")
    app.run_polling()


if __name__ == "__main__":
    main()
