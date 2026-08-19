import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)


TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🔥 Offerte", callback_data="offerte"),
        ],
        [
            InlineKeyboardButton("📱 Elettronica", callback_data="elettronica"),
            InlineKeyboardButton("💻 Informatica", callback_data="informatica"),
        ],
        [
            InlineKeyboardButton("🏠 Casa e Cucina", callback_data="casa"),
        ],
        [
            InlineKeyboardButton("🔗 Inserisci link Amazon", callback_data="link"),
        ],
        [
            InlineKeyboardButton("📦 Inserisci ASIN", callback_data="asin"),
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🛒 *AMAZON OFFER BOT*\n\n"
        "Cosa vuoi fare?",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "offerte":
        text = (
            "🔥 *OFFERTE*\n\n"
            "La ricerca automatica Amazon verrà collegata "
            "quando sarà disponibile la Creators API."
        )

    elif query.data == "elettronica":
        text = "📱 Hai selezionato *Elettronica*."

    elif query.data == "informatica":
        text = "💻 Hai selezionato *Informatica*."

    elif query.data == "casa":
        text = "🏠 Hai selezionato *Casa e Cucina*."

    elif query.data == "link":
        text = (
            "🔗 *Inserisci link Amazon*\n\n"
            "Questa funzione verrà attivata nel prossimo passaggio."
        )

    elif query.data == "asin":
        text = (
            "📦 *Inserisci ASIN*\n\n"
            "Questa funzione verrà attivata nel prossimo passaggio."
        )

    else:
        text = "Comando non riconosciuto."

    await query.edit_message_text(
        text=text,
        parse_mode="Markdown",
    )


def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot Telegram avviato.")

    application.run_polling()


if __name__ == "__main__":
    main()
    
# Railway deployment test
