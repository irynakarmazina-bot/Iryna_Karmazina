import os, logging, base64, re, json
for v in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"):
    os.environ.pop(v, None)
from dotenv import load_dotenv
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "chat_history.json")

def load_history() -> dict[int, list[dict]]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
        except Exception:
            log.exception("Не вдалося завантажити chat_history.json")
    return {}

def save_history(h: dict[int, list[dict]]):
    try:
        # Зберігаємо тільки текстовий вміст — пропускаємо великі PDF-об'єкти
        saveable = {}
        for uid, msgs in h.items():
            clean = []
            for m in msgs:
                if isinstance(m["content"], str):
                    clean.append(m)
                elif isinstance(m["content"], list):
                    # Замінюємо PDF-блоки на текстовий заповнювач
                    text_parts = [
                        p["text"] for p in m["content"]
                        if p.get("type") == "text"
                    ]
                    placeholder = " ".join(text_parts) if text_parts else "[PDF документ]"
                    clean.append({"role": m["role"], "content": placeholder})
            if clean:
                saveable[str(uid)] = clean
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(saveable, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("Не вдалося зберегти chat_history.json")

history: dict[int, list[dict]] = load_history()

# Зберігаємо шаблон довідки для кожного користувача
templates: dict[int, bytes] = {}
# Зберігаємо рахунок поки чекаємо на додаткові дані
pending_invoices: dict[int, bytes] = {}

SYSTEM_PROMPT = """Ти асистент логістичної компанії. Говориш українською.

Коли отримуєш PDF-рахунок на транспортні послуги:
1. Виділи всі послуги де маршрут або опис вказує на перевезення ДО кордону України (до Ukrainian border, до Чопа, до Мостиська, до Ягодина, до Ковеля тощо — будь-який пункт на кордоні України)
2. Посумуй їх вартість
3. Запам'ятай валюту

Якщо надано шаблон довідки — заповни його за зразком.
Якщо шаблону немає — сформуй довідку у такому форматі:

ДОВІДКА
про вартість транспортних послуг

Коносамент №: [значення або "-"]
ЦМР №: [значення або "-"]
Контейнер №: [значення або "-"]
Авто/Рейс: [значення або "-"]

Послуги до кордону України:
[номер]. [назва послуги] — [маршрут] — [сума] [валюта]

РАЗОМ до кордону України: [сума] [валюта]

Якщо якихось реквізитів (коносамент, ЦМР, контейнер, авто) немає в рахунку — ОБОВ'ЯЗКОВО запитай їх у користувача перед тим як видати довідку."""

YOUTUBE_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([\w-]+)'
)

def extract_youtube_id(text: str) -> tuple[str, str] | tuple[None, None]:
    m = YOUTUBE_PATTERN.search(text)
    if m:
        return m.group(0), m.group(1)
    return None, None

async def summarize_youtube(update: Update, ctx: ContextTypes.DEFAULT_TYPE, url: str, video_id: str):
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await update.message.reply_text("Отримую субтитри відео...")

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        fetcher = YouTubeTranscriptApi()
        # Спочатку пробуємо українську, потім російську, потім англійську
        try:
            transcript_obj = fetcher.fetch(video_id, languages=['uk', 'ru', 'en'])
        except Exception:
            # Якщо конкретні мови недоступні — беремо будь-яку
            listing = fetcher.list(video_id)
            first = next(iter(listing))
            transcript_obj = first.fetch()

        snippets = list(transcript_obj)
        full_text = ' '.join(item.text for item in snippets)
    except Exception as e:
        log.exception("YouTube transcript error")
        await update.message.reply_text(
            "Не вдалося отримати субтитри відео.\n"
            "Можливі причини:\n"
            "• Субтитри вимкнені автором\n"
            "• Відео недоступне в цьому регіоні\n"
            "• Технічна помилка\n\n"
            f"Спробуй надіслати текст або питання про відео — я відповім на основі своїх знань."
        )
        return

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await update.message.reply_text("Аналізую вміст...")

    # Обрізаємо до ~15 000 символів щоб не перевищити ліміти
    text_for_claude = full_text[:15000]
    if len(full_text) > 15000:
        text_for_claude += "\n\n[...транскрипт скорочено...]"

    prompt = f"""Я надаю транскрипт відео з YouTube: {url}

Транскрипт:
{text_for_claude}

Зроби, будь ласка:
1. **Короткий переказ** (3-5 речень) — про що це відео
2. **Основні моменти** — 5-8 ключових тез у вигляді маркованого списку
3. **Важливі факти/цифри** — якщо є конкретні дані, дати, статистика

Відповідай українською."""

    try:
        resp = claude.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        result_text = resp.content[0].text
        await update.message.reply_text(result_text)
    except Exception:
        log.exception("Claude error")
        await update.message.reply_text("Помилка при аналізі відео. Спробуй ще раз.")

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я допомагаю складати довідки про вартість транспортних послуг.\n\n"
        "Надішли мені PDF-рахунок — я виділю послуги до кордону України і складу довідку.\n\n"
        "Також можу зробити переказ YouTube-відео — просто надішли посилання!\n\n"
        "Команди:\n"
        "/start — це повідомлення\n"
        "/reset — очистити розмову\n"
        "/template — надіслати шаблон довідки (необов'язково)"
    )

async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"Твій Telegram ID: `{uid}`", parse_mode="Markdown")

async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    history.pop(uid, None)
    pending_invoices.pop(uid, None)
    save_history(history)
    await update.message.reply_text("Розмову очищено. Надішли новий рахунок.")

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    doc = update.message.document

    if not doc.mime_type == "application/pdf":
        await update.message.reply_text("Надішли, будь ласка, файл у форматі PDF.")
        return

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await update.message.reply_text("Читаю PDF...")

    tg_file = await ctx.bot.get_file(doc.file_id)
    import io
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    pdf_bytes = buf.getvalue()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode()

    caption = update.message.caption or ""

    user_content = [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_b64,
            },
        },
    ]

    if caption:
        user_content.append({"type": "text", "text": caption})
    else:
        user_content.append({
            "type": "text",
            "text": "Це рахунок на транспортні послуги. Виділи послуги до кордону України, посумуй їх вартість і склади довідку. Якщо не вистачає реквізитів (коносамент, ЦМР, контейнер, авто) — запитай їх."
        })

    history.setdefault(uid, []).append({"role": "user", "content": user_content})

    try:
        resp = claude.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=history[uid],
        )
        text = resp.content[0].text
        history[uid].append({"role": "assistant", "content": text})
        history[uid] = history[uid][-10:]
        save_history(history)
        await update.message.reply_text(text)
    except Exception:
        log.exception("error")
        await update.message.reply_text("Помилка при обробці файлу. Спробуй ще раз.")

async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.is_bot:
        return

    uid = update.effective_user.id
    text_msg = update.message.text or ""

    # Перевіряємо чи є YouTube-посилання
    url, video_id = extract_youtube_id(text_msg)
    if video_id:
        await summarize_youtube(update, ctx, url, video_id)
        return

    history.setdefault(uid, []).append({"role": "user", "content": text_msg})
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        resp = claude.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=history[uid],
        )
        text = resp.content[0].text
        history[uid].append({"role": "assistant", "content": text})
        history[uid] = history[uid][-20:]
        save_history(history)
        await update.message.reply_text(text)
    except Exception:
        log.exception("error")
        await update.message.reply_text("Помилка. Спробуй ще раз.")

def main():
    app = ApplicationBuilder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    log.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
