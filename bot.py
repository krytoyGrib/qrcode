import logging
import qrcode
import sqlite3
import phonenumbers
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
)

# КОНФИГУРАЦИЯ
TOKEN = "8856906549:AAEhzSYr_arBR6sgpsicvS_WBid08KXW-Qw"  


NAME, PHONE, WAITING_MSG = range(3)

# Тексты 
TEXTS = {
    "welcome": "Привет! Давайте создадим ваш QR-код.\nВведите ваше ФИО:",
    "ask_phone": "Теперь введите ваш белорусский номер телефона в формате +375XXXXXXXXX (например, +375291234567):",
    "qr_ready": "✅ Ваш QR-код готов!\nПри сканировании откроется бот с вашими данными.\n\nСсылка для копирования: {}",
    "not_found": "Владелец этого QR-кода не найден.",
    "contact_info": "👤 Контактные данные владельца:\nИмя: {name}\n📞 Телефон: {phone}",
    "contact_btn": "💬 Связаться с владельцем",
    "msg_prompt": "✍️ Напишите ваше сообщение для владельца, и я его перешлю.",
    "msg_sent": "✅ Сообщение отправлено владельцу.",
    "msg_fail": "❌ Не удалось отправить сообщение.",
    "cancel": "Операция отменена.",
    "wrong_phone": "Некорректный белорусский номер. Введите в формате +375XXXXXXXXX (9 цифр после +375).",
    "owner_notify": "Ваш QR-код создан! Теперь вы можете получать сообщения от других пользователей.",
    "help": "🤖 *QR Contact Bot*\n/start – Создать QR-код или посмотреть контакт\n/cancel – Отменить текущую операцию\n/help – Показать эту справку",
}

# БД
def init_db():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  name TEXT,
                  phone TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
    )
    conn.commit()
    conn.close()

def save_owner(user_id, name, phone):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO users (user_id, name, phone) VALUES (?,?,?)",
        (user_id, name, phone),
    )
    conn.commit()
    conn.close()

def get_owner(user_id):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT name, phone FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {"name": row[0], "phone": row[1]} if row else None

# QR
def generate_qr(data: str) -> BytesIO:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

# ОБРАБОТЧИКИ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id

    # Если запущен с параметром (сканирование QR)
    if args and args[0].startswith("owner_"):
        try:
            owner_id = int(args[0].split("_")[1])
        except ValueError:
            await update.message.reply_text(TEXTS["not_found"])
            return ConversationHandler.END

        owner = get_owner(owner_id)
        if not owner:
            await update.message.reply_text(TEXTS["not_found"])
            return ConversationHandler.END

        context.user_data["owner_id"] = owner_id
        text = TEXTS["contact_info"].format(name=owner["name"], phone=owner["phone"])
        keyboard = [
            [InlineKeyboardButton(TEXTS["contact_btn"], callback_data="contact_owner")]
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return WAITING_MSG

    # Обычный старт – создание QR
    await update.message.reply_text(TEXTS["welcome"])
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text(TEXTS["ask_phone"])
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_raw = update.message.text
    user_id = update.effective_user.id

    # Валидация белорусского номера
    try:
        parsed = phonenumbers.parse(phone_raw, "BY")
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError
        if phonenumbers.region_code_for_number(parsed) != "BY":
            raise ValueError
        phone = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except:
        await update.message.reply_text(TEXTS["wrong_phone"])
        return PHONE

    name = context.user_data["name"]
    save_owner(user_id, name, phone)

    bot_username = context.bot.username
    deep_link = f"https://t.me/{bot_username}?start=owner_{user_id}"
    qr_image = generate_qr(deep_link)

    await update.message.reply_photo(
        photo=qr_image,
        caption=TEXTS["qr_ready"].format(deep_link),
    )
    await update.message.reply_text(TEXTS["owner_notify"])
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXTS["cancel"])
    return ConversationHandler.END

async def contact_owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    owner_id = context.user_data.get("owner_id")
    if not owner_id:
        await query.edit_message_text(TEXTS["not_found"])
        return
    context.user_data["forward_to"] = owner_id
    await query.edit_message_text(TEXTS["msg_prompt"])

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    owner_id = context.user_data.get("forward_to")
    if not owner_id:
        await update.message.reply_text(
            "Я не понимаю. Используйте /start для создания QR или просмотра контактов."
        )
        return ConversationHandler.END

    msg_text = update.message.text
    sender = update.effective_user
    forward_text = f"✉️ Вам написал {sender.first_name} (@{sender.username}):\n\n{msg_text}"
    try:
        await context.bot.send_message(chat_id=owner_id, text=forward_text)
        await update.message.reply_text(TEXTS["msg_sent"])
    except Exception:
        await update.message.reply_text(TEXTS["msg_fail"])

    del context.user_data["forward_to"]
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXTS["help"], parse_mode="Markdown")

# ===== ЗАПУСК =====
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            WAITING_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(contact_owner_callback, pattern="contact_owner"))
    app.add_handler(CommandHandler("help", help_command))

    logging.basicConfig(level=logging.INFO)
    print("🚀 Бот запущен! Принимаются только белорусские номера (+375).")
    app.run_polling()

if __name__ == "__main__":
    main()
