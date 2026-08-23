import os
import asyncio
from collections import deque

import requests
from bs4 import BeautifulSoup

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


# =========================================================
# CLUB / PUNTI
# =========================================================

from club import (
    inizializza_database,
    registra_utente,
    menu_club,
    mostra_punti,
    invita_amici,
    mostra_premi,
    richiedi_premio,
    gestisci_premio_admin,
    club_home,

    admin_club_menu,
    admin_club_utenti,
    admin_club_utente,
    admin_modifica_punti,
    admin_storico_utente,
    admin_movimenti,
    admin_inviti,
    admin_premi,
)


# =========================================================
# CONFIGURAZIONE
# =========================================================

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHAT_ID"]
ADMIN_ID = os.environ.get("ADMIN_TELEGRAM_ID")


(
    LINK,
    NOME,
    PREZZO,
    VECCHIO_PREZZO,
    CONFERMA,
    RAPIDO,
    DATI_AUTOMATICI,
) = range(7)


ultime_offerte = deque(maxlen=10)


# =========================================================
# SICUREZZA ADMIN
# =========================================================

def autorizzato(update: Update) -> bool:

    if not ADMIN_ID:
        return False

    user = update.effective_user

    if not user:
        return False

    return str(user.id) == str(ADMIN_ID)


async def controlla_autorizzazione(update: Update):

    if autorizzato(update):
        return True

    if update.message:
        await update.message.reply_text(
            "⛔ Questa funzione è riservata all'amministratore."
        )

    elif update.callback_query:
        await update.callback_query.answer(
            "⛔ Funzione riservata all'amministratore.",
            show_alert=True,
        )

    return False


# =========================================================
# MENU ADMIN
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
            [
                InlineKeyboardButton(
                    "👥 GESTIONE CLUB",
                    callback_data="admin_club",
                )
            ],
        ]
    )


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return ConversationHandler.END

    # ADMIN
    if autorizzato(update):

        await update.message.reply_text(
            "🔥 AMAZON OFFERTE BOT\n\n"
            "🛠 Modalità amministratore\n\n"
            "Cosa vuoi fare?",
            reply_markup=menu_principale(),
        )

        return ConversationHandler.END

    # UTENTE CLUB
    invitato_da = None

    if context.args:

        try:
            invitato_da = int(context.args[0])

        except (ValueError, TypeError):
            invitato_da = None

    nuovo = registra_utente(
        user,
        invitato_da
    )

    testo = (
        "🔥 BENVENUTO NEL CLUB OFFERTE\n\n"
        "Qui le offerte non sono l'unico vantaggio. 😉\n\n"
        "Invita i tuoi amici, accumula punti "
        "e sblocca premi!\n\n"
        "👥 Ogni amico valido = 2 punti\n"
        "🎁 10 punti = Buono Amazon da 5 €\n\n"
    )

    if nuovo and invitato_da:
        testo += (
            "👥 Sei entrato tramite "
            "l'invito di un amico!\n\n"
        )

    testo += (
        "⭐ Il tuo saldo: 0 punti\n"
        "👥 Amici premiati questo mese: 0/5\n\n"
        "I tuoi punti si accumulano e puoi "
        "controllarli quando vuoi.\n\n"
        "🚀 Porta i tuoi amici nel Club "
        "e raggiungi il prossimo premio!\n\n"
        "👇 Cosa vuoi fare?"
    )

    await update.message.reply_text(
        testo,
        reply_markup=menu_club(),
    )

    return ConversationHandler.END


# =========================================================
# TELEGRAM ID
# =========================================================

async def mio_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🆔 Il tuo Telegram User ID è:\n\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# LETTURA AUTOMATICA AMAZON
# =========================================================

def leggi_prodotto_amazon(url):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
        "Accept-Language": (
            "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
    }

    try:

        risposta = requests.get(
            url,
            headers=headers,
            timeout=15,
            allow_redirects=True,
        )

        if risposta.status_code != 200:
            return None

        soup = BeautifulSoup(
            risposta.text,
            "html.parser",
        )

        titolo = None
        prezzo = None
        vecchio_prezzo = None

        selettori_titolo = [
            "#productTitle",
            "#title",
            "h1 span",
        ]

        for selettore in selettori_titolo:

            elemento = soup.select_one(selettore)

            if elemento:

                valore = elemento.get_text(
                    " ",
                    strip=True,
                )

                if valore:
                    titolo = valore
                    break

        selettori_prezzo = [
            ".priceToPay .a-offscreen",
            ".apexPriceToPay .a-offscreen",
            "#corePrice_feature_div .a-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            ".a-price .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
        ]

        for selettore in selettori_prezzo:

            elemento = soup.select_one(selettore)

            if elemento:

                valore = elemento.get_text(
                    " ",
                    strip=True,
                )

                if valore:
                    prezzo = valore
                    break

        selettori_vecchio = [
            ".basisPrice .a-offscreen",
            ".a-price.a-text-price .a-offscreen",
            "#corePrice_feature_div .a-text-price .a-offscreen",
            ".savingPriceOverride .a-price.a-text-price .a-offscreen",
        ]

        for selettore in selettori_vecchio:

            elemento = soup.select_one(selettore)

            if elemento:

                valore = elemento.get_text(
                    " ",
                    strip=True,
                )

                if valore:

                    if prezzo and valore == prezzo:
                        continue

                    vecchio_prezzo = valore
                    break

        if not titolo and not prezzo:
            return None

        return {
            "nome": titolo,
            "prezzo": prezzo,
            "vecchio_prezzo": vecchio_prezzo,
        }

    except requests.RequestException:
        return None

    except Exception as errore:

        print(
            f"Errore lettura Amazon: {errore}"
        )

        return None


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


# =========================================================
# RICEZIONE LINK
# =========================================================

async def ricevi_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    link = update.message.text.strip()

    if (
        "amazon." not in link
        and "amzn." not in link
    ):

        await update.message.reply_text(
            "❌ Non sembra un link Amazon.\n\n"
            "Inviami un link Amazon valido:"
        )

        return LINK

    context.user_data["link"] = link

    messaggio_attesa = (
        await update.message.reply_text(
            "🔎 Sto provando a leggere automaticamente "
            "i dati del prodotto..."
        )
    )

    dati = await asyncio.to_thread(
        leggi_prodotto_amazon,
        link,
    )

    if not dati:

        await messaggio_attesa.edit_text(
            "⚠️ Non sono riuscito a leggere "
            "automaticamente i dati.\n\n"
            "Nessun problema: continuiamo manualmente.\n\n"
            "📦 Scrivi il nome del prodotto:"
        )

        return NOME

    nome = dati.get("nome")
    prezzo = dati.get("prezzo")
    vecchio = dati.get("vecchio_prezzo")

    if not nome or not prezzo:

        await messaggio_attesa.edit_text(
            "⚠️ Ho trovato solo una parte dei dati.\n\n"
            "Continuiamo manualmente.\n\n"
            "📦 Scrivi il nome del prodotto:"
        )

        return NOME

    context.user_data["nome"] = nome
    context.user_data["prezzo"] = pulisci_prezzo(prezzo)

    if vecchio:
        context.user_data["vecchio_prezzo"] = pulisci_prezzo(vecchio)
    else:
        context.user_data["vecchio_prezzo"] = "NO"

    vecchio_testo = context.user_data["vecchio_prezzo"]

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ USA QUESTI DATI",
                    callback_data="dati_ok",
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ INSERISCI MANUALMENTE",
                    callback_data="dati_manual",
                )
            ],
        ]
    )

    await messaggio_attesa.edit_text(
        "✅ DATI TROVATI\n\n"
        f"📦 {context.user_data['nome']}\n\n"
        f"💰 Prezzo: {context.user_data['prezzo']} €\n"
        f"🏷️ Prima: {vecchio_testo}"
        f"{' €' if vecchio_testo != 'NO' else ''}\n\n"
        "Controlla che prezzo e prodotto siano corretti.",
        reply_markup=tastiera,
    )

    return DATI_AUTOMATICI


# =========================================================
# CONFERMA DATI AUTOMATICI
# =========================================================

async def conferma_dati_automatici(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query

    await query.answer()

    if query.data == "dati_ok":

        await query.edit_message_text(
            "✅ Dati confermati."
        )

        return await mostra_anteprima(
            update,
            context,
        )

    if query.data == "dati_manual":

        link = context.user_data.get("link")

        context.user_data.clear()

        context.user_data["link"] = link

        await query.edit_message_text(
            "✏️ Inserimento manuale selezionato."
        )

        await query.message.reply_text(
            "📦 Scrivi il nome del prodotto:"
        )

        return NOME


# =========================================================
# INSERIMENTO MANUALE
# =========================================================

async def ricevi_nome(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data["nome"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "💰 Qual è il prezzo attuale?\n\n"
        "Esempio: 39,99"
    )

    return PREZZO


async def ricevi_prezzo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data["prezzo"] = pulisci_prezzo(
        update.message.text.strip()
    )

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

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    valore = update.message.text.strip()

    if valore.upper() == "NO":

        context.user_data["vecchio_prezzo"] = "NO"

    else:

        context.user_data["vecchio_prezzo"] = pulisci_prezzo(
            valore
        )

    return await mostra_anteprima(
        update,
        context,
    )


# =========================================================
# PULIZIA PREZZO
# =========================================================

def pulisci_prezzo(prezzo):

    if not prezzo:
        return ""

    prezzo = str(prezzo)

    prezzo = prezzo.replace("\xa0", " ")
    prezzo = prezzo.replace("EUR", "")
    prezzo = prezzo.replace("€", "")

    return prezzo.strip()


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
        "LINK - NOME - PREZZO - PREZZO PRIMA\n\n"
        "Esempio:\n"
        "https://www.amazon.it/dp/XXXX "
        "- AirPods Pro "
        "- 199,99 "
        "- 279,99\n\n"
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
        "Invia tutto in una sola riga:\n\n"
        "LINK - NOME - PREZZO - PREZZO PRIMA\n\n"
        "Esempio:\n"
        "https://www.amazon.it/dp/XXXX "
        "- AirPods Pro "
        "- 199,99 "
        "- 279,99\n\n"
        "Senza prezzo precedente:\n"
        "https://www.amazon.it/dp/XXXX "
        "- AirPods Pro "
        "- 199,99 "
        "- NO"
    )

    return RAPIDO


async def ricevi_rapido(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    testo = update.message.text.strip()

    parti = [
        parte.strip()
        for parte in testo.split(
            " - ",
            3,
        )
    ]

    if len(parti) != 4:

        await update.message.reply_text(
            "❌ Formato non corretto.\n\n"
            "Usa esattamente:\n\n"
            "LINK - NOME - PREZZO - PREZZO PRIMA"
        )

        return RAPIDO

    link, nome, prezzo, vecchio = parti

    if (
        "amazon." not in link
        and "amzn." not in link
    ):

        await update.message.reply_text(
            "❌ Il primo campo deve essere un link Amazon."
        )

        return RAPIDO

    context.user_data["link"] = link
    context.user_data["nome"] = nome
    context.user_data["prezzo"] = pulisci_prezzo(prezzo)

    if vecchio.upper() == "NO":
        context.user_data["vecchio_prezzo"] = "NO"
    else:
        context.user_data["vecchio_prezzo"] = pulisci_prezzo(vecchio)

    return await mostra_anteprima(
        update,
        context,
    )


# =========================================================
# CALCOLO SCONTO
# =========================================================

def numero_da_prezzo(valore):

    if not valore:
        return None

    valore = (
        valore
        .replace("€", "")
        .replace("EUR", "")
        .replace(" ", "")
        .strip()
    )

    if "," in valore:

        valore = valore.replace(".", "")
        valore = valore.replace(",", ".")

    try:
        return float(valore)

    except ValueError:
        return None


def calcola_sconto(
    prezzo,
    vecchio,
):

    nuovo = numero_da_prezzo(prezzo)
    precedente = numero_da_prezzo(vecchio)

    if (
        nuovo is None
        or precedente is None
        or precedente <= 0
    ):
        return None

    return round(
        (1 - nuovo / precedente)
        * 100
    )


# =========================================================
# TEMPLATE MESSAGGI
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

    # AGGRESSIVO
    if template == "aggressivo":

        testo = (
            "🚨 SUPER OFFERTA AMAZON 🚨\n\n"
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

    # TECH
    if template == "tech":

        testo = (
            "⚡ TECH DEAL\n\n"
            f"📱 {nome}\n\n"
        )

        if vecchio.upper() != "NO":
            testo += f"🏷️ Listino: {vecchio} €\n"

        testo += f"💰 Offerta: {prezzo} €\n"

        if sconto is not None:
            testo += f"📉 -{sconto}%"

        return testo

    # PULITO
    testo = (
        "🔥 OFFERTA AMAZON\n\n"
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

    messaggio = crea_messaggio(
        context
    )

    context.user_data["messaggio"] = messaggio

    link = context.user_data.get(
        "link",
        "",
    )

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
# CONFERMA / PUBBLICAZIONE
# =========================================================

async def conferma(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query

    await query.answer()

    # ANNULLA
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

    # CAMBIA TEMPLATE
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

    # TEMPLATE SELEZIONATO
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

    # PUBBLICA
    if query.data == "pubblica":

        messaggio = context.user_data.get("messaggio")
        link = context.user_data.get("link")
        nome = context.user_data.get("nome")

        if not messaggio or not link:

            await query.edit_message_text(
                "❌ Dati dell'offerta mancanti."
            )

            return ConversationHandler.END

        messaggio_con_link = (
            f"{messaggio}\n\n"
            f"👉 {link}\n\n"
            "⚡ Prezzo e disponibilità possono variare."
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
                "prezzo": context.user_data.get("prezzo"),
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

        righe = [
            "📋 ULTIME OFFERTE\n"
        ]

        for numero, offerta in enumerate(
            ultime_offerte,
            start=1,
        ):

            righe.append(
                f"{numero}. "
                f"{offerta['nome']} "
                f"— {offerta['prezzo']} €"
            )

        testo = "\n".join(righe)

    if update.message:

        await update.message.reply_text(
            testo
        )

    else:

        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            testo
        )


# =========================================================
# TEMPLATE DAL MENU ADMIN
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

    if not await controlla_autorizzazione(update):
        return

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

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Operazione annullata.",
        reply_markup=menu_principale(),
    )

    return ConversationHandler.END


# =========================================================
# AVVIO BOT
# =========================================================

def main():

    inizializza_database()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

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
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_link,
                )
            ],

            DATI_AUTOMATICI: [
                CallbackQueryHandler(
                    conferma_dati_automatici,
                    pattern="^(dati_ok|dati_manual)$",
                )
            ],

            NOME: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_nome,
                )
            ],

            PREZZO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_prezzo,
                )
            ],

            VECCHIO_PREZZO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_vecchio_prezzo,
                )
            ],

            RAPIDO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_rapido,
                )
            ],

            CONFERMA: [
                CallbackQueryHandler(
                    conferma,
                    pattern=(
                        "^(pubblica|"
                        "annulla|"
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


    # =====================================================
    # COMANDI GENERALI
    # =====================================================

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


    # =====================================================
    # ADMIN OFFERTE
    # =====================================================

    app.add_handler(
        CommandHandler(
            "ultime",
            ultime,
        )
    )

    app.add_handler(
        conversazione
    )

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


    # =====================================================
    # CLUB UTENTI
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            mostra_punti,
            pattern="^club_punti$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            invita_amici,
            pattern="^club_invita$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            mostra_premi,
            pattern="^club_premi$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            club_home,
            pattern="^club_home$",
        )
    )


    # =====================================================
    # PREMI
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            richiedi_premio,
            pattern="^premio_(5|10)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_premio_admin,
            pattern=(
                "^(approva|rifiuta)"
                "_premio_[0-9]+$"
            ),
        )
    )


    # =====================================================
    # PANNELLO ADMIN CLUB
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            admin_club_menu,
            pattern="^admin_club$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_club_utenti,
            pattern="^adm_utenti$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_club_utente,
            pattern=r"^adm_user_[0-9]+$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_modifica_punti,
            pattern=r"^adm_pts_[0-9]+_(1|5|m1|m5)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_storico_utente,
            pattern=r"^adm_storico_[0-9]+$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_movimenti,
            pattern="^adm_movimenti$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_inviti,
            pattern="^adm_inviti$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_premi,
            pattern="^adm_premi$",
        )
    )


    print(
        "🤖 Amazon Offer Bot + Club V2 avviato"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
