import os, logging, base64
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
history: dict[int, list[dict]] = {}

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

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я допомагаю складати довідки про вартість транспортних послуг.\n\n"
        "Надішли мені PDF-рахунок — я виділю послуги до кордону України і складу довідку.\n\n"
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
    await update.message.reply_text("Розмову очищено. Надішли новий рахунок.")

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    doc = update.message.document

    if not doc.mime_type == "application/pdf":
        await update.message.reply_text("Надішли, будь ласка, файл у форматі PDF.")
        return

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await update.message.reply_text("Читаю PDF...")

    # Завантажуємо файл
    tg_file = await ctx.bot.get_file(doc.file_id)
    import io
    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    pdf_bytes = buf.getvalue()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode()

    # Перевіряємо чи є підпис у повідомленні (caption)
    caption = update.message.caption or ""

    # Формуємо повідомлення для Claude
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
        await update.message.reply_text(text)
    except Exception:
        log.exception("error")
        await update.message.reply_text("Помилка при обробці файлу. Спробуй ще раз.")

async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    history.setdefault(uid, []).append({"role": "user", "content": update.message.text})
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
