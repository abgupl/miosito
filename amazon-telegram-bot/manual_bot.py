import os
from collections import deque

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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

# Facoltativo: se impostato su Railway, solo tu potrai usare il bot
ADMIN_ID = os.environ.get("ADMIN_TELEGRAM_ID")

LINK, NOME, PREZZO, VECCHIO_PREZZO, CONFERMA, RAPIDO = range(6)

ultime_offerte = deque(maxlen=10)


# =========================================================
# SICUREZZA
# =========================================================

def autorizzato(update: Update) -> bool:
    if not ADMIN_ID:
        return True

    user = update.effective_user

    if not user:
        return False

    return str(user.id) == str(ADMIN_ID)


async def controlla_autorizzazione(update: Update):
    if autorizzato(update):
        return True

    if update.message:
        await update.message.reply_text(
            "⛔ Non sei autorizzato a utilizzare questo bot."
        )

    elif update.callback_query:
        await update.callback_query.answer(
            "Non sei autorizzato.",
            show_alert=True,
        )

    return False


# =========================================================
# MENU PRINCIPALE
# =========================================================

def menu_principale():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ NUOVA OFFERTA",
                    callback_data="nuova",
                )
            ],
            [
                InlineKeyboardButton(
                    "⚡ MODALITÀ RAPIDA",
                    callback_data="rapido",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎨 TEMPLATE",
                    callback_data="template",
                ),
                InlineKeyboardButton(
                    "📋 ULTIME",
                    callback_data="ultime",
                ),
            ],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    await update.message.reply_text(
        "🔥 AMAZON OFFERTE BOT\n\n"
        "Cosa vuoi fare?",
        reply_markup=menu_principale(),
    )

    return ConversationHandler.END


# =========================================================
# ID TELEGRAM
# =========================================================

async def mio_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Il tuo Telegram User ID è:\n\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# NUOVA OFFERTA
# =========================================================

async def nuova_da_comando(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data.clear()

    await update.message.reply_text(
        "🔗 Inviami il link Amazon del prodotto:"
    )

    return LINK


async def nuova_da_pulsante(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.message.reply_text(
        "🔗 Inviami il link Amazon del prodotto:"
    )

    return LINK


async def ricevi_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    link = update.message.text.strip()

    if "amazon." not in link and "amzn." not in link:
        await update.message.reply_text(
            "❌ Non sembra un link Amazon.\n\n"
            "Inviami un link valido:"
        )

        return LINK

    context.user_data["link"] = link

    await update.message.reply_text(
        "📦 Scrivi il nome del prodotto:"
    )

    return NOME


async def ricevi_nome(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["nome"] = update.message.text.strip()

    await update.message.reply_text(
        "💰 Qual è il prezzo attuale?\n\n"
        "Esempio: 39,99"
    )

    return PREZZO


async def ricevi_prezzo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["prezzo"] = update.message.text.strip()

    await update.message.reply_text(
        "🏷️ Qual era il prezzo precedente?\n\n"
        "Esempio: 59,99\n\n"
        "Oppure scrivi: NO"
    )

    return VECCHIO_PREZZO


async def ricevi_vecchio_prezzo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["vecchio_prezzo"] = update.message.text.strip()

    return await mostra_anteprima(update, context)


# =========================================================
# MODALITÀ RAPIDA
# =========================================================

async def rapido_da_comando(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data.clear()

    await update.message.reply_text(
        "⚡ MODALITÀ RAPIDA\n\n"
        "Mandami tutto in una sola riga:\n\n"
        "LINK | NOME | PREZZO | PREZZO PRIMA\n\n"
        "Esempio:\n"
        "https://www.amazon.it/... | AirPods Pro | 199,99 | 279,99\n\n"
        "Se non c'è il prezzo precedente usa NO."
    )

    return RAPIDO


async def rapido_da_pulsante(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.message.reply_text(
        "⚡ MODALITÀ RAPIDA\n\n"
        "Invia:\n\n"
        "LINK | NOME | PREZZO | PREZZO PRIMA\n\n"
        "Esempio:\n"
        "https://www.amazon.it/... | AirPods Pro | 199,99 | 279,99"
    )

    return RAPIDO


async def ricevi_rapido(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    parti = [
        parte.strip()
        for parte in update.message.text.split("|")
    ]

    if len(parti) != 4:
        await update.message.reply_text(
            "❌ Formato non corretto.\n\n"
            "Usa:\n"
            "LINK | NOME | PREZZO | PREZZO PRIMA"
        )

        return RAPIDO

    link, nome, prezzo, vecchio = parti

    if "amazon." not in link and "amzn." not in link:
        await update.message.reply_text(
            "❌ Il primo campo deve essere un link Amazon."
        )

        return RAPIDO

    context.user_data["link"] = link
    context.user_data["nome"] = nome
    context.user_data["prezzo"] = prezzo
    context.user_data["vecchio_prezzo"] = vecchio

    return await mostra_anteprima(update, context)


# =========================================================
# CALCOLO SCONTO
# =========================================================

def calcola_sconto(prezzo, vecchio):
    try:
        nuovo = float(
            prezzo
            .replace("€", "")
            .replace(",", ".")
            .strip()
        )

        precedente = float(
            vecchio
            .replace("€", "")
            .replace(",", ".")
            .strip()
        )

        if precedente <= 0:
            return None

        return round(
            (1 - nuovo / precedente) * 100
        )

    except (ValueError, ZeroDivisionError):
        return None


# =========================================================
# TEMPLATE
# =========================================================

def crea_messaggio(context):
    nome = context.user_data["nome"]
    prezzo = context.user_data["prezzo"]
    vecchio = context.user_data["vecchio_prezzo"]

    template = context.user_data.get(
        "template",
        "pulito",
    )

    sconto = None

    if vecchio.upper() != "NO":
        sconto = calcola_sconto(
            prezzo,
            vecchio,
        )

    if template == "aggressivo":
        testo = (
            f"🚨 SUPER OFFERTA AMAZON 🚨\n\n"
            f"🔥 {nome}\n\n"
        )

        if vecchio.upper() != "NO":
            testo += f"❌ Prima: {vecchio} €\n"

        testo += f"✅ ORA: {prezzo} €\n"

        if sconto is not None:
            testo += f"\n💥 SCONTO {sconto}%"

        testo += (
            "\n\n⚡ Approfittane prima che cambi il prezzo!"
        )

        return testo

    if template == "tech":
        testo = (
            f"⚡ TECH DEAL\n\n"
            f"📱 {nome}\n\n"
        )

        if vecchio.upper() != "NO":
            testo += f"🏷️ Listino: {vecchio} €\n"

        testo += f"💰 Offerta: {prezzo} €\n"

        if sconto is not None:
            testo += f"📉 -{sconto}%"

        return testo

    # TEMPLATE PULITO

    testo = (
        f"🔥 OFFERTA AMAZON\n\n"
        f"📦 {nome}\n\n"
    )

    if vecchio.upper() != "NO":
        testo += f"❌ Prima: {vecchio} €\n"

    testo += f"✅ Ora: {prezzo} €\n"

    if sconto is not None:
        testo += f"\n🔥 Sconto: {sconto}%"

    return testo


# =========================================================
# ANTEPRIMA
# =========================================================

async def mostra_anteprima(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    messaggio = crea_messaggio(context)

    context.user_data["messaggio"] = messaggio

    link = context.user_data.get("link", "")

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📤 PUBBLICA",
                    callback_data="pubblica",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎨 CAMBIA TEMPLATE",
                    callback_data="cambia_template",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ ANNULLA",
                    callback_data="annulla",
                )
            ],
        ]
    )

    testo = (
        "👀 ANTEPRIMA\n\n"
        "──────────────\n\n"
        f"{messaggio}\n\n"
        f"👉 {link}\n\n"
        "⚡ Prezzo e disponibilità possono variare."
    )

    if update.message:
        await update.message.reply_text(
            testo,
            reply_markup=tastiera,
        )
    else:
        await update.callback_query.message.reply_text(
            testo,
            reply_markup=tastiera,
        )

    return CONFERMA


# =========================================================
# PUBBLICAZIONE
# =========================================================

async def conferma(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    if query.data == "annulla":
        context.user_data.clear()

        await query.edit_message_text(
            "❌ Pubblicazione annullata."
        )

        await query.message.reply_text(
            "Cosa vuoi fare?",
            reply_markup=menu_principale(),
        )

        return ConversationHandler.END

    if query.data == "cambia_template":
        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✨ Pulito",
                        callback_data="tpl_pulito",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🚨 Aggressivo",
                        callback_data="tpl_aggressivo",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⚡ Tech",
                        callback_data="tpl_tech",
                    )
                ],
            ]
        )

        await query.message.reply_text(
            "🎨 Scegli il template:",
            reply_markup=tastiera,
        )

        return CONFERMA

    if query.data.startswith("tpl_"):
        template = query.data.replace(
            "tpl_",
            "",
        )

        context.user_data["template"] = template

        await query.edit_message_text(
            f"✅ Template selezionato: {template}"
        )

        return await mostra_anteprima(
            update,
            context,
        )

    if query.data == "pubblica":
        messaggio = context.user_data.get(
            "messaggio"
        )

        link = context.user_data.get(
            "link"
        )

        nome = context.user_data.get(
            "nome"
        )

        if not messaggio or not link:
            await query.edit_message_text(
                "❌ Dati dell'offerta mancanti."
            )

            return ConversationHandler.END

        # IMPORTANTE:
        # Il link è presente anche nel testo del post,
        # così Telegram può generare l'anteprima Amazon.
        messaggio_con_link = (
            f"{messaggio}\n\n"
            f"👉 {link}\n\n"
            f"⚡ Prezzo e disponibilità possono variare."
        )

        bottone_offerta = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🛒 VEDI OFFERTA",
                        url=link,
                    )
                ]
            ]
        )

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=messaggio_con_link,
            reply_markup=bottone_offerta,
        )

        ultime_offerte.appendleft(
            {
                "nome": nome,
                "link": link,
                "prezzo": context.user_data.get(
                    "prezzo"
                ),
            }
        )

        context.user_data.clear()

        await query.edit_message_text(
            "✅ OFFERTA PUBBLICATA!"
        )

        await query.message.reply_text(
            "Vuoi pubblicarne un'altra?",
            reply_markup=menu_principale(),
        )

        return ConversationHandler.END


# =========================================================
# ULTIME OFFERTE
# =========================================================

async def ultime(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await controlla_autorizzazione(update):
        return

    if not ultime_offerte:
        testo = (
            "📋 Nessuna offerta pubblicata "
            "da quando il bot è stato avviato."
        )

    else:
        righe = ["📋 ULTIME OFFERTE\n"]

        for numero, offerta in enumerate(
            ultime_offerte,
            start=1,
        ):
            righe.append(
                f"{numero}. {offerta['nome']} "
                f"— {offerta['prezzo']} €"
            )

        testo = "\n".join(righe)

    if update.message:
        await update.message.reply_text(testo)

    else:
        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            testo
        )


# =========================================================
# TEMPLATE DAL MENU
# =========================================================

async def template_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query
    await query.answer()

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✨ Pulito",
                    callback_data="menu_tpl_pulito",
                )
            ],
            [
                InlineKeyboardButton(
                    "🚨 Aggressivo",
                    callback_data="menu_tpl_aggressivo",
                )
            ],
            [
                InlineKeyboardButton(
                    "⚡ Tech",
                    callback_data="menu_tpl_tech",
                )
            ],
        ]
    )

    await query.message.reply_text(
        "🎨 Scegli il template predefinito:",
        reply_markup=tastiera,
    )


async def scegli_template_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    template = query.data.replace(
        "menu_tpl_",
        "",
    )

    context.user_data["template"] = template

    await query.edit_message_text(
        f"✅ Template impostato: {template}"
    )


# =========================================================
# ANNULLA
# =========================================================

async def annulla(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Operazione annullata.",
        reply_markup=menu_principale(),
    )

    return ConversationHandler.END


# =========================================================
# AVVIO
# =========================================================

def main():
    app = Application.builder().token(TOKEN).build()

    conversazione = ConversationHandler(
        entry_points=[
            CommandHandler(
                "nuova",
                nuova_da_comando,
            ),
            CommandHandler(
                "rapido",
                rapido_da_comando,
            ),
            CallbackQueryHandler(
                nuova_da_pulsante,
                pattern="^nuova$",
            ),
            CallbackQueryHandler(
                rapido_da_pulsante,
                pattern="^rapido$",
            ),
        ],

        states={
            LINK: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_link,
                )
            ],

            NOME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_nome,
                )
            ],

            PREZZO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_prezzo,
                )
            ],

            VECCHIO_PREZZO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_vecchio_prezzo,
                )
            ],

            RAPIDO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_rapido,
                )
            ],

            CONFERMA: [
                CallbackQueryHandler(
                    conferma,
                    pattern=(
                        "^(pubblica|annulla|"
                        "cambia_template|"
                        "tpl_pulito|"
                        "tpl_aggressivo|"
                        "tpl_tech)$"
                    ),
                )
            ],
        },

        fallbacks=[
            CommandHandler(
                "annulla",
                annulla,
            )
        ],

        allow_reentry=True,
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "id",
            mio_id,
        )
    )

    app.add_handler(
        CommandHandler(
            "ultime",
            ultime,
        )
    )

    app.add_handler(conversazione)

    app.add_handler(
        CallbackQueryHandler(
            ultime,
            pattern="^ultime$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            template_menu,
            pattern="^template$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            scegli_template_menu,
            pattern="^menu_tpl_",
        )
    )

    print("🤖 Amazon Offer Bot V2 avviato")

    app.run_polling()


if __name__ == "__main__":
    main()
