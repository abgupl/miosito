import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHAT_ID"]

LINK, NOME, PREZZO, VECCHIO_PREZZO, CONFERMA = range(5)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 BOT OFFERTE AMAZON\n\n"
        "Inviami il link Amazon del prodotto che vuoi pubblicare."
    )
    return LINK


async def ricevi_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()

    if "amazon." not in link and "amzn." not in link:
        await update.message.reply_text(
            "❌ Il link non sembra essere un link Amazon.\n\n"
            "Inviami un link Amazon valido."
        )
        return LINK

    context.user_data["link"] = link

    await update.message.reply_text(
        "✅ Link ricevuto.\n\n"
        "📦 Scrivi il nome del prodotto:"
    )

    return NOME


async def ricevi_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nome"] = update.message.text.strip()

    await update.message.reply_text(
        "💰 Qual è il prezzo attuale?\n\n"
        "Esempio: 199,99"
    )

    return PREZZO


async def ricevi_prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["prezzo"] = update.message.text.strip()

    await update.message.reply_text(
        "❌ Qual era il prezzo precedente?\n\n"
        "Esempio: 279,99\n\n"
        "Se non vuoi mostrarlo scrivi: NO"
    )

    return VECCHIO_PREZZO


async def ricevi_vecchio_prezzo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    vecchio = update.message.text.strip()

    context.user_data["vecchio_prezzo"] = vecchio

    link = context.user_data["link"]
    nome = context.user_data["nome"]
    prezzo = context.user_data["prezzo"]

    if vecchio.upper() == "NO":

        messaggio = (
            f"🔥 OFFERTA AMAZON 🔥\n\n"
            f"📦 {nome}\n\n"
            f"💰 {prezzo} €\n\n"
            f"👉 VEDI L'OFFERTA\n"
            f"{link}\n\n"
            f"⚡ Prezzo e disponibilità possono variare."
        )

    else:

        try:
            prezzo_num = float(
                prezzo.replace(",", ".").replace("€", "").strip()
            )

            vecchio_num = float(
                vecchio.replace(",", ".").replace("€", "").strip()
            )

            sconto = round(
                (1 - prezzo_num / vecchio_num) * 100
            )

            sconto_testo = f"🔥 SCONTO {sconto}%\n\n"

        except (ValueError, ZeroDivisionError):

            sconto_testo = ""

        messaggio = (
            f"🔥 OFFERTA AMAZON 🔥\n\n"
            f"📦 {nome}\n\n"
            f"❌ Prima: {vecchio} €\n"
            f"💰 Ora: {prezzo} €\n\n"
            f"{sconto_testo}"
            f"👉 VEDI L'OFFERTA\n"
            f"{link}\n\n"
            f"⚡ Prezzo e disponibilità possono variare."
        )

    context.user_data["messaggio"] = messaggio

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📤 PUBBLICA",
                    callback_data="pubblica"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ ANNULLA",
                    callback_data="annulla"
                )
            ]
        ]
    )

    await update.message.reply_text(
        "👀 ANTEPRIMA DEL POST:\n\n" + messaggio,
        reply_markup=tastiera
    )

    return CONFERMA


async def conferma(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    await query.answer()

    if query.data == "pubblica":

        messaggio = context.user_data.get("messaggio")

        if not messaggio:

            await query.edit_message_text(
                "❌ Non trovo il post da pubblicare."
            )

            return ConversationHandler.END

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=messaggio
        )

        await query.edit_message_text(
            "✅ OFFERTA PUBBLICATA NEL CANALE!"
        )

    elif query.data == "annulla":

        await query.edit_message_text(
            "❌ Pubblicazione annullata."
        )

    context.user_data.clear()

    return ConversationHandler.END


async def annulla(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Operazione annullata."
    )

    return ConversationHandler.END


def main():

    app = Application.builder().token(TOKEN).build()

    conversazione = ConversationHandler(

        entry_points=[
            CommandHandler("start", start)
        ],

        states={

            LINK: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_link
                )
            ],

            NOME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_nome
                )
            ],

            PREZZO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_prezzo
                )
            ],

            VECCHIO_PREZZO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_vecchio_prezzo
                )
            ],

            CONFERMA: [
                CallbackQueryHandler(
                    conferma,
                    pattern="^(pubblica|annulla)$"
                )
            ]
        },

        fallbacks=[
            CommandHandler(
                "annulla",
                annulla
            )
        ]
    )

    app.add_handler(conversazione)

    print("🤖 Bot manuale Amazon avviato...")

    app.run_polling()


if __name__ == "__main__":
    main()
