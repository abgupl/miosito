import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHAT_ID"]

bozze = {}


async def ricevi_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text.strip()

    if "amazon." not in testo and "amzn." not in testo:
        await update.message.reply_text("Mandami un link Amazon.")
        return

    user_id = update.effective_user.id
    bozze[user_id] = testo

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📤 Pubblica", callback_data="pubblica"),
                InlineKeyboardButton("❌ Annulla", callback_data="annulla"),
            ]
        ]
    )

    await update.message.reply_text(
        f"🔥 OFFERTA AMAZON\n\n"
        f"👉 {testo}\n\n"
        "Vuoi pubblicarla nel canale?",
        reply_markup=tastiera,
    )


async def pulsanti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "annulla":
        bozze.pop(user_id, None)
        await query.edit_message_text("❌ Pubblicazione annullata.")
        return

    if query.data == "pubblica":
        link = bozze.get(user_id)

        if not link:
            await query.edit_message_text("Non trovo nessuna offerta da pubblicare.")
            return

        testo = (
            "🔥 OFFERTA AMAZON 🔥\n\n"
            "🛒 Approfitta dell'offerta:\n\n"
            f"👉 {link}\n\n"
            "⚡ Prezzo e disponibilità possono variare."
        )

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=testo,
        )

        bozze.pop(user_id, None)

        await query.edit_message_text("✅ Offerta pubblicata nel canale!")


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_link)
    )

    app.add_handler(
        CallbackQueryHandler(pulsanti)
    )

    print("Bot manuale avviato.")

    app.run_polling()


if __name__ == "__main__":
    main()
