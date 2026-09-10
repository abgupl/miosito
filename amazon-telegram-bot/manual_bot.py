import os
import asyncio
import sqlite3
import html
import re
import random
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import deque

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from amazon_client import get_items, search_items

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
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
DB_PATH = os.environ.get("CLUB_DB_PATH", "club.db")
ROMA_TZ = ZoneInfo("Europe/Rome")
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "bestprice24h_logo.png"
AMAZON_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "amazon_logo.png"

AUTO_INTERVALLO, AUTO_FASCIA = range(300, 302)

AUTO_CATEGORIE = {
    "elettronica": ("📱 Elettronica", ["offerte elettronica", "cuffie bluetooth", "dispositivi smart home"]),
    "informatica": ("💻 Informatica", ["offerte informatica", "accessori PC", "computer e tablet"]),
    "smartphone": ("📲 Smartphone", ["smartphone in offerta", "accessori smartphone", "caricabatterie powerbank"]),
    "tvaudio": ("📺 TV e audio", ["smart TV in offerta", "soundbar altoparlanti", "cuffie auricolari"]),
    "gaming": ("🎮 Gaming", ["offerte gaming", "accessori gaming", "videogiochi e console"]),
    "casa": ("🏠 Casa e cucina", ["offerte casa e cucina", "accessori cucina", "pulizia casa"]),
    "elettrodomestici": ("🔌 Elettrodomestici", ["piccoli elettrodomestici", "elettrodomestici cucina", "aspirapolvere in offerta"]),
    "persona": ("🧴 Cura personale", ["cura della persona", "rasoi elettrici", "asciugacapelli piastre"]),
    "bellezza": ("💄 Bellezza", ["prodotti bellezza", "skincare in offerta", "profumi e cosmetici"]),
    "sport": ("🏋️ Sport", ["offerte sport fitness", "attrezzatura sportiva", "abbigliamento sportivo"]),
    "faidate": ("🛠 Fai da te", ["offerte fai da te", "utensili elettrici", "attrezzi bricolage"]),
    "giocattoli": ("🧸 Giochi e giocattoli", ["giocattoli in offerta", "giochi da tavolo", "LEGO in offerta"]),
}

AUTO_HASHTAG = {
    "elettronica": "#Elettronica",
    "informatica": "#Informatica",
    "smartphone": "#Smartphone",
    "tvaudio": "#TVeAudio",
    "casa": "#CasaECucina",
    "gaming": "#Gaming",
    "elettrodomestici": "#Elettrodomestici",
    "sport": "#Sport",
    "persona": "#CuraPersonale",
    "bellezza": "#Bellezza",
    "faidate": "#FaiDaTe",
    "giocattoli": "#GiochiEGiocattoli",
}


(
    LINK,
    NOME,
    PREZZO,
    VECCHIO_PREZZO,
    CONFERMA,
    RAPIDO,
    DATI_AUTOMATICI,
    PROGRAMMA_DATA,
    PROGRAMMA_ORA,
    CONFERMA_ORARIO,
) = range(10)

(
    PROG_SELEZIONE,
    PROG_GESTIONE,
    PROG_MODIFICA_MENU,
    PROG_EDIT_NOME,
    PROG_EDIT_PREZZO,
    PROG_EDIT_VECCHIO,
    PROG_EDIT_LINK,
    PROG_EDIT_DATA_ORA,
) = range(100, 108)

(
    FOTO_SCELTA,
    FOTO_ATTESA,
    PROG_IMMAGINE_MENU,
    PROG_IMMAGINE_ATTESA,
) = range(200, 204)


ultime_offerte = deque(maxlen=10)



# =========================================================
# RECAP GIORNALIERO OFFERTE - ORE 22:01
# =========================================================

def inizializza_recap():

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recap_offerte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            link TEXT NOT NULL,
            prezzo TEXT,
            vecchio_prezzo TEXT,
            pubblicata_il TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recap_giorni (
            data TEXT PRIMARY KEY,
            inviato_il TEXT NOT NULL
        )
    """)

    # Campi aggiuntivi per poter reinviare rapidamente i post storici.
    cur.execute("PRAGMA table_info(recap_offerte)")
    colonne_recap = {riga[1] for riga in cur.fetchall()}

    if "messaggio" not in colonne_recap:
        cur.execute("ALTER TABLE recap_offerte ADD COLUMN messaggio TEXT")

    if "foto_file_id" not in colonne_recap:
        cur.execute("ALTER TABLE recap_offerte ADD COLUMN foto_file_id TEXT")

    if "template" not in colonne_recap:
        cur.execute("ALTER TABLE recap_offerte ADD COLUMN template TEXT DEFAULT 'pulito'")

    db.commit()
    db.close()


def salva_offerta_recap(
    nome,
    link,
    prezzo,
    vecchio_prezzo="NO",
    messaggio=None,
    foto_file_id=None,
    template="pulito",
):

    if not nome or not link:
        return

    adesso = datetime.now(ROMA_TZ)

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        INSERT INTO recap_offerte (
            nome,
            link,
            prezzo,
            vecchio_prezzo,
            pubblicata_il,
            messaggio,
            foto_file_id,
            template
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nome,
        link,
        prezzo or "",
        vecchio_prezzo or "NO",
        adesso.isoformat(timespec="seconds"),
        messaggio,
        foto_file_id,
        template or "pulito",
    ))

    db.commit()
    db.close()


def estrai_vecchio_prezzo_da_messaggio(messaggio):

    if not messaggio:
        return "NO"

    match = re.search(
        r"(?:Prima|Listino):\s*([^\n€]+)",
        messaggio,
        flags=re.IGNORECASE,
    )

    if not match:
        return "NO"

    valore = match.group(1).strip()
    return valore or "NO"


def offerte_recap_di_oggi():

    oggi = datetime.now(ROMA_TZ).date().isoformat()

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            nome,
            link,
            prezzo,
            vecchio_prezzo,
            pubblicata_il
        FROM recap_offerte
        WHERE substr(pubblicata_il, 1, 10) = ?
        ORDER BY pubblicata_il DESC
    """, (oggi,))

    risultati = cur.fetchall()
    db.close()

    return risultati


def recap_gia_inviato(oggi):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute(
        "SELECT 1 FROM recap_giorni WHERE data = ?",
        (oggi,),
    )

    trovato = cur.fetchone() is not None
    db.close()

    return trovato


def segna_recap_inviato(oggi):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO recap_giorni (data, inviato_il)
        VALUES (?, ?)
    """, (
        oggi,
        datetime.now(ROMA_TZ).isoformat(timespec="seconds"),
    ))

    db.commit()
    db.close()


def crea_righe_recap(offerte):

    righe = []

    for nome, link, prezzo, vecchio, _ in offerte:

        nome_breve = accorcia_nome_articolo(nome)
        nome_html = html.escape(str(nome_breve))
        link_html = html.escape(str(link), quote=True)
        prezzo_html = html.escape(str(prezzo or "—"))

        if vecchio and str(vecchio).upper() != "NO":
            vecchio_html = html.escape(str(vecchio))
        else:
            vecchio_html = "—"

        righe.append(
            f'🛒 <a href="{link_html}">{nome_html}</a> | '
            f'❌ {vecchio_html}€ → ✅ {prezzo_html}€'
        )

    return righe


async def invia_recap_giornaliero(bot):

    offerte = offerte_recap_di_oggi()

    if not offerte:
        return False

    righe = crea_righe_recap(offerte)

    intestazione = (
        "🔥 <b>RECAP OFFERTE DI OGGI</b>\n\n"
    )

    club_footer = (
        "\n\n────────────────\n"
        '🎁 <a href="https://t.me/BestPrice24h_bot">'
        "<b>Entra nel Club</b></a>"
        " → invita amici e accumula punti!\n"
        "👥 Invita amici • ⭐ Accumula punti • 🎁 Ottieni premi"
    )

    messaggi = []
    corrente = intestazione

    for riga in righe:

        candidato = corrente + riga + "\n\n"

        if (
            len(candidato) + len(club_footer) > 3900
            and corrente != intestazione
        ):
            messaggi.append(corrente.rstrip())
            corrente = intestazione + riga + "\n\n"
        else:
            corrente = candidato

    if corrente.strip():
        messaggi.append(
            corrente.rstrip() + club_footer
        )

    for testo in messaggi:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=testo,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    return True


async def controlla_recap(app):

    while True:

        try:
            adesso = datetime.now(ROMA_TZ)
            oggi = adesso.date().isoformat()

            orario_recap_raggiunto = (
                adesso.hour > 22
                or (adesso.hour == 22 and adesso.minute >= 1)
            )

            if (
                orario_recap_raggiunto
                and not recap_gia_inviato(oggi)
            ):
                inviato = await invia_recap_giornaliero(app.bot)

                # Segniamo la giornata solo se c'erano offerte.
                if inviato:
                    segna_recap_inviato(oggi)

        except Exception as errore:
            print(f"Errore recap giornaliero: {errore}")

        await asyncio.sleep(30)


# =========================================================
# PROGRAMMAZIONE INVIO OFFERTE
# =========================================================


def salva_foto_programmazione(
    programmazione_id,
    foto_file_id,
):

    if not foto_file_id:
        return

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET foto_file_id = ?
        WHERE id = ?
    """, (
        foto_file_id,
        programmazione_id,
    ))

    db.commit()
    db.close()



def inizializza_programmazioni():

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS programmazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            messaggio TEXT NOT NULL,
            link TEXT NOT NULL,
            prezzo TEXT,
            vecchio_prezzo TEXT DEFAULT 'NO',
            template TEXT DEFAULT 'pulito',
            foto_file_id TEXT,
            invio_previsto TEXT NOT NULL,
            stato TEXT DEFAULT 'attesa',
            data_creazione TEXT NOT NULL
        )
    """)

    # Migrazione automatica per database già esistenti.
    cur.execute("PRAGMA table_info(programmazioni)")
    colonne = {
        riga[1]
        for riga in cur.fetchall()
    }

    if "vecchio_prezzo" not in colonne:
        cur.execute(
            "ALTER TABLE programmazioni "
            "ADD COLUMN vecchio_prezzo TEXT DEFAULT 'NO'"
        )

    if "template" not in colonne:
        cur.execute(
            "ALTER TABLE programmazioni "
            "ADD COLUMN template TEXT DEFAULT 'pulito'"
        )

    if "foto_file_id" not in colonne:
        cur.execute(
            "ALTER TABLE programmazioni "
            "ADD COLUMN foto_file_id TEXT"
        )

    db.commit()
    db.close()


def salva_programmazione(
    nome,
    messaggio,
    link,
    prezzo,
    invio_previsto_locale,
):

    # Salviamo in UTC per evitare problemi
    # con ora legale/solare.
    invio_previsto_utc = (
        invio_previsto_locale
        .astimezone(timezone.utc)
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    vecchio_prezzo = (
        estrai_vecchio_prezzo_da_messaggio(
            messaggio
        )
    )

    if messaggio.startswith(
        "🚨 SUPER OFFERTA AMAZON"
    ):
        template = "aggressivo"

    elif messaggio.startswith(
        "⚡ TECH DEAL"
    ):
        template = "tech"

    else:
        template = "pulito"

    cur.execute("""
        INSERT INTO programmazioni (
            nome,
            messaggio,
            link,
            prezzo,
            vecchio_prezzo,
            template,
            foto_file_id,
            invio_previsto,
            stato,
            data_creazione
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'attesa', ?)
    """, (
        nome,
        messaggio,
        link,
        prezzo,
        vecchio_prezzo,
        template,
        None,
        invio_previsto_utc.isoformat(
            timespec="seconds"
        ),
        datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        ),
    ))

    programmazione_id = cur.lastrowid

    db.commit()
    db.close()

    return (
        programmazione_id,
        invio_previsto_locale
    )


async def invia_offerta_programmata(
    bot,
    programmazione,
):

    (
        programmazione_id,
        nome,
        messaggio,
        link,
        prezzo,
        foto_file_id,
    ) = programmazione

    messaggio_con_link = (
        f"{messaggio}\n\n"
        f"👉 {link}\n\n"
        "⚡ Prezzo e disponibilità "
        "possono variare."
    )

    bottone_offerta = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎁 CLUB",
                    url="https://t.me/BestPrice24h_bot",
                ),
                InlineKeyboardButton(
                    "🛒 APRI",
                    url=link,
                )
            ]
        ]
    )

    if foto_file_id:
        await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=foto_file_id,
            caption=messaggio_con_link,
            reply_markup=bottone_offerta,
        )
    else:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=messaggio_con_link,
            reply_markup=bottone_offerta,
        )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET stato = 'inviata'
        WHERE id = ?
    """, (
        programmazione_id,
    ))

    db.commit()
    db.close()

    ultime_offerte.appendleft(
        {
            "nome": nome,
            "link": link,
            "prezzo": prezzo,
        }
    )

    salva_offerta_recap(
        nome,
        link,
        prezzo,
        estrai_vecchio_prezzo_da_messaggio(messaggio),
        messaggio=messaggio,
        foto_file_id=foto_file_id,
    )


async def controlla_programmazioni(app):

    while True:

        try:

            db = sqlite3.connect(DB_PATH)
            cur = db.cursor()

            cur.execute("""
                SELECT
                    id,
                    nome,
                    messaggio,
                    link,
                    prezzo,
                    foto_file_id
                FROM programmazioni
                WHERE stato = 'attesa'
                  AND invio_previsto <= ?
                ORDER BY invio_previsto ASC
            """, (
                datetime.now(
                    timezone.utc
                ).isoformat(
                    timespec="seconds"
                ),
            ))

            programmazioni = cur.fetchall()

            db.close()

            for programmazione in programmazioni:

                try:

                    await invia_offerta_programmata(
                        app.bot,
                        programmazione,
                    )

                except Exception as errore:

                    print(
                        "Errore invio programmato: "
                        f"{errore}"
                    )

        except Exception as errore:

            print(
                "Errore controllo programmazioni: "
                f"{errore}"
            )

        await asyncio.sleep(30)


async def avvia_programmazioni(app):

    app.create_task(
        controlla_programmazioni(app)
    )

    app.create_task(
        controlla_recap(app)
    )

    app.create_task(
        controlla_invii_automatici(app)
    )

    app.create_task(
        controlla_offerte_terminate(app)
    )


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
# INVIO AUTOMATICO - CONFIGURAZIONE
# =========================================================

def inizializza_automazione():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS configurazione_automatica (
            chiave TEXT PRIMARY KEY,
            valore TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categorie_automatiche (
            categoria TEXT PRIMARY KEY
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invii_automatici (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asin TEXT,
            nome TEXT,
            link TEXT,
            categoria TEXT,
            sconto INTEGER,
            slot_data TEXT NOT NULL,
            slot_ora TEXT NOT NULL,
            stato TEXT NOT NULL,
            creato_il TEXT NOT NULL,
            UNIQUE(slot_data, slot_ora)
        )
    """)
    cur.execute("PRAGMA table_info(invii_automatici)")
    colonne_invii = {riga[1] for riga in cur.fetchall()}
    nuove_colonne = {
        "telegram_message_id": "INTEGER",
        "soglia_sconto": "INTEGER",
        "verifiche_fallite": "INTEGER DEFAULT 0",
        "terminata_il": "TEXT",
        "deal_end_time": "TEXT",
        "ultima_verifica": "TEXT",
        "telegram_photo_file_id": "TEXT",
    }
    for colonna, definizione in nuove_colonne.items():
        if colonna not in colonne_invii:
            cur.execute(f"ALTER TABLE invii_automatici ADD COLUMN {colonna} {definizione}")
    defaults = {
        "attiva": "0",
        "intervallo_minuti": "120",
        "ora_inizio": "09:00",
        "ora_fine": "21:00",
        "prossimo_invio": "",
        "sconto_minimo": "20",
    }
    for chiave, valore in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)",
            (chiave, valore),
        )
    versione = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = 'versione_config'"
    ).fetchone()
    if not versione or versione[0] != "3":
        cur.execute(
            "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES ('attiva', '0')"
        )
        cur.execute(
            "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES ('versione_config', '3')"
        )
    db.commit()
    db.close()


def leggi_config_automatica():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute("SELECT chiave, valore FROM configurazione_automatica")
    valori = dict(cur.fetchall())
    cur.execute("SELECT categoria FROM categorie_automatiche ORDER BY categoria")
    categorie = [riga[0] for riga in cur.fetchall()]
    db.close()
    return {
        "attiva": valori.get("attiva", "0") == "1",
        "intervallo_minuti": int(valori.get("intervallo_minuti", "120")),
        "ora_inizio": valori.get("ora_inizio", "09:00"),
        "ora_fine": valori.get("ora_fine", "21:00"),
        "prossimo_invio": valori.get("prossimo_invio", ""),
        "sconto_minimo": int(valori.get("sconto_minimo", "20")),
        "categorie": categorie,
    }


def salva_config_automatica(chiave, valore):
    db = sqlite3.connect(DB_PATH)
    db.execute(
        "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)",
        (chiave, str(valore)),
    )
    db.commit()
    db.close()


def tastiera_automazione(configurazione):
    stato = "🟢 ATTIVA" if configurazione["attiva"] else "🔴 DISATTIVATA"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"STATO: {stato}", callback_data="auto_toggle")],
        [InlineKeyboardButton(
            f"⏱ OGNI {configurazione['intervallo_minuti']} MINUTI",
            callback_data="auto_intervallo",
        )],
        [InlineKeyboardButton(
            f"🕒 DALLE {configurazione['ora_inizio']} ALLE {configurazione['ora_fine']}",
            callback_data="auto_fascia",
        )],
        [InlineKeyboardButton("🗂 CATEGORIE PRODOTTI", callback_data="auto_categorie")],
        [InlineKeyboardButton(
            f"📉 SCONTO MINIMO: {configurazione['sconto_minimo']}%",
            callback_data="auto_sconto",
        )],
        [InlineKeyboardButton("🧪 TESTA RICERCA", callback_data="auto_test")],
        [InlineKeyboardButton("⬅️ TORNA AL MENU PRINCIPALE", callback_data="menu_admin")],
    ])


def testo_automazione(configurazione):
    categorie = [AUTO_CATEGORIE[x][0] for x in configurazione["categorie"] if x in AUTO_CATEGORIE]
    return (
        "🤖 INVIO AUTOMATICO\n\n"
        f"Stato: {'🟢 Attivo' if configurazione['attiva'] else '🔴 Disattivato'}\n"
        f"Intervallo: {configurazione['intervallo_minuti']} minuti\n"
        f"Orario: {configurazione['ora_inizio']}–{configurazione['ora_fine']}\n"
        f"Sconto minimo: {configurazione['sconto_minimo']}%\n"
        f"Categorie: {', '.join(categorie) if categorie else 'nessuna'}"
    )


async def menu_automazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    await aggiorna_menu_automazione(query)


async def aggiorna_menu_automazione(query):
    configurazione = leggi_config_automatica()
    await query.edit_message_text(
        testo_automazione(configurazione),
        reply_markup=tastiera_automazione(configurazione),
    )


async def mostra_categorie_automatiche(query):
    selezionate = set(leggi_config_automatica()["categorie"])
    tastiera = []
    for codice, (etichetta, _) in AUTO_CATEGORIE.items():
        segno = "✅" if codice in selezionate else "▫️"
        tastiera.append([
            InlineKeyboardButton(
                f"{segno} {etichetta.upper()}",
                callback_data=f"auto_cat_{codice}",
            )
        ])
    tastiera.append([InlineKeyboardButton("✅ FATTO", callback_data="auto_menu")])
    await query.edit_message_text(
        "🗂 Seleziona le categorie da pubblicare:",
        reply_markup=InlineKeyboardMarkup(tastiera),
    )


async def gestisci_automazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    azione = query.data
    configurazione = leggi_config_automatica()

    if azione == "auto_toggle":
        if configurazione["attiva"]:
            salva_config_automatica("attiva", 0)
            salva_config_automatica("prossimo_invio", "")
            return await aggiorna_menu_automazione(query)

        if not configurazione["categorie"]:
            await query.message.reply_text("❌ Seleziona almeno una categoria.")
            return

        adesso = datetime.now(ROMA_TZ)
        salva_config_automatica("attiva", 1)
        configurazione = leggi_config_automatica()

        if _dentro_fascia_automatica(configurazione, adesso):
            prossimo = _calcola_prossimo_invio(configurazione, adesso)
            salva_config_automatica("prossimo_invio", prossimo.isoformat(timespec="seconds"))
            await aggiorna_menu_automazione(query)
            await query.message.reply_text("🚀 Automazione attivata. Cerco subito la prima offerta…")
            await esegui_slot_automatico(
                context.application,
                configurazione,
                adesso.date().isoformat(),
                adesso.strftime("%H:%M"),
            )
            return

        prossimo = _prossimo_inizio_fascia(configurazione, adesso)
        salva_config_automatica("prossimo_invio", prossimo.isoformat(timespec="seconds"))
        await aggiorna_menu_automazione(query)
        await query.message.reply_text(
            f"✅ Automazione attivata. Il primo tentativo partirà alle {prossimo.strftime('%H:%M')}."
        )
        return

    if azione == "auto_sconto":
        valori = (10, 15, 20, 25, 30, 40, 50)
        tastiera = [
            [InlineKeyboardButton(f"{v}%", callback_data=f"auto_disc_{v}") for v in valori[:4]],
            [InlineKeyboardButton(f"{v}%", callback_data=f"auto_disc_{v}") for v in valori[4:]],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data="auto_menu")],
        ]
        await query.edit_message_text("📉 Seleziona lo sconto minimo:", reply_markup=InlineKeyboardMarkup(tastiera))
        return

    if azione.startswith("auto_disc_"):
        salva_config_automatica("sconto_minimo", int(azione.rsplit("_", 1)[1]))
        salva_config_automatica("attiva", 0)
        return await aggiorna_menu_automazione(query)

    if azione == "auto_categorie":
        return await mostra_categorie_automatiche(query)

    if azione.startswith("auto_cat_"):
        categoria = azione.replace("auto_cat_", "", 1)
        if categoria not in AUTO_CATEGORIE:
            return
        db = sqlite3.connect(DB_PATH)
        cur = db.cursor()
        cur.execute("SELECT 1 FROM categorie_automatiche WHERE categoria = ?", (categoria,))
        if cur.fetchone():
            cur.execute("DELETE FROM categorie_automatiche WHERE categoria = ?", (categoria,))
        else:
            cur.execute("INSERT INTO categorie_automatiche (categoria) VALUES (?)", (categoria,))
        db.commit()
        db.close()
        salva_config_automatica("attiva", 0)
        return await mostra_categorie_automatiche(query)


async def richiedi_intervallo_automatico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⏱ Intervallo tra i post\n\n"
        "Scrivi quanti minuti devono passare tra un post e l’altro.\n\n"
        "Esempio: 120\n\n"
        "Il minimo consentito è 29 minuti."
    )
    return AUTO_INTERVALLO


async def ricevi_intervallo_automatico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    try:
        minuti = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Scrivi soltanto il numero dei minuti, per esempio 120.")
        return AUTO_INTERVALLO
    if minuti < 29 or minuti > 1440:
        await update.message.reply_text("❌ Inserisci un valore tra 29 e 1440 minuti.")
        return AUTO_INTERVALLO
    salva_config_automatica("intervallo_minuti", minuti)
    salva_config_automatica("attiva", 0)
    configurazione = leggi_config_automatica()
    await update.message.reply_text(
        f"✅ Intervallo salvato: {minuti} minuti.\n\n"
        "L’automazione resta disattivata finché non la riattivi.",
        reply_markup=tastiera_automazione(configurazione),
    )
    return ConversationHandler.END


async def richiedi_fascia_automatica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🕒 Orario di attività\n\n"
        "Scrivi l’orario di inizio e quello di fine separati da un trattino.\n\n"
        "Esempio: 09:00-21:00\n\n"
        "Alle 21:00 il bot si fermerà."
    )
    return AUTO_FASCIA


async def ricevi_fascia_automatica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    testo = update.message.text.strip().replace("–", "-").replace("—", "-")
    parti = [x.strip() for x in testo.split("-")]
    if len(parti) != 2:
        await update.message.reply_text("❌ Usa il formato 09:00-21:00.")
        return AUTO_FASCIA
    try:
        inizio = datetime.strptime(parti[0], "%H:%M")
        fine = datetime.strptime(parti[1], "%H:%M")
    except ValueError:
        await update.message.reply_text("❌ Orario non corretto. Usa il formato 09:00-21:00.")
        return AUTO_FASCIA
    inizio_minuti = inizio.hour * 60 + inizio.minute
    fine_minuti = fine.hour * 60 + fine.minute
    if fine_minuti <= inizio_minuti:
        await update.message.reply_text("❌ L’orario finale deve essere successivo a quello iniziale.")
        return AUTO_FASCIA
    ora_inizio = inizio.strftime("%H:%M")
    ora_fine = fine.strftime("%H:%M")
    salva_config_automatica("ora_inizio", ora_inizio)
    salva_config_automatica("ora_fine", ora_fine)
    salva_config_automatica("attiva", 0)
    configurazione = leggi_config_automatica()
    await update.message.reply_text(
        f"✅ Orario salvato: dalle {ora_inizio} alle {ora_fine}.\n\n"
        f"Alle {ora_fine} il bot si fermerà.",
        reply_markup=tastiera_automazione(configurazione),
    )
    return ConversationHandler.END


def estrai_prodotto_creators(item):
    """Converte un Item delle Creators API nel formato usato dal bot."""
    try:
        titolo = item.item_info.title.display_value
        immagine = item.images.primary.large.url
        link = item.detail_page_url
        asin = item.asin

        offerte = item.offers_v2.listings
        if not offerte:
            return None

        offerta = offerte[0]
        prezzo_api = offerta.price
        denaro = prezzo_api.money
        if not denaro or denaro.amount is None:
            return None

        prezzo_valore = float(denaro.amount)
        prezzo = denaro.display_amount or f"{prezzo_valore:.2f} €"
        vecchio_prezzo = None
        vecchio_valore = None

        base = prezzo_api.saving_basis
        if base and base.money and base.money.amount is not None:
            vecchio_valore = float(base.money.amount)
            vecchio_prezzo = base.money.display_amount or f"{vecchio_valore:.2f} €"

        sconto = 0
        if prezzo_api.savings and prezzo_api.savings.percentage is not None:
            sconto = round(float(prezzo_api.savings.percentage))
        elif vecchio_valore and vecchio_valore > prezzo_valore:
            sconto = round((1 - prezzo_valore / vecchio_valore) * 100)

        if not all((titolo, immagine, link, asin)):
            return None

        venditore = None
        if offerta.merchant_info and offerta.merchant_info.name:
            venditore = offerta.merchant_info.name.strip()

        deal_end_time = None
        if offerta.deal_details and offerta.deal_details.end_time:
            deal_end_time = offerta.deal_details.end_time

        return {
            "asin": asin,
            "nome": titolo,
            "prezzo": prezzo,
            "prezzo_valore": prezzo_valore,
            "vecchio_prezzo": vecchio_prezzo,
            "vecchio_valore": vecchio_valore,
            "sconto": sconto,
            "immagine": immagine,
            "link": link,
            "venditore": venditore,
            "deal_end_time": deal_end_time,
        }
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def riga_venditore_categoria(prodotto, categoria):
    hashtag = AUTO_HASHTAG.get(categoria, "#OfferteAmazon")
    venditore = prodotto.get("venditore")
    if venditore and "amazon" in venditore.lower():
        return f"Venduto e spedito da <i>Amazon</i> - Categoria: {hashtag}"
    return f"Categoria: {hashtag}"


def crea_immagine_brandizzata(image_url):
    """Scarica la foto Amazon e aggiunge cornice e logo BestPrice24h."""
    risposta = requests.get(image_url, timeout=20)
    risposta.raise_for_status()

    prodotto = Image.open(BytesIO(risposta.content)).convert("RGB")
    canvas = Image.new("RGB", (1080, 1080), "white")

    # Margine bianco uniforme del 16% su tutti i lati del prodotto.
    area_prodotto = (734, 734)
    margine_prodotto = 173
    foto = ImageOps.contain(
        prodotto,
        area_prodotto,
        method=Image.Resampling.LANCZOS,
    )
    posizione_foto = (
        margine_prodotto + (area_prodotto[0] - foto.width) // 2,
        margine_prodotto + (area_prodotto[1] - foto.height) // 2,
    )
    canvas.paste(foto, posizione_foto)

    # Cornice rossa sottile, profilo nero e nessuna ombra esterna.
    disegno = ImageDraw.Draw(canvas)
    disegno.rounded_rectangle(
        (8, 8, 1072, 1072), radius=40, outline="#F20D18", width=18
    )
    disegno.rounded_rectangle(
        (26, 26, 1054, 1054), radius=22, outline="#171717", width=3
    )

    if not LOGO_PATH.exists():
        raise FileNotFoundError(f"Logo non trovato: {LOGO_PATH}")

    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo = ImageOps.contain(logo, (195, 170), Image.Resampling.LANCZOS)
    # Trasparenza molto leggera: il logo conserva circa il 92% di opacità.
    alpha_logo = logo.getchannel("A").point(lambda valore: valore * 150 // 255)
    logo.putalpha(alpha_logo)
    # Margine del logo: 10 px dal profilo nero, in alto e a destra.
    posizione_logo = (1044 - logo.width, 36)

    # Il logo è opaco; solo una piccola ombra ne migliora la leggibilità.
    alpha_ombra = logo.getchannel("A").point(lambda valore: valore * 90 // 255)
    sagoma_nera = Image.new("RGBA", logo.size, (0, 0, 0, 0))
    sagoma_nera.putalpha(alpha_ombra)
    ombra = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ombra.paste(
        sagoma_nera,
        (posizione_logo[0] + 5, posizione_logo[1] + 6),
        sagoma_nera,
    )
    ombra = ombra.filter(ImageFilter.GaussianBlur(6))

    canvas = Image.alpha_composite(canvas.convert("RGBA"), ombra)
    canvas.alpha_composite(logo, posizione_logo)

    # Logo Amazon originale, centrato nel margine bianco inferiore.
    if AMAZON_LOGO_PATH.exists():
        logo_amazon = Image.open(AMAZON_LOGO_PATH).convert("RGBA")
        # Rende trasparente soltanto lo sfondo bianco del file fornito.
        pixel = []
        for rosso, verde, blu, alpha in logo_amazon.getdata():
            if rosso >= 245 and verde >= 245 and blu >= 245:
                pixel.append((rosso, verde, blu, 0))
            else:
                pixel.append((rosso, verde, blu, alpha))
        logo_amazon.putdata(pixel)
        logo_amazon = ImageOps.contain(
            logo_amazon,
            (140, 60),
            Image.Resampling.LANCZOS,
        )
        posizione_amazon = (
            (1080 - logo_amazon.width) // 2,
            1010 - logo_amazon.height,
        )
        canvas.alpha_composite(logo_amazon, posizione_amazon)

    output = BytesIO()
    output.name = "offerta_bestprice24h.jpg"
    canvas.convert("RGB").save(
        output,
        format="JPEG",
        quality=93,
        optimize=True,
    )
    output.seek(0)
    return output


async def prepara_foto_automatica(image_url):
    """Crea la grafica senza bloccare il bot; in errore usa la foto originale."""
    try:
        return await asyncio.to_thread(crea_immagine_brandizzata, image_url)
    except Exception as errore:
        print(f"Impossibile creare immagine brandizzata: {errore}")
        return image_url


def _font_terminata(dimensione):
    percorsi = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    )
    for percorso in percorsi:
        try:
            return ImageFont.truetype(percorso, dimensione)
        except OSError:
            continue
    return ImageFont.load_default()


def crea_immagine_terminata(dati_immagine):
    """Crea la versione grigia della foto già pubblicata."""
    originale = Image.open(BytesIO(bytes(dati_immagine))).convert("RGBA")
    immagine = ImageOps.grayscale(originale).convert("RGBA")

    # Mantiene riconoscibile la cornice BestPrice24h.
    disegno = ImageDraw.Draw(immagine, "RGBA")
    disegno.rounded_rectangle(
        (8, 8, 1072, 1072), radius=40, outline="#F20D18", width=18
    )
    disegno.rounded_rectangle(
        (26, 26, 1054, 1054), radius=22, outline="#171717", width=3
    )

    # Ripristina a colori il logo BestPrice24h.
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo = ImageOps.contain(logo, (195, 170), Image.Resampling.LANCZOS)
        alpha_logo = logo.getchannel("A").point(lambda valore: valore * 235 // 255)
        logo.putalpha(alpha_logo)
        immagine.alpha_composite(logo, (1044 - logo.width, 36))

    # Fascia chiara e scritta rossa centrale.
    fascia = Image.new("RGBA", immagine.size, (0, 0, 0, 0))
    ImageDraw.Draw(fascia).rectangle((35, 430, 1045, 650), fill=(255, 255, 255, 210))
    immagine = Image.alpha_composite(immagine, fascia)
    disegno = ImageDraw.Draw(immagine)
    testo = "OFFERTA TERMINATA"
    dimensione = 82
    font = _font_terminata(dimensione)
    while disegno.textbbox((0, 0), testo, font=font)[2] > 930 and dimensione > 40:
        dimensione -= 4
        font = _font_terminata(dimensione)
    riquadro = disegno.textbbox((0, 0), testo, font=font, stroke_width=2)
    larghezza = riquadro[2] - riquadro[0]
    altezza = riquadro[3] - riquadro[1]
    posizione = ((1080 - larghezza) // 2, (1080 - altezza) // 2 - riquadro[1])
    disegno.text(
        posizione,
        testo,
        font=font,
        fill="#E30613",
        stroke_width=2,
        stroke_fill="white",
    )

    output = BytesIO()
    output.name = "offerta_terminata.jpg"
    immagine.convert("RGB").save(output, "JPEG", quality=93, optimize=True)
    output.seek(0)
    return output


async def testa_ricerca_automatica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    configurazione = leggi_config_automatica()
    if not configurazione["categorie"]:
        await query.message.reply_text("❌ Prima seleziona almeno una categoria.")
        return

    categoria = random.choice(configurazione["categorie"])
    etichetta, termini = AUTO_CATEGORIE[categoria]
    termine = random.choice(termini)
    attesa = await query.message.reply_text(
        f"🔎 Cerco una prova in {etichetta}…\n"
        f"Sconto minimo richiesto: {configurazione['sconto_minimo']}%"
    )

    try:
        items = await asyncio.to_thread(search_items, termine, "All", 10)
        prodotti = []
        for item in items:
            prodotto = estrai_prodotto_creators(item)
            if prodotto and prodotto["sconto"] >= configurazione["sconto_minimo"]:
                prodotti.append(prodotto)

        if not prodotti:
            await attesa.edit_text(
                "ℹ️ Collegamento riuscito, ma la ricerca non ha trovato prodotti "
                f"con almeno il {configurazione['sconto_minimo']}% di sconto.\n\n"
                "Nessun post è stato pubblicato."
            )
            return

        prodotto = max(prodotti, key=lambda x: x["sconto"])
        prodotto["categoria"] = categoria
        await attesa.delete()
        tipo_offerta = "🚨 ERRORE PREZZO" if prodotto["sconto"] > 40 else "🔥 OFFERTA AMAZON"
        vecchio = (
            f"\n❌ Prima: <s>{html.escape(prodotto['vecchio_prezzo'])}</s>"
            if prodotto["vecchio_prezzo"] else ""
        )
        testo = (
            f"🧪 <b>ANTEPRIMA TEST — {tipo_offerta}</b>\n\n"
            f"🛒 {html.escape(prodotto['nome'])}\n\n"
            f"💥 Sconto: <b>-{prodotto['sconto']}%</b>"
            f"{vecchio}\n"
            f"✅ Ora: <b>{html.escape(prodotto['prezzo'])}</b>\n\n"
            f"{riga_venditore_categoria(prodotto, categoria)}\n\n"
            f"👉 <a href=\"{html.escape(prodotto['link'], quote=True)}\">Scopri l’offerta su Amazon</a>\n\n"
            "Anteprima non pubblicata"
        )
        tastiera = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 APRI", url=prodotto["link"]),
        ]])
        foto = await prepara_foto_automatica(prodotto["immagine"])
        await query.message.reply_photo(
            photo=foto,
            caption=testo,
            parse_mode="HTML",
            reply_markup=tastiera,
        )
    except Exception as errore:
        print(f"Errore test Creators API: {errore}")
        await attesa.edit_text(
            "❌ Il test delle Creator API non è riuscito.\n\n"
            f"Dettaglio tecnico: {html.escape(str(errore))[:900]}\n\n"
            "Nessun post è stato pubblicato.",
            parse_mode="HTML",
        )


# =========================================================
# INVIO AUTOMATICO - MOTORE
# =========================================================

def _slot_automatico_gia_gestito(data_slot, ora_slot):
    db = sqlite3.connect(DB_PATH)
    riga = db.execute(
        "SELECT stato FROM invii_automatici WHERE slot_data = ? AND slot_ora = ?",
        (data_slot, ora_slot),
    ).fetchone()
    db.close()
    return bool(riga)


def _prenota_slot_automatico(data_slot, ora_slot, categoria):
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute(
            """
            INSERT INTO invii_automatici (
                categoria, slot_data, slot_ora, stato, creato_il
            ) VALUES (?, ?, ?, 'ricerca', ?)
            """,
            (
                categoria,
                data_slot,
                ora_slot,
                datetime.now(ROMA_TZ).isoformat(timespec="seconds"),
            ),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        db.close()


def _aggiorna_slot_automatico(
    data_slot,
    ora_slot,
    stato,
    prodotto=None,
    telegram_message_id=None,
    telegram_photo_file_id=None,
    soglia_sconto=None,
    deal_end_time=None,
):
    prodotto = prodotto or {}
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        UPDATE invii_automatici
        SET stato = ?, asin = ?, nome = ?, link = ?, sconto = ?,
            telegram_message_id = COALESCE(?, telegram_message_id),
            telegram_photo_file_id = COALESCE(?, telegram_photo_file_id),
            soglia_sconto = COALESCE(?, soglia_sconto),
            deal_end_time = COALESCE(?, deal_end_time),
            ultima_verifica = CASE
                WHEN ? = 'pubblicata' THEN COALESCE(ultima_verifica, ?)
                ELSE ultima_verifica
            END
        WHERE slot_data = ? AND slot_ora = ?
        """,
        (
            stato,
            prodotto.get("asin"),
            prodotto.get("nome"),
            prodotto.get("link"),
            prodotto.get("sconto"),
            telegram_message_id,
            telegram_photo_file_id,
            soglia_sconto,
            deal_end_time,
            stato,
            datetime.now(ROMA_TZ).isoformat(timespec="seconds"),
            data_slot,
            ora_slot,
        ),
    )
    db.commit()
    db.close()


def _asin_gia_pubblicato(asin):
    if not asin:
        return True
    db = sqlite3.connect(DB_PATH)
    riga = db.execute(
        "SELECT 1 FROM invii_automatici WHERE asin = ? AND stato = 'pubblicata' LIMIT 1",
        (asin,),
    ).fetchone()
    db.close()
    return bool(riga)


def _numero_slot_del_giorno(data_slot):
    db = sqlite3.connect(DB_PATH)
    numero = db.execute(
        "SELECT COUNT(*) FROM invii_automatici WHERE slot_data = ?",
        (data_slot,),
    ).fetchone()[0]
    db.close()
    return numero


def _prezzo_italiano(valore):
    return f"{float(valore):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


async def _notifica_admin_automazione(bot, testo):
    if not ADMIN_ID:
        return
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=testo)
    except Exception as errore:
        print(f"Errore notifica automazione: {errore}")


async def cerca_offerta_automatica(configurazione, categoria_iniziale):
    categorie = list(configurazione["categorie"])
    if categoria_iniziale in categorie:
        indice = categorie.index(categoria_iniziale)
        categorie = categorie[indice:] + categorie[:indice]

    tentativi = []
    for numero in range(3):
        categoria = categorie[numero % len(categorie)]
        termini = AUTO_CATEGORIE[categoria][1]
        termine = termini[numero % len(termini)]
        tentativi.append((categoria, termine))

    candidati = []
    for numero, (categoria, termine) in enumerate(tentativi, start=1):
        print(f"Ricerca automatica {numero}/3: {categoria} - {termine}")
        try:
            items = await asyncio.to_thread(search_items, termine, "All", 10)
            for item in items:
                prodotto = estrai_prodotto_creators(item)
                if not prodotto:
                    continue
                if prodotto["sconto"] < configurazione["sconto_minimo"]:
                    continue
                if _asin_gia_pubblicato(prodotto["asin"]):
                    continue
                prodotto["categoria"] = categoria
                candidati.append(prodotto)
        except Exception as errore:
            print(f"Errore tentativo automatico {numero}: {errore}")
        if numero < len(tentativi):
            await asyncio.sleep(1.2)

    if not candidati:
        return None
    candidati.sort(key=lambda x: (x["sconto"], -x["prezzo_valore"]), reverse=True)
    return candidati[0]


async def pubblica_offerta_automatica(bot, prodotto):
    nome = prodotto["nome"]
    prezzo_numero = _prezzo_italiano(prodotto["prezzo_valore"])
    vecchio_numero = None
    if prodotto["vecchio_prezzo"]:
        base = prodotto.get("vecchio_valore")
        if base is not None:
            vecchio_numero = _prezzo_italiano(base)

    prima = (
        f"\n❌ Prima: <s>{html.escape(prodotto['vecchio_prezzo'])}</s>"
        if prodotto["vecchio_prezzo"] else ""
    )
    tipo_offerta = "🚨 ERRORE PREZZO" if prodotto["sconto"] > 40 else "🔥 OFFERTA AMAZON"
    link_html = html.escape(prodotto["link"], quote=True)
    riga_venditore = riga_venditore_categoria(prodotto, prodotto.get("categoria"))
    messaggio = (
        f"<b>{tipo_offerta}</b>\n\n"
        f"🛒 {html.escape(nome)}\n\n"
        f"💥 Sconto: <b>-{prodotto['sconto']}%</b>"
        f"{prima}\n"
        f"✅ Ora: <b>{html.escape(prodotto['prezzo'])}</b>\n\n"
        f"{riga_venditore}\n\n"
        f"👉 <a href=\"{link_html}\">Scopri l’offerta su Amazon</a>\n\n"
        "⚡ Prezzo e disponibilità possono variare."
    )
    tastiera = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 CLUB", url="https://t.me/BestPrice24h_bot"),
        InlineKeyboardButton("🛒 APRI", url=prodotto["link"]),
    ]])
    foto = await prepara_foto_automatica(prodotto["immagine"])
    messaggio_telegram = await bot.send_photo(
        chat_id=CHANNEL_ID,
        photo=foto,
        caption=messaggio,
        parse_mode="HTML",
        reply_markup=tastiera,
    )
    ultime_offerte.appendleft({
        "nome": nome,
        "link": prodotto["link"],
        "prezzo": prezzo_numero,
    })
    foto_telegram = prodotto["immagine"]
    if messaggio_telegram.photo:
        foto_telegram = messaggio_telegram.photo[-1].file_id
    salva_offerta_recap(
        nome,
        prodotto["link"],
        prezzo_numero,
        vecchio_numero or "NO",
        messaggio=messaggio,
        foto_file_id=foto_telegram,
        template="automatico",
    )
    return messaggio_telegram.message_id, foto_telegram


async def esegui_slot_automatico(app, configurazione, data_slot, ora_slot):
    categorie = configurazione["categorie"]
    if not categorie:
        return
    indice = _numero_slot_del_giorno(data_slot) % len(categorie)
    categoria = categorie[indice]
    if not _prenota_slot_automatico(data_slot, ora_slot, categoria):
        return

    try:
        if minuti_rimanenti_prima_del_prossimo_invio() > 0:
            _aggiorna_slot_automatico(data_slot, ora_slot, "saltata_distanza")
            await _notifica_admin_automazione(
                app.bot,
                f"⏭ Invio automatico delle {ora_slot} saltato: troppo vicino a un altro post.",
            )
            return

        prodotto = await cerca_offerta_automatica(configurazione, categoria)
        if not prodotto:
            _aggiorna_slot_automatico(data_slot, ora_slot, "nessuna_offerta")
            await _notifica_admin_automazione(
                app.bot,
                f"ℹ️ Alle {ora_slot} non ho trovato offerte nuove con almeno "
                f"il {configurazione['sconto_minimo']}% di sconto dopo 3 tentativi.",
            )
            return

        message_id, foto_file_id = await pubblica_offerta_automatica(app.bot, prodotto)
        _aggiorna_slot_automatico(
            data_slot,
            ora_slot,
            "pubblicata",
            prodotto,
            telegram_message_id=message_id,
            telegram_photo_file_id=foto_file_id,
            soglia_sconto=configurazione["sconto_minimo"],
            deal_end_time=prodotto.get("deal_end_time"),
        )
        await _notifica_admin_automazione(
            app.bot,
            f"✅ Offerta automatica pubblicata alle {ora_slot}:\n"
            f"{prodotto['nome']}\nSconto: -{prodotto['sconto']}%",
        )
    except Exception as errore:
        _aggiorna_slot_automatico(data_slot, ora_slot, "errore")
        print(f"Errore invio automatico: {errore}")
        await _notifica_admin_automazione(
            app.bot,
            f"❌ Errore invio automatico delle {ora_slot}:\n{str(errore)[:700]}",
        )


def _limiti_fascia_automatica(configurazione, giorno):
    inizio_ora = datetime.strptime(configurazione["ora_inizio"], "%H:%M").time()
    fine_ora = datetime.strptime(configurazione["ora_fine"], "%H:%M").time()
    return (
        datetime.combine(giorno, inizio_ora, tzinfo=ROMA_TZ),
        datetime.combine(giorno, fine_ora, tzinfo=ROMA_TZ),
    )


def _dentro_fascia_automatica(configurazione, adesso):
    inizio, fine = _limiti_fascia_automatica(configurazione, adesso.date())
    return inizio <= adesso < fine


def _prossimo_inizio_fascia(configurazione, adesso):
    inizio, fine = _limiti_fascia_automatica(configurazione, adesso.date())
    if adesso < inizio:
        return inizio
    if adesso >= fine:
        domani = adesso.date() + timedelta(days=1)
        return _limiti_fascia_automatica(configurazione, domani)[0]
    return adesso


def _calcola_prossimo_invio(configurazione, riferimento):
    candidato = riferimento + timedelta(minutes=configurazione["intervallo_minuti"])
    _, fine = _limiti_fascia_automatica(configurazione, riferimento.date())
    if candidato < fine:
        return candidato
    domani = riferimento.date() + timedelta(days=1)
    return _limiti_fascia_automatica(configurazione, domani)[0]


async def controlla_invii_automatici(app):
    while True:
        try:
            configurazione = leggi_config_automatica()
            if configurazione["attiva"]:
                adesso = datetime.now(ROMA_TZ)
                prossimo_testo = configurazione.get("prossimo_invio")
                prossimo = None
                if prossimo_testo:
                    try:
                        prossimo = datetime.fromisoformat(prossimo_testo)
                        if prossimo.tzinfo is None:
                            prossimo = prossimo.replace(tzinfo=ROMA_TZ)
                        else:
                            prossimo = prossimo.astimezone(ROMA_TZ)
                    except ValueError:
                        prossimo = None

                if prossimo is None:
                    prossimo = _prossimo_inizio_fascia(configurazione, adesso)
                    salva_config_automatica("prossimo_invio", prossimo.isoformat(timespec="seconds"))

                if adesso >= prossimo:
                    if not _dentro_fascia_automatica(configurazione, adesso):
                        prossimo = _prossimo_inizio_fascia(configurazione, adesso)
                        salva_config_automatica("prossimo_invio", prossimo.isoformat(timespec="seconds"))
                    else:
                        successivo = _calcola_prossimo_invio(configurazione, adesso)
                        salva_config_automatica("prossimo_invio", successivo.isoformat(timespec="seconds"))
                        data_slot = adesso.date().isoformat()
                        ora_slot = adesso.strftime("%H:%M")
                        if not _slot_automatico_gia_gestito(data_slot, ora_slot):
                            await esegui_slot_automatico(
                                app,
                                configurazione,
                                data_slot,
                                ora_slot,
                            )
        except Exception as errore:
            print(f"Errore controllo automazione: {errore}")
        await asyncio.sleep(20)


# =========================================================
# CONTROLLO OFFERTE TERMINATE
# =========================================================

def _offerte_da_verificare():
    adesso = datetime.now(ROMA_TZ)
    limite = adesso - timedelta(days=7)
    db = sqlite3.connect(DB_PATH)
    righe = db.execute(
        """
        SELECT id, asin, nome, categoria, telegram_message_id,
               COALESCE(soglia_sconto, 0), COALESCE(verifiche_fallite, 0),
               creato_il, deal_end_time, ultima_verifica,
               telegram_photo_file_id
        FROM invii_automatici
        WHERE stato = 'pubblicata'
          AND telegram_message_id IS NOT NULL
          AND creato_il >= ?
        ORDER BY creato_il DESC
        """,
        (limite.isoformat(timespec="seconds"),),
    ).fetchall()
    db.close()
    da_verificare = []
    for riga in righe:
        creato_il = _data_api(riga[7])
        fine_offerta = _data_api(riga[8])
        ultima_verifica = _data_api(riga[9]) or creato_il
        if not creato_il:
            continue

        eta = adesso - creato_il
        fallimenti = riga[6]
        if fallimenti > 0:
            intervallo = timedelta(minutes=30)
        elif fine_offerta and adesso < fine_offerta:
            continue
        elif fine_offerta:
            intervallo = timedelta(hours=2)
        elif eta <= timedelta(hours=24):
            intervallo = timedelta(hours=2)
        elif eta <= timedelta(hours=72):
            intervallo = timedelta(hours=6)
        else:
            intervallo = timedelta(hours=24)

        if not ultima_verifica or adesso - ultima_verifica >= intervallo:
            da_verificare.append(riga[:7] + (riga[10],))
    return da_verificare


def _data_api(valore):
    if not valore:
        return None
    try:
        testo = str(valore).strip().replace("Z", "+00:00")
        data = datetime.fromisoformat(testo)
        if data.tzinfo is None:
            data = data.replace(tzinfo=ROMA_TZ)
        return data.astimezone(ROMA_TZ)
    except (TypeError, ValueError):
        return None


def _aggiorna_verifica_offerta(invio_id, fallita):
    db = sqlite3.connect(DB_PATH)
    if fallita:
        db.execute(
            """
            UPDATE invii_automatici
            SET verifiche_fallite = COALESCE(verifiche_fallite, 0) + 1,
                ultima_verifica = ?
            WHERE id = ?
            """,
            (datetime.now(ROMA_TZ).isoformat(timespec="seconds"), invio_id),
        )
    else:
        db.execute(
            """
            UPDATE invii_automatici
            SET verifiche_fallite = 0, ultima_verifica = ?
            WHERE id = ?
            """,
            (datetime.now(ROMA_TZ).isoformat(timespec="seconds"), invio_id),
        )
    db.commit()
    valore = db.execute(
        "SELECT COALESCE(verifiche_fallite, 0) FROM invii_automatici WHERE id = ?",
        (invio_id,),
    ).fetchone()
    db.close()
    return valore[0] if valore else 0


def _segna_offerta_terminata(invio_id):
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        UPDATE invii_automatici
        SET stato = 'terminata', terminata_il = ?
        WHERE id = ?
        """,
        (datetime.now(ROMA_TZ).isoformat(timespec="seconds"), invio_id),
    )
    db.commit()
    db.close()


async def _modifica_post_terminato(
    bot,
    invio_id,
    nome,
    categoria,
    message_id,
    foto_file_id=None,
):
    hashtag = AUTO_HASHTAG.get(categoria, "#OfferteAmazon")
    didascalia = (
        "⛔ <b>OFFERTA TERMINATA</b>\n\n"
        f"🛒 {html.escape(nome)}\n\n"
        "Questa promozione non risulta più disponibile.\n\n"
        f"Categoria: {hashtag}\n\n"
        "Continua a seguirci per le prossime offerte."
    )
    immagine_aggiornata = False
    if foto_file_id:
        try:
            file_telegram = await bot.get_file(foto_file_id)
            dati = await file_telegram.download_as_bytearray()
            foto_terminata = await asyncio.to_thread(crea_immagine_terminata, dati)
            await bot.edit_message_media(
                chat_id=CHANNEL_ID,
                message_id=message_id,
                media=InputMediaPhoto(
                    media=foto_terminata,
                    caption=didascalia,
                    parse_mode="HTML",
                ),
                reply_markup=None,
            )
            immagine_aggiornata = True
        except Exception as errore:
            print(f"Impossibile aggiornare la foto terminata: {errore}")

    # Fallback per vecchi post o errori nel download della foto Telegram.
    if not immagine_aggiornata:
        await bot.edit_message_caption(
            chat_id=CHANNEL_ID,
            message_id=message_id,
            caption=didascalia,
            parse_mode="HTML",
        )
        await bot.edit_message_reply_markup(
            chat_id=CHANNEL_ID,
            message_id=message_id,
            reply_markup=None,
        )
    _segna_offerta_terminata(invio_id)


async def controlla_offerte_terminate(app):
    while True:
        try:
            offerte = _offerte_da_verificare()
            for posizione in range(0, len(offerte), 10):
                gruppo = offerte[posizione:posizione + 10]
                asins = [riga[1] for riga in gruppo if riga[1]]
                if not asins:
                    continue
                try:
                    items = await asyncio.to_thread(get_items, asins)
                except Exception as errore:
                    print(f"Errore verifica disponibilità Creator API: {errore}")
                    continue

                prodotti = {}
                for item in items:
                    asin = getattr(item, "asin", None)
                    if asin:
                        prodotti[asin] = estrai_prodotto_creators(item)

                for invio_id, asin, nome, categoria, message_id, soglia, _, foto_file_id in gruppo:
                    prodotto = prodotti.get(asin)
                    non_valida = not prodotto or prodotto["sconto"] < soglia
                    fallimenti = _aggiorna_verifica_offerta(invio_id, non_valida)
                    if non_valida and fallimenti >= 2:
                        try:
                            await _modifica_post_terminato(
                                app.bot,
                                invio_id,
                                nome,
                                categoria,
                                message_id,
                                foto_file_id,
                            )
                            await _notifica_admin_automazione(
                                app.bot,
                                f"⛔ Offerta terminata aggiornata nel canale:\n{nome}",
                            )
                        except Exception as errore:
                            print(f"Errore modifica post terminato: {errore}")

                await asyncio.sleep(1.2)
        except Exception as errore:
            print(f"Errore controllo offerte terminate: {errore}")

        await asyncio.sleep(1800)


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
                    "🔁 INVIA DI NUOVO",
                    callback_data="reinvia_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    "📅 PROGRAMMATI",
                    callback_data="programmati",
                )
            ],
            [
                InlineKeyboardButton(
                    "🤖 INVIO AUTOMATICO",
                    callback_data="auto_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 GESTIONE CLUB",
                    callback_data="admin_club",
                )
            ],
        ]
    )


def menu_dopo_pubblicazione():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ INVIA UN NUOVO POST",
                    callback_data="nuova",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ TORNA AL MENU PRINCIPALE",
                    callback_data="menu_admin",
                )
            ],
        ]
    )


async def torna_menu_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🔥 AMAZON OFFERTE BOT\n\n"
        "🛠 Modalità amministratore\n\n"
        "Cosa vuoi fare?",
        reply_markup=menu_principale(),
    )



def menu_utente_principale():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛍️ SCEGLI LA CATEGORIA",
                    callback_data="categorie",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎁 CLUB & PREMI",
                    callback_data="club_home",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 INVITA AMICI",
                    callback_data="club_invita",
                ),
                InlineKeyboardButton(
                    "⭐ I MIEI PUNTI",
                    callback_data="club_punti",
                ),
            ],
        ]
    )


def menu_categorie():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔌 ELETTRONICA",
                    url="https://t.me/bestprice_2026",
                ),
                InlineKeyboardButton(
                    "🏠 CASA 🚧",
                    callback_data="wip_casa",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🌿 GIARDINO 🚧",
                    callback_data="wip_giardino",
                ),
                InlineKeyboardButton(
                    "🔨 FAI DA TE 🚧",
                    callback_data="wip_faidate",
                ),
            ],
            [
                InlineKeyboardButton(
                    "👕 MODA 🚧",
                    callback_data="wip_moda",
                ),
                InlineKeyboardButton(
                    "💄 BELLEZZA 🚧",
                    callback_data="wip_bellezza",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏋️ SPORT 🚧",
                    callback_data="wip_sport",
                ),
                InlineKeyboardButton(
                    "🧸 BAMBINI 🚧",
                    callback_data="wip_bambini",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🐶 ANIMALI 🚧",
                    callback_data="wip_animali",
                ),
                InlineKeyboardButton(
                    "🚗 AUTO & MOTO 🚧",
                    callback_data="wip_auto",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ TORNA AL MENU PRINCIPALE",
                    callback_data="menu_utente",
                )
            ],
        ]
    )


async def mostra_categorie(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🛍️ SCEGLI LA CATEGORIA\n\n"
        "Segui solo le offerte che ti interessano 👇",
        reply_markup=menu_categorie(),
    )


async def categoria_work_in_progress(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🚧 COMING SOON\n\n"
        "Stiamo preparando questo canale.\n"
        "Torna presto per scoprire le nuove offerte! 🔥",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ TORNA ALLE CATEGORIE",
                        callback_data="categorie",
                    )
                ]
            ]
        ),
    )


async def torna_menu_utente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🔥 BESTPRICE24H\n\n"
        "Meno offerte. Più affari.\n\n"
        "Scegli cosa vuoi fare 👇",
        reply_markup=menu_utente_principale(),
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

    # =====================================================
    # ADMIN
    # =====================================================
    if autorizzato(update):

        await update.message.reply_text(
            "🔥 AMAZON OFFERTE BOT\n\n"
            "🛠 Modalità amministratore\n\n"
            "Cosa vuoi fare?",
            reply_markup=menu_principale(),
        )

        return ConversationHandler.END

    # =====================================================
    # UTENTE NORMALE
    # =====================================================
    invitato_da = None

    if context.args:

        try:
            invitato_da = int(context.args[0])

        except (ValueError, TypeError):
            invitato_da = None

    registra_utente(
        user,
        invitato_da
    )

    testo = (
        "🔥 BENVENUTO SU BESTPRICE24H\n\n"
        "Meno offerte. Più affari.\n\n"
        "Qui trovi una selezione delle migliori offerte Amazon, "
        "organizzate per categoria, così puoi seguire solo quello "
        "che ti interessa.\n\n"
        "📲 Scegli i tuoi canali preferiti e non perderti "
        "le occasioni migliori.\n\n"
        "🎁 Con il Club BestPrice24h puoi invitare amici, "
        "accumulare punti e ottenere premi.\n\n"
        "👇 Da dove vuoi iniziare?"
    )

    await update.message.reply_text(
        testo,
        reply_markup=menu_utente_principale(),
    )

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

    # UTENTE
    invitato_da = None

    if context.args:

        try:
            invitato_da = int(context.args[0])

        except (ValueError, TypeError):
            invitato_da = None

    registra_utente(
        user,
        invitato_da
    )

    testo = (
        "🔥 BENVENUTO SU BESTPRICE24H\\n\\n"
        "Meno offerte. Più affari.\\n\\n"
        "Qui trovi una selezione delle migliori offerte Amazon, "
        "organizzate per categoria, così puoi seguire solo quello "
        "che ti interessa.\\n\\n"
        "📲 Scegli i tuoi canali preferiti e non perderti "
        "le occasioni migliori.\\n\\n"
        "🎁 Con il Club BestPrice24h puoi invitare amici, "
        "accumulare punti e ottenere premi.\\n\\n"
        "👇 Da dove vuoi iniziare?"
    )

    await update.message.reply_text(
        testo,
        reply_markup=menu_utente_principale(),
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

    dati = None

    # Prova fino a 3 volte a leggere automaticamente i dati Amazon.
    # Tra un tentativo e l'altro aspetta un attimo, utile quando Amazon
    # risponde in modo incompleto o temporaneamente blocca la richiesta.
    for tentativo in range(1, 4):

        dati = await asyncio.to_thread(
            leggi_prodotto_amazon,
            link,
        )

        if dati:
            break

        if tentativo < 3:
            await messaggio_attesa.edit_text(
                f"🔎 Tentativo {tentativo}/3 non riuscito.\n"
                "Riprovo automaticamente..."
            )
            await asyncio.sleep(2)

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

    context.user_data["nome"] = " ".join(str(nome).split()).strip()
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

        return await chiedi_immagine(
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

    context.user_data["nome"] = " ".join(
        update.message.text.strip().split()
    )

    await update.message.reply_text(
        "💰 Qual è il prezzo attuale?"
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

    return await chiedi_immagine(
        update,
        context,
    )


# =========================================================
# PULIZIA PREZZO
# =========================================================

def accorcia_nome_articolo(nome):
    """Semplifica i titoli Amazon mantenendo le informazioni più utili."""
    if not nome:
        return ""

    nome = " ".join(str(nome).split()).strip()

    # Elimina ciò che segue separatori tipicamente usati per descrizioni secondarie.
    for separatore in [" | ", " – ", " — "]:
        if separatore in nome:
            parte = nome.split(separatore, 1)[0].strip()
            if len(parte.split()) >= 3:
                nome = parte
                break

    # Espressioni commerciali/accessorie che appesantiscono spesso i titoli Amazon.
    frasi_inutili = [
        r"\bideale per\b",
        r"\bperfetto per\b",
        r"\balta qualità\b",
        r"\bnuovo modello\b",
        r"\bcon tecnologia\b",
        r"\bcompatibile con\b",
        r"\bcompatibile per\b",
        r"\balexa integrata\b",
        r"\bassistente vocale\b",
    ]

    # Se una di queste frasi introduce la parte accessoria finale, la rimuove.
    for frase in frasi_inutili:
        m = re.search(frase, nome, flags=re.IGNORECASE)
        if m and m.start() > 20:
            nome = nome[:m.start()].rstrip(" ,;-")
            break

    # Divide sulle virgole: conserva il nucleo iniziale e solo specifiche brevi/utili.
    parti = [p.strip() for p in nome.split(",") if p.strip()]
    if len(parti) <= 1:
        return nome.rstrip(" ,;-")

    risultato = parti[0]
    parole_chiave = re.compile(
        r"(\b\d+\s?(?:GB|TB|MB|W|mAh|Hz|kHz|MP|L|ml|cm|mm)\b|"
        r"\b\d+(?:[.,]\d+)?[\"”″]\b|"
        r"\b\d+(?:[.,]\d+)?\s?(?:pollici|litri)\b|"
        r"\b4K\b|\b8K\b|\bUHD\b|\bOLED\b|\bQLED\b|\bAMOLED\b|"
        r"\b5G\b|\bWi-?Fi\b|\bBluetooth\b|\bWireless\b|\bUSB-C\b|"
        r"\bPro\b|\bMax\b|\bPlus\b|\bUltra\b|"
        r"\bNero\b|\bBianco\b|\bGrafite\b|\bNavy\b|\bBlu\b|\bRosso\b|\bVerde\b)",
        re.IGNORECASE
    )

    aggiunte = 0
    for parte in parti[1:]:
        if parole_chiave.search(parte):
            candidato = f"{risultato} {parte}".strip()
            if len(candidato) <= 100:
                risultato = candidato
                aggiunte += 1
        if aggiunte >= 2:
            break

    # Nessun puntino di sospensione: restituisce sempre un titolo completo.
    return re.sub(r"\s{2,}", " ", risultato).strip(" ,;-")



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
    context.user_data["nome"] = " ".join(str(nome).split()).strip()
    context.user_data["prezzo"] = pulisci_prezzo(prezzo)

    if vecchio.upper() == "NO":
        context.user_data["vecchio_prezzo"] = "NO"
    else:
        context.user_data["vecchio_prezzo"] = pulisci_prezzo(vecchio)

    return await chiedi_immagine(
        update,
        context,
    )



# =========================================================
# RICEZIONE ORA PROGRAMMAZIONE
# =========================================================

async def ricevi_ora_programmazione(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    testo = update.message.text.strip()

    # Accettiamo anche 9:00 oltre a 09:00
    formati = [
        "%H:%M",
    ]

    ora_scelta = None

    for formato in formati:

        try:

            ora_scelta = datetime.strptime(
                testo,
                formato,
            ).time()

            break

        except ValueError:
            pass

    if ora_scelta is None:

        await update.message.reply_text(
            "❌ Orario non corretto.\n\n"
            "Inserisci l'orario nel formato HH:MM."
        )

        return PROGRAMMA_ORA

    data_iso = context.user_data.get(
        "data_programmata"
    )

    if not data_iso:

        await update.message.reply_text(
            "❌ Giorno non trovato.\n"
            "Riprova dalla programmazione."
        )

        return ConversationHandler.END

    data_scelta = datetime.fromisoformat(
        data_iso
    ).date()

    data_locale = datetime.combine(
        data_scelta,
        ora_scelta,
        tzinfo=ROMA_TZ,
    )

    adesso = datetime.now(
        ROMA_TZ
    )

    if data_locale <= adesso:

        await update.message.reply_text(
            "❌ Questo orario è già passato.\n\n"
            "Inserisci un orario futuro."
        )

        return PROGRAMMA_ORA

    conflitti = trova_conflitto(
        data_locale
    )

    if conflitti:

        vicino = conflitti[0]

        context.user_data[
            "data_ora_da_confermare"
        ] = data_locale.isoformat()

        tastiera = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ SÌ, PROGRAMMA",
                    callback_data="conferma_orario_vicino",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 CAMBIA ORARIO",
                    callback_data="cambia_orario",
                )
            ],
        ])

        await update.message.reply_text(
            "⚠️ POST TROPPO VICINO\n\n"
            f"Hai già un'offerta programmata "
            f"alle "
            f"{vicino['datetime'].strftime('%H:%M')}.\n\n"
            f"📦 {vicino['nome']}\n"
            f"💰 {vicino['prezzo']} €\n\n"
            f"Ti consiglio di lasciare almeno "
            f"{DISTANZA_MINIMA_MINUTI} minuti "
            "tra due offerte.\n\n"
            "Vuoi programmarla comunque?",
            reply_markup=tastiera,
        )

        return CONFERMA_ORARIO

    messaggio = context.user_data.get(
        "messaggio"
    )
    link = context.user_data.get(
        "link"
    )
    nome = context.user_data.get(
        "nome"
    )
    prezzo = context.user_data.get(
        "prezzo"
    )

    if not messaggio or not link:

        await update.message.reply_text(
            "❌ Dati dell'offerta mancanti."
        )

        return ConversationHandler.END

    (
        programmazione_id,
        invio_previsto,
    ) = salva_programmazione(
        nome,
        messaggio,
        link,
        prezzo,
        data_locale,
    )

    salva_foto_programmazione(
        programmazione_id,
        context.user_data.get("foto_file_id"),
    )

    da_reinvio = context.user_data.get("programmazione_da_reinvio", False)
    context.user_data.clear()

    await update.message.reply_text(
        "✅ OFFERTA PROGRAMMATA!\n\n"
        f"📅 Data: "
        f"{invio_previsto.strftime('%d/%m/%Y')}\n"
        f"🕒 Ora: "
        f"{invio_previsto.strftime('%H:%M')}\n"
        f"📦 {nome}\n"
        f"💰 {prezzo} €\n\n"
        f"🆔 Programmazione: "
        f"#{programmazione_id}",
        reply_markup=menu_principale(),
    )

    if da_reinvio:
        await invia_lista_programmati(update.message)

    return ConversationHandler.END



# =========================================================
# CONTROLLO SLOT PROGRAMMAZIONE
# =========================================================

DISTANZA_MINIMA_MINUTI = 29


def programmazioni_del_giorno(data_locale):

    inizio_locale = datetime.combine(
        data_locale,
        datetime.min.time(),
        tzinfo=ROMA_TZ,
    )

    fine_locale = (
        inizio_locale
        + timedelta(days=1)
    )

    inizio_utc = (
        inizio_locale
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )

    fine_utc = (
        fine_locale
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            id,
            nome,
            prezzo,
            invio_previsto
        FROM programmazioni
        WHERE stato = 'attesa'
          AND invio_previsto >= ?
          AND invio_previsto < ?
        ORDER BY invio_previsto ASC
    """, (
        inizio_utc,
        fine_utc,
    ))

    dati = cur.fetchall()

    db.close()

    risultati = []

    for (
        programmazione_id,
        nome,
        prezzo,
        invio_previsto,
    ) in dati:

        data_utc = datetime.fromisoformat(
            invio_previsto
        )

        if data_utc.tzinfo is None:
            data_utc = data_utc.replace(
                tzinfo=timezone.utc
            )

        data_it = data_utc.astimezone(
            ROMA_TZ
        )

        risultati.append(
            {
                "id": programmazione_id,
                "nome": nome,
                "prezzo": prezzo,
                "datetime": data_it,
            }
        )

    return risultati


def trova_conflitto(
    data_locale,
):

    eventi = programmazioni_del_giorno(
        data_locale.date()
    )

    conflitti = []

    for evento in eventi:

        differenza = abs(
            (
                evento["datetime"]
                - data_locale
            ).total_seconds()
            / 60
        )

        if differenza < DISTANZA_MINIMA_MINUTI:

            conflitti.append(
                {
                    **evento,
                    "differenza": int(
                        differenza
                    ),
                }
            )

    conflitti.sort(
        key=lambda x: x["differenza"]
    )

    return conflitti


def suggerisci_prossimo_slot(
    data_giorno,
):

    eventi = programmazioni_del_giorno(
        data_giorno
    )

    # Orari consigliati di base
    slot_base = [
        "09:00",
        "11:00",
        "13:00",
        "15:30",
        "18:00",
        "20:00",
        "21:30",
    ]

    adesso = datetime.now(
        ROMA_TZ
    )

    for slot in slot_base:

        ora_slot = datetime.strptime(
            slot,
            "%H:%M",
        ).time()

        candidato = datetime.combine(
            data_giorno,
            ora_slot,
            tzinfo=ROMA_TZ,
        )

        if candidato <= adesso:
            continue

        conflitti = trova_conflitto(
            candidato
        )

        if not conflitti:
            return candidato

    # Se gli slot standard sono occupati,
    # cerca slot liberi dalle 09:00 alle 22:30.
    candidato = datetime.combine(
        data_giorno,
        datetime.strptime(
            "09:00",
            "%H:%M",
        ).time(),
        tzinfo=ROMA_TZ,
    )

    fine = datetime.combine(
        data_giorno,
        datetime.strptime(
            "22:30",
            "%H:%M",
        ).time(),
        tzinfo=ROMA_TZ,
    )

    if candidato <= adesso:
        candidato = adesso.replace(
            second=0,
            microsecond=0,
        )

        minuto = candidato.minute

        resto = minuto % 15

        if resto:
            candidato += timedelta(
                minutes=(15 - resto)
            )

    while candidato <= fine:

        conflitti = trova_conflitto(
            candidato
        )

        if not conflitti:
            return candidato

        candidato += timedelta(
            minutes=15
        )

    return None



# =========================================================
# CONFERMA ORARIO VICINO
# =========================================================

async def conferma_orario_vicino(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query

    await query.answer()

    if query.data == "cambia_orario":

        await query.message.reply_text(
            "🕒 Scrivi un nuovo orario."
        )

        return PROGRAMMA_ORA

    data_iso = context.user_data.get(
        "data_ora_da_confermare"
    )

    if not data_iso:

        await query.message.reply_text(
            "❌ Dati programmazione mancanti."
        )

        return ConversationHandler.END

    data_locale = datetime.fromisoformat(
        data_iso
    )

    messaggio = context.user_data.get(
        "messaggio"
    )
    link = context.user_data.get(
        "link"
    )
    nome = context.user_data.get(
        "nome"
    )
    prezzo = context.user_data.get(
        "prezzo"
    )

    if not messaggio or not link:

        await query.message.reply_text(
            "❌ Dati dell'offerta mancanti."
        )

        return ConversationHandler.END

    (
        programmazione_id,
        invio_previsto,
    ) = salva_programmazione(
        nome,
        messaggio,
        link,
        prezzo,
        data_locale,
    )

    salva_foto_programmazione(
        programmazione_id,
        context.user_data.get("foto_file_id"),
    )

    da_reinvio = context.user_data.get("programmazione_da_reinvio", False)
    context.user_data.clear()

    await query.message.reply_text(
        "✅ OFFERTA PROGRAMMATA!\n\n"
        f"📅 Data: "
        f"{invio_previsto.strftime('%d/%m/%Y')}\n"
        f"🕒 Ora: "
        f"{invio_previsto.strftime('%H:%M')}\n"
        f"📦 {nome}\n"
        f"💰 {prezzo} €\n\n"
        f"🆔 Programmazione: "
        f"#{programmazione_id}",
        reply_markup=menu_principale(),
    )

    if da_reinvio:
        await invia_lista_programmati(query.message)

    return ConversationHandler.END


# =========================================================
# GESTIONE POST PROGRAMMATI
# =========================================================

def data_programmata_locale(invio_previsto):

    try:

        data_utc = datetime.fromisoformat(
            invio_previsto
        )

        if data_utc.tzinfo is None:
            data_utc = data_utc.replace(
                tzinfo=timezone.utc
            )

        return data_utc.astimezone(
            ROMA_TZ
        )

    except Exception:
        return None


def leggi_programmato(programmazione_id):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            id,
            nome,
            messaggio,
            link,
            prezzo,
            COALESCE(vecchio_prezzo, 'NO'),
            COALESCE(template, 'pulito'),
            foto_file_id,
            invio_previsto,
            stato
        FROM programmazioni
        WHERE id = ?
    """, (programmazione_id,))

    riga = cur.fetchone()

    db.close()

    if not riga:
        return None

    return {
        "id": riga[0],
        "nome": riga[1],
        "messaggio": riga[2],
        "link": riga[3],
        "prezzo": riga[4],
        "vecchio_prezzo": riga[5] or "NO",
        "template": riga[6] or "pulito",
        "foto_file_id": riga[7],
        "invio_previsto": riga[8],
        "stato": riga[9],
    }


def crea_messaggio_programmato(
    nome,
    prezzo,
    vecchio,
    template,
):

    vecchio = vecchio or "NO"
    template = template or "pulito"

    sconto = None

    if str(vecchio).upper() != "NO":

        sconto = calcola_sconto(
            prezzo,
            vecchio,
        )

    if template == "aggressivo":

        testo = (
            "🚨 SUPER OFFERTA AMAZON 🚨\n\n"
            f"🔥 {nome}\n\n"
        )

        if str(vecchio).upper() != "NO":
            testo += (
                f"❌ Prima: {vecchio} €\n"
            )

        testo += f"✅ ORA: {prezzo} €\n"

        if sconto is not None:
            testo += (
                f"\n💥 SCONTO {sconto}%"
            )

        testo += (
            "\n\n⚡ Approfittane prima "
            "che cambi il prezzo!"
        )

        return testo

    if template == "tech":

        testo = (
            "⚡ TECH DEAL\n\n"
            f"📱 {nome}\n\n"
        )

        if str(vecchio).upper() != "NO":
            testo += (
                f"🏷️ Listino: {vecchio} €\n"
            )

        testo += (
            f"💰 Offerta: {prezzo} €\n"
        )

        if sconto is not None:
            testo += f"📉 -{sconto}%"

        return testo

    testo = (
        "🔥 OFFERTA AMAZON\n\n"
        f"📦 {nome}\n\n"
    )

    if str(vecchio).upper() != "NO":
        testo += (
            f"❌ Prima: {vecchio} €\n"
        )

    testo += f"✅ Ora: {prezzo} €\n"

    if sconto is not None:
        testo += (
            f"\n🔥 Sconto: {sconto}%"
        )

    return testo


def aggiorna_messaggio_programmato(
    programmazione_id,
):

    post = leggi_programmato(
        programmazione_id
    )

    if not post:
        return False

    messaggio = crea_messaggio_programmato(
        post["nome"],
        post["prezzo"],
        post["vecchio_prezzo"],
        post["template"],
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET messaggio = ?
        WHERE id = ?
    """, (
        messaggio,
        programmazione_id,
    ))

    db.commit()
    db.close()

    return True


async def invia_lista_programmati(
    messaggio,
):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            id,
            nome,
            prezzo,
            invio_previsto
        FROM programmazioni
        WHERE stato = 'attesa'
        ORDER BY invio_previsto ASC
        LIMIT 100
    """)

    righe_db = cur.fetchall()

    db.close()

    if not righe_db:

        await messaggio.reply_text(
            "📅 POST PROGRAMMATI\n\n"
            "Non ci sono offerte programmate.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ TORNA AL MENU PRINCIPALE",
                            callback_data="prog_esci",
                        )
                    ]
                ]
            ),
        )

        return

    righe = [
        "📅 POST PROGRAMMATI\n"
    ]

    for (
        programmazione_id,
        nome,
        prezzo,
        invio_previsto,
    ) in righe_db:

        data_locale = data_programmata_locale(
            invio_previsto
        )

        if data_locale:
            quando = data_locale.strftime(
                "%d/%m • %H:%M"
            )
        else:
            quando = invio_previsto

        righe.append(
            f"#{programmazione_id} • {quando}\n"
            f"📦 {nome} — {prezzo} €\n"
        )

    righe.append(
        "\n🔢 Scrivi il numero # del post "
        "che vuoi gestire.\n\n"
    )

    await messaggio.reply_text(
        "\n".join(righe),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ TORNA AL MENU PRINCIPALE",
                        callback_data="prog_esci",
                    )
                ]
            ]
        ),
    )


async def mostra_programmati(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query

    if query:
        await query.answer()
        messaggio = query.message
    else:
        messaggio = update.message

    context.user_data.pop(
        "prog_id",
        None,
    )

    # Pulisce eventuali stati rimasti dal flusso "Invia di nuovo".
    # Così il numero digitato qui viene sempre interpretato come ID
    # del post programmato da gestire/modificare, mai come un orario.
    for chiave in (
        "attesa_ora_reinvio",
        "reinvia_data",
        "reinvia_edit_state",
        "reinvia_attesa_foto",
        "programmazione_da_reinvio",
    ):
        context.user_data.pop(chiave, None)

    await invia_lista_programmati(
        messaggio
    )

    return PROG_SELEZIONE


async def seleziona_programmato(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    testo = update.message.text.strip()

    testo = testo.replace("#", "").strip()

    if not testo.isdigit():

        await update.message.reply_text(
            "❌ Scrivi solo il numero del post.\n\n"
            )

        return PROG_SELEZIONE

    programmazione_id = int(testo)

    post = leggi_programmato(
        programmazione_id
    )

    if (
        not post
        or post["stato"] != "attesa"
    ):

        await update.message.reply_text(
            "❌ Non trovo un post programmato "
            f"attivo con ID #{programmazione_id}.\n\n"
            "Scrivi un altro numero."
        )

        return PROG_SELEZIONE

    context.user_data[
        "prog_id"
    ] = programmazione_id

    await invia_scheda_programmato(
        update.message,
        programmazione_id,
    )

    return PROG_GESTIONE


async def invia_scheda_programmato(
    messaggio,
    programmazione_id,
):

    post = leggi_programmato(
        programmazione_id
    )

    if not post:
        return

    data_locale = data_programmata_locale(
        post["invio_previsto"]
    )

    quando = (
        data_locale.strftime(
            "%d/%m/%Y • %H:%M"
        )
        if data_locale
        else post["invio_previsto"]
    )

    testo = (
        f"📅 POST PROGRAMMATO #{post['id']}\n"
        f"🕒 {quando}\n\n"
        "👀 ANTEPRIMA\n\n"
        f"{post['messaggio']}\n\n"
        f"👉 {post['link']}\n\n"
        "⚡ Prezzo e disponibilità "
        "possono variare."
    )

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛒 APRI",
                    url=post["link"],
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ MODIFICA",
                    callback_data="prog_modifica",
                ),
                InlineKeyboardButton(
                    "🗑 ELIMINA",
                    callback_data="prog_elimina",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ TORNA AI PROGRAMMATI",
                    callback_data="prog_indietro",
                )
            ],
        ]
    )

    if post.get("foto_file_id"):
        await messaggio.reply_photo(
            photo=post["foto_file_id"],
            caption=testo,
            reply_markup=tastiera,
        )
    else:
        await messaggio.reply_text(
            testo,
            reply_markup=tastiera,
        )


async def gestisci_programmato(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:

        await query.message.reply_text(
            "❌ Post non selezionato."
        )

        return PROG_SELEZIONE

    if query.data == "prog_indietro":

        context.user_data.pop(
            "prog_id",
            None,
        )

        await invia_lista_programmati(
            query.message
        )

        return PROG_SELEZIONE

    if query.data == "prog_elimina":

        post = leggi_programmato(
            programmazione_id
        )

        if not post:
            return PROG_SELEZIONE

        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ SÌ, ELIMINA",
                        callback_data="prog_elimina_si",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ ANNULLA",
                        callback_data="prog_elimina_no",
                    )
                ],
            ]
        )

        await query.message.reply_text(
            "⚠️ ELIMINARE QUESTO POST?\n\n"
            f"#{programmazione_id}\n"
            f"📦 {post['nome']}\n"
            f"💰 {post['prezzo']} €",
            reply_markup=tastiera,
        )

        return PROG_GESTIONE

    if query.data == "prog_modifica":

        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📦 NOME",
                        callback_data="prog_edit_nome",
                    ),
                    InlineKeyboardButton(
                        "💰 PREZZO",
                        callback_data="prog_edit_prezzo",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🏷 PREZZO PRIMA",
                        callback_data="prog_edit_vecchio",
                    ),
                    InlineKeyboardButton(
                        "🔗 LINK",
                        callback_data="prog_edit_link",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🖼 IMMAGINE",
                        callback_data="prog_edit_immagine",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🕒 DATA E ORA",
                        callback_data="prog_edit_dataora",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🎨 TEMPLATE",
                        callback_data="prog_edit_template",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ INDIETRO",
                        callback_data="prog_torna_scheda",
                    )
                ],
            ]
        )

        await query.message.reply_text(
            "✏️ COSA VUOI MODIFICARE?",
            reply_markup=tastiera,
        )

        return PROG_MODIFICA_MENU

    if query.data == "prog_elimina_no":

        await invia_scheda_programmato(
            query.message,
            programmazione_id,
        )

        return PROG_GESTIONE

    if query.data == "prog_elimina_si":

        db = sqlite3.connect(DB_PATH)
        cur = db.cursor()

        cur.execute("""
            UPDATE programmazioni
            SET stato = 'annullata'
            WHERE id = ?
              AND stato = 'attesa'
        """, (
            programmazione_id,
        ))

        modificati = cur.rowcount

        db.commit()
        db.close()

        if modificati:

            await query.message.reply_text(
                f"🗑 Post #{programmazione_id} "
                "eliminato dalla programmazione."
            )

        else:

            await query.message.reply_text(
                "❌ Il post non è più disponibile."
            )

        context.user_data.pop(
            "prog_id",
            None,
        )

        await invia_lista_programmati(
            query.message
        )

        return PROG_SELEZIONE

    return PROG_GESTIONE


async def menu_modifica_programmato(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    if query.data == "prog_torna_scheda":

        await invia_scheda_programmato(
            query.message,
            programmazione_id,
        )

        return PROG_GESTIONE

    if query.data == "prog_edit_nome":

        await query.message.reply_text(
            "📦 Scrivi il nuovo nome del prodotto:"
        )

        return PROG_EDIT_NOME

    if query.data == "prog_edit_prezzo":

        await query.message.reply_text(
            "💰 Scrivi il nuovo prezzo attuale.\n\n"
        )

        return PROG_EDIT_PREZZO

    if query.data == "prog_edit_vecchio":

        await query.message.reply_text(
            "🏷 Scrivi il nuovo prezzo precedente.\n\n"
            "Oppure scrivi NO."
        )

        return PROG_EDIT_VECCHIO

    if query.data == "prog_edit_link":

        await query.message.reply_text(
            "🔗 Inviami il nuovo link Amazon:"
        )

        return PROG_EDIT_LINK

    if query.data == "prog_edit_immagine":

        post = leggi_programmato(
            programmazione_id
        )

        if not post:
            return PROG_GESTIONE

        if post.get("foto_file_id"):

            tastiera = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 SOSTITUISCI IMMAGINE",
                            callback_data="prog_img_sostituisci",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🗑 RIMUOVI IMMAGINE",
                            callback_data="prog_img_rimuovi",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ INDIETRO",
                            callback_data="prog_img_indietro",
                        )
                    ],
                ]
            )

        else:

            tastiera = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📷 AGGIUNGI IMMAGINE",
                            callback_data="prog_img_aggiungi",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ INDIETRO",
                            callback_data="prog_img_indietro",
                        )
                    ],
                ]
            )

        await query.message.reply_text(
            "🖼 GESTIONE IMMAGINE",
            reply_markup=tastiera,
        )

        return PROG_IMMAGINE_MENU

    if query.data == "prog_edit_dataora":

        await query.message.reply_text(
            "🕒 Scrivi nuova data e ora nel formato:\n\n"
            "25/08/2026 18:30"
        )

        return PROG_EDIT_DATA_ORA

    if query.data == "prog_edit_template":

        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✨ PULITO",
                        callback_data="prog_tpl_pulito",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🚨 AGGRESSIVO",
                        callback_data="prog_tpl_aggressivo",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⚡ TECH",
                        callback_data="prog_tpl_tech",
                    )
                ],
            ]
        )

        await query.message.reply_text(
            "🎨 Scegli il nuovo template:",
            reply_markup=tastiera,
        )

        return PROG_MODIFICA_MENU

    if query.data.startswith("prog_tpl_"):

        template = query.data.replace(
            "prog_tpl_",
            "",
        )

        db = sqlite3.connect(DB_PATH)
        cur = db.cursor()

        cur.execute("""
            UPDATE programmazioni
            SET template = ?
            WHERE id = ?
              AND stato = 'attesa'
        """, (
            template,
            programmazione_id,
        ))

        db.commit()
        db.close()

        aggiorna_messaggio_programmato(
            programmazione_id
        )

        await query.message.reply_text(
            "✅ Template aggiornato."
        )

        await invia_scheda_programmato(
            query.message,
            programmazione_id,
        )

        return PROG_GESTIONE

    return PROG_MODIFICA_MENU


async def salva_modifica_testuale_programmato(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    valore = update.message.text.strip()

    stato = context.user_data.get(
        "prog_edit_state"
    )

    # Lo stato viene impostato dai wrapper sotto.
    if stato == "nome":

        if not valore:

            await update.message.reply_text(
                "❌ Il nome non può essere vuoto."
            )

            return PROG_EDIT_NOME

        colonna = "nome"
        nuovo_valore = valore

    elif stato == "prezzo":

        nuovo_valore = pulisci_prezzo(
            valore
        )

        if not nuovo_valore:

            await update.message.reply_text(
                "❌ Prezzo non valido."
            )

            return PROG_EDIT_PREZZO

        colonna = "prezzo"

    elif stato == "vecchio":

        if valore.upper() == "NO":
            nuovo_valore = "NO"
        else:
            nuovo_valore = pulisci_prezzo(
                valore
            )

        colonna = "vecchio_prezzo"

    elif stato == "link":

        if (
            "amazon." not in valore
            and "amzn." not in valore
        ):

            await update.message.reply_text(
                "❌ Non sembra un link Amazon.\n"
                "Invia un link valido."
            )

            return PROG_EDIT_LINK

        colonna = "link"
        nuovo_valore = valore

    else:
        return PROG_GESTIONE

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute(
        f"""
        UPDATE programmazioni
        SET {colonna} = ?
        WHERE id = ?
          AND stato = 'attesa'
        """,
        (
            nuovo_valore,
            programmazione_id,
        ),
    )

    db.commit()
    db.close()

    if colonna in (
        "nome",
        "prezzo",
        "vecchio_prezzo",
    ):

        aggiorna_messaggio_programmato(
            programmazione_id
        )

    context.user_data.pop(
        "prog_edit_state",
        None,
    )

    await update.message.reply_text(
        "✅ Post programmato aggiornato."
    )

    await invia_scheda_programmato(
        update.message,
        programmazione_id,
    )

    return PROG_GESTIONE


async def edit_programmato_nome(
    update,
    context,
):

    context.user_data[
        "prog_edit_state"
    ] = "nome"

    return await salva_modifica_testuale_programmato(
        update,
        context,
    )


async def edit_programmato_prezzo(
    update,
    context,
):

    context.user_data[
        "prog_edit_state"
    ] = "prezzo"

    return await salva_modifica_testuale_programmato(
        update,
        context,
    )


async def edit_programmato_vecchio(
    update,
    context,
):

    context.user_data[
        "prog_edit_state"
    ] = "vecchio"

    return await salva_modifica_testuale_programmato(
        update,
        context,
    )


async def edit_programmato_link(
    update,
    context,
):

    context.user_data[
        "prog_edit_state"
    ] = "link"

    return await salva_modifica_testuale_programmato(
        update,
        context,
    )


async def edit_programmato_dataora(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    valore = update.message.text.strip()

    try:

        data_locale = datetime.strptime(
            valore,
            "%d/%m/%Y %H:%M",
        ).replace(
            tzinfo=ROMA_TZ
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Formato non valido.\n\n"
            "Usa: 25/08/2026 18:30"
        )

        return PROG_EDIT_DATA_ORA

    if data_locale <= datetime.now(
        ROMA_TZ
    ):

        await update.message.reply_text(
            "❌ La nuova data/ora deve "
            "essere nel futuro."
        )

        return PROG_EDIT_DATA_ORA

    conflitti = trova_conflitto(
        data_locale
    )

    conflitti = [
        evento
        for evento in conflitti
        if evento["id"] != programmazione_id
    ]

    if conflitti:

        vicino = conflitti[0]

        await update.message.reply_text(
            "⚠️ Attenzione: c'è già un post "
            "programmato vicino a questo orario.\n\n"
            f"📦 {vicino['nome']}\n"
            f"🕒 {vicino['datetime'].strftime('%H:%M')}\n\n"
            "La modifica viene comunque salvata."
        )

    data_utc = data_locale.astimezone(
        timezone.utc
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET invio_previsto = ?
        WHERE id = ?
          AND stato = 'attesa'
    """, (
        data_utc.isoformat(
            timespec="seconds"
        ),
        programmazione_id,
    ))

    db.commit()
    db.close()

    await update.message.reply_text(
        "✅ Data e ora aggiornate."
    )

    await invia_scheda_programmato(
        update.message,
        programmazione_id,
    )

    return PROG_GESTIONE



async def gestisci_immagine_programmata(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    if query.data == "prog_img_indietro":

        await query.message.reply_text(
            "✏️ Torna alla modifica del post.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ MODIFICA POST",
                            callback_data="prog_modifica",
                        )
                    ]
                ]
            ),
        )

        return PROG_GESTIONE

    if query.data in (
        "prog_img_aggiungi",
        "prog_img_sostituisci",
    ):

        await query.message.reply_text(
            "📷 Inviami la nuova immagine."
        )

        return PROG_IMMAGINE_ATTESA

    if query.data == "prog_img_rimuovi":

        db = sqlite3.connect(DB_PATH)
        cur = db.cursor()

        cur.execute("""
            UPDATE programmazioni
            SET foto_file_id = NULL
            WHERE id = ?
              AND stato = 'attesa'
        """, (
            programmazione_id,
        ))

        db.commit()
        db.close()

        await query.message.reply_text(
            "✅ Immagine rimossa."
        )

        await invia_scheda_programmato(
            query.message,
            programmazione_id,
        )

        return PROG_GESTIONE

    return PROG_IMMAGINE_MENU


async def ricevi_immagine_programmata(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    if not update.message.photo:

        await update.message.reply_text(
            "❌ Inviami una foto valida."
        )

        return PROG_IMMAGINE_ATTESA

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    foto_file_id = (
        update.message.photo[-1].file_id
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET foto_file_id = ?
        WHERE id = ?
          AND stato = 'attesa'
    """, (
        foto_file_id,
        programmazione_id,
    ))

    db.commit()
    db.close()

    await update.message.reply_text(
        "✅ Immagine aggiornata."
    )

    await invia_scheda_programmato(
        update.message,
        programmazione_id,
    )

    return PROG_GESTIONE


async def esci_programmati(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    context.user_data.pop(
        "prog_id",
        None,
    )
    context.user_data.pop(
        "prog_edit_state",
        None,
    )

    await query.message.reply_text(
        "🔥 AMAZON OFFERTE BOT\n\n"
        "🛠 Modalità amministratore\n\n"
        "Cosa vuoi fare?",
        reply_markup=menu_principale(),
    )

    return ConversationHandler.END


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



async def chiedi_immagine(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📷 AGGIUNGI IMMAGINE",
                    callback_data="foto_aggiungi",
                )
            ],
            [
                InlineKeyboardButton(
                    "➡️ CONTINUA SENZA IMMAGINE",
                    callback_data="foto_salta",
                )
            ],
        ]
    )

    if update.message:
        await update.message.reply_text(
            "🖼 Vuoi aggiungere un'immagine al post?",
            reply_markup=tastiera,
        )
    else:
        await update.callback_query.message.reply_text(
            "🖼 Vuoi aggiungere un'immagine al post?",
            reply_markup=tastiera,
        )

    return FOTO_SCELTA


async def scelta_immagine(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    if query.data == "foto_salta":
        context.user_data.pop(
            "foto_file_id",
            None,
        )

        await query.edit_message_text(
            "➡️ Continuo senza immagine."
        )

        return await mostra_anteprima(
            update,
            context,
        )

    if query.data == "foto_aggiungi":
        await query.edit_message_text(
            "📷 Inviami la foto del prodotto."
        )
        return FOTO_ATTESA

    return FOTO_SCELTA


async def ricevi_immagine(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message.photo:
        await update.message.reply_text(
            "❌ Inviami una foto valida."
        )
        return FOTO_ATTESA

    foto = update.message.photo[-1]
    context.user_data[
        "foto_file_id"
    ] = foto.file_id

    await update.message.reply_text(
        "✅ Immagine aggiunta."
    )

    return await mostra_anteprima(
        update,
        context,
    )


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
                    "📤 PUBBLICA ORA",
                    callback_data="pubblica",
                )
            ],
            [
                InlineKeyboardButton(
                    "🕒 PROGRAMMA INVIO",
                    callback_data="programma",
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

    foto_file_id = context.user_data.get(
        "foto_file_id"
    )

    if update.message:

        if foto_file_id:
            await update.message.reply_photo(
                photo=foto_file_id,
                caption=testo,
                reply_markup=tastiera,
            )
        else:
            await update.message.reply_text(
                testo,
                reply_markup=tastiera,
            )

    else:

        if foto_file_id:
            await update.callback_query.message.reply_photo(
                photo=foto_file_id,
                caption=testo,
                reply_markup=tastiera,
            )
        else:
            await update.callback_query.message.reply_text(
                testo,
                reply_markup=tastiera,
            )

    return CONFERMA


# =========================================================
# CONTROLLO DISTANZA INVII MANUALI
# =========================================================

def minuti_rimanenti_prima_del_prossimo_invio():

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT pubblicata_il
        FROM recap_offerte
        ORDER BY pubblicata_il DESC
        LIMIT 1
    """)

    riga = cur.fetchone()
    db.close()

    if not riga or not riga[0]:
        return 0

    try:
        ultimo_invio = datetime.fromisoformat(riga[0])

        if ultimo_invio.tzinfo is None:
            ultimo_invio = ultimo_invio.replace(tzinfo=ROMA_TZ)
        else:
            ultimo_invio = ultimo_invio.astimezone(ROMA_TZ)

        trascorsi = (
            datetime.now(ROMA_TZ) - ultimo_invio
        ).total_seconds() / 60

        rimanenti = DISTANZA_MINIMA_MINUTI - trascorsi

        if rimanenti <= 0:
            return 0

        # Arrotondiamo per eccesso: a 30 minuti con limite 31 mostra 1 minuto.
        return max(1, int(rimanenti) + (0 if rimanenti.is_integer() else 1))

    except Exception:
        return 0


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

    # PROGRAMMA INVIO
    if query.data == "programma":

        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📅 OGGI",
                        callback_data="prog_giorno_0",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📅 DOMANI",
                        callback_data="prog_giorno_1",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📅 TRA 2 GIORNI",
                        callback_data="prog_giorno_2",
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

        await query.message.reply_text(
            "📅 PROGRAMMA INVIO\n\n"
            "Scegli il giorno:",
            reply_markup=tastiera,
        )

        return CONFERMA

    # GIORNO SCELTO
    if query.data.startswith("prog_giorno_"):

        try:

            giorni = int(
                query.data.replace(
                    "prog_giorno_",
                    "",
                )
            )

        except ValueError:

            return CONFERMA

        data_scelta = (
            datetime.now(ROMA_TZ).date()
            + timedelta(days=giorni)
        )

        context.user_data[
            "data_programmata"
        ] = data_scelta.isoformat()

        etichetta = (
            "oggi"
            if giorni == 0
            else "domani"
            if giorni == 1
            else "tra 2 giorni"
        )

        eventi = programmazioni_del_giorno(
            data_scelta
        )

        if eventi:

            orari_occupati = ", ".join(
                evento["datetime"].strftime(
                    "%H:%M"
                )
                for evento in eventi
            )

        else:

            orari_occupati = "nessuno"

        suggerito = suggerisci_prossimo_slot(
            data_scelta
        )

        if suggerito:

            suggerimento_testo = (
                "💡 Prossimo spazio consigliato: "
                f"{suggerito.strftime('%H:%M')}\n\n"
            )

        else:

            suggerimento_testo = (
                "⚠️ Non trovo altri spazi "
                "consigliati oggi.\n\n"
            )

        await query.message.reply_text(
            f"🕒 Hai scelto {etichetta}.\n\n"
            f"📅 Orari già programmati: "
            f"{orari_occupati}\n\n"
            f"{suggerimento_testo}"
            "Ora scrivi solo l'orario."
        )

        return PROGRAMMA_ORA

    # ANNULLA
    if query.data == "annulla":
        return await annulla(update, context)

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

        minuti_rimanenti = minuti_rimanenti_prima_del_prossimo_invio()

        if minuti_rimanenti > 0:
            await query.message.reply_text(
                f"⏳ È ancora presto. Attendi ancora {minuti_rimanenti} minuto/i.\n\n"
                f"Tra un post e l'altro devono passare almeno "
                f"{DISTANZA_MINIMA_MINUTI} minuti."
            )
            return CONFERMA

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
                        "🎁 CLUB",
                        url="https://t.me/BestPrice24h_bot",
                    ),
                    InlineKeyboardButton(
                        "🛒 APRI",
                        url=link,
                    )
                ]
            ]
        )

        foto_file_id = context.user_data.get(
            "foto_file_id"
        )

        if foto_file_id:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=foto_file_id,
                caption=messaggio_con_link,
                reply_markup=bottone_offerta,
            )
        else:
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

        salva_offerta_recap(
            nome,
            link,
            context.user_data.get("prezzo"),
            context.user_data.get("vecchio_prezzo", "NO"),
            messaggio=messaggio,
            foto_file_id=foto_file_id,
            template=context.user_data.get("template", "pulito"),
        )

        context.user_data.clear()

        chat_id = query.message.chat_id

        await query.message.delete()

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ OFFERTA PUBBLICATA!\n\n"
                "Cosa vuoi fare adesso?"
            ),
            reply_markup=menu_dopo_pubblicazione(),
        )

        return ConversationHandler.END

    return CONFERMA


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

        testo = "\n\n".join(righe)

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
# INVIA DI NUOVO - STORICO ULTIMI 3 GIORNI
# =========================================================

REINVIO_PER_PAGINA = 6


def leggi_offerte_da_reinviare():

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    limite = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat(timespec="seconds")

    cur.execute("""
        SELECT id, nome, link, prezzo,
               COALESCE(vecchio_prezzo, 'NO'),
               pubblicata_il, messaggio, foto_file_id,
               COALESCE(template, 'pulito')
        FROM recap_offerte
        WHERE pubblicata_il >= ?
        ORDER BY pubblicata_il DESC
    """, (limite,))

    righe = cur.fetchall()
    db.close()
    return righe


def leggi_offerta_da_reinviare(offerta_id):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT id, nome, link, prezzo,
               COALESCE(vecchio_prezzo, 'NO'),
               pubblicata_il, messaggio, foto_file_id,
               COALESCE(template, 'pulito')
        FROM recap_offerte
        WHERE id = ?
    """, (offerta_id,))

    riga = cur.fetchone()
    db.close()
    return riga


async def mostra_reinvio_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query
    await query.answer()

    pagina = 0
    if query.data.startswith("reinvia_pagina_"):
        try:
            pagina = int(query.data.rsplit("_", 1)[1])
        except ValueError:
            pagina = 0

    offerte = leggi_offerte_da_reinviare()

    if not offerte:
        await query.message.reply_text(
            "📭 Non ci sono offerte pubblicate negli ultimi 3 giorni.",
            reply_markup=menu_principale(),
        )
        return

    totale_pagine = max(
        1,
        (len(offerte) + REINVIO_PER_PAGINA - 1) // REINVIO_PER_PAGINA,
    )
    pagina = max(0, min(pagina, totale_pagine - 1))

    inizio = pagina * REINVIO_PER_PAGINA
    offerte_pagina = offerte[inizio:inizio + REINVIO_PER_PAGINA]

    righe = []
    tastiera = []
    pulsanti_numerici = []

    for posizione, offerta in enumerate(offerte_pagina, start=1):
        numero = inizio + posizione
        offerta_id, nome, _, prezzo, _, pubblicata_il, *_ = offerta

        try:
            data = datetime.fromisoformat(pubblicata_il)
            if data.tzinfo is None:
                data = data.replace(tzinfo=timezone.utc)
            data = data.astimezone(ROMA_TZ)
            data_testo = data.strftime("%d/%m %H:%M")
        except Exception:
            data_testo = ""

        nome_breve = accorcia_nome_articolo(nome)

        righe.append(
            f"#{numero}  {nome_breve}\n"
            f"💰 {prezzo} € · 🕒 {data_testo}"
        )

        pulsanti_numerici.append(
            InlineKeyboardButton(
                f"#{numero}",
                callback_data=f"reinvia_scegli_{offerta_id}_{numero}",
            )
        )

    for i in range(0, len(pulsanti_numerici), 3):
        tastiera.append(pulsanti_numerici[i:i + 3])

    nav = []
    if pagina > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️",
                callback_data=f"reinvia_pagina_{pagina - 1}",
            )
        )

    nav.append(
        InlineKeyboardButton(
            f"📄 {pagina + 1}/{totale_pagine}",
            callback_data="reinvia_nop",
        )
    )

    if pagina < totale_pagine - 1:
        nav.append(
            InlineKeyboardButton(
                "➡️",
                callback_data=f"reinvia_pagina_{pagina + 1}",
            )
        )

    tastiera.append(nav)
    tastiera.append([
        InlineKeyboardButton("⬅️ TORNA AL MENU", callback_data="menu_admin")
    ])

    await query.message.reply_text(
        "🔁 INVIA DI NUOVO\n\n"
        "📅 Ultimi 3 giorni · 6 articoli per pagina\n\n"
        + "\n\n".join(righe)
        + "\n\n👇 Scegli il numero dell'articolo.",
        reply_markup=InlineKeyboardMarkup(tastiera),
    )


async def reinvia_nop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def _dati_reinvio(context):
    draft = context.user_data.get("reinvia_draft")
    if draft:
        return draft

    offerta_id = context.user_data.get("reinvia_offerta_id")
    riga = leggi_offerta_da_reinviare(offerta_id)
    if not riga:
        return None

    _, nome, link, prezzo, vecchio_prezzo, _, messaggio_salvato, foto_file_id, template = riga
    draft = {
        "nome": nome,
        "link": link,
        "prezzo": prezzo,
        "vecchio_prezzo": vecchio_prezzo,
        "messaggio_salvato": messaggio_salvato,
        "foto_file_id": foto_file_id,
        "template": template or "pulito",
        "modificato": False,
    }
    context.user_data["reinvia_draft"] = draft
    return draft


def _messaggio_reinvio(draft):
    if not draft:
        return ""
    if not draft.get("modificato") and draft.get("messaggio_salvato"):
        return draft["messaggio_salvato"]
    return crea_messaggio_programmato(
        draft.get("nome", ""),
        draft.get("prezzo", ""),
        draft.get("vecchio_prezzo", "NO"),
        draft.get("template", "pulito"),
    )


async def mostra_anteprima_reinvio(messaggio, context):
    draft = await _dati_reinvio(context)
    if not draft:
        await messaggio.reply_text("❌ Offerta non trovata.")
        return

    numero = context.user_data.get("reinvia_numero", "")
    testo_post = _messaggio_reinvio(draft)
    anteprima = (
        f"🔁 ANTEPRIMA ARTICOLO #{numero}\n\n"
        f"{testo_post}\n\n"
        f"👉 {draft['link']}\n\n"
        "⚡ Prezzo e disponibilità possono variare."
    )

    tastiera = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 RIPUBBLICA ORA", callback_data="reinvia_ora"),
            InlineKeyboardButton("🕒 PROGRAMMA", callback_data="reinvia_programma"),
        ],
        [
            InlineKeyboardButton("✏️ MODIFICA", callback_data="reinvia_modifica"),
        ],
        [
            InlineKeyboardButton("⬅️ TORNA ALLO STORICO", callback_data="reinvia_pagina_0"),
        ],
    ])

    if draft.get("foto_file_id"):
        await messaggio.reply_photo(
            photo=draft["foto_file_id"],
            caption=anteprima,
            reply_markup=tastiera,
        )
    else:
        await messaggio.reply_text(
            anteprima,
            reply_markup=tastiera,
        )


async def scegli_offerta_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query
    await query.answer()

    try:
        _, _, offerta_id, numero = query.data.split("_")
        offerta_id = int(offerta_id)
        numero = int(numero)
    except Exception:
        return

    context.user_data["reinvia_offerta_id"] = offerta_id
    context.user_data["reinvia_numero"] = numero
    context.user_data.pop("reinvia_draft", None)
    context.user_data.pop("reinvia_edit_state", None)

    if not leggi_offerta_da_reinviare(offerta_id):
        await query.message.reply_text("❌ Offerta non trovata.")
        return

    await mostra_anteprima_reinvio(query.message, context)


async def menu_modifica_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "✏️ COSA VUOI MODIFICARE?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📦 NOME", callback_data="reinvia_edit_nome"),
                InlineKeyboardButton("💰 PREZZO", callback_data="reinvia_edit_prezzo"),
            ],
            [
                InlineKeyboardButton("🏷 PREZZO PRIMA", callback_data="reinvia_edit_vecchio"),
                InlineKeyboardButton("🔗 LINK", callback_data="reinvia_edit_link"),
            ],
            [InlineKeyboardButton("🖼 IMMAGINE", callback_data="reinvia_edit_immagine")],
            [InlineKeyboardButton("🎨 TEMPLATE", callback_data="reinvia_edit_template")],
            [InlineKeyboardButton("⬅️ TORNA ALL'ANTEPRIMA", callback_data="reinvia_anteprima")],
        ]),
    )


async def gestisci_modifica_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    draft = await _dati_reinvio(context)
    if not draft:
        return

    if data == "reinvia_anteprima":
        context.user_data.pop("reinvia_edit_state", None)
        await mostra_anteprima_reinvio(query.message, context)
        return

    if data == "reinvia_edit_nome":
        context.user_data["reinvia_edit_state"] = "nome"
        await query.message.reply_text("📦 Scrivi il nuovo nome del prodotto:")
        return

    if data == "reinvia_edit_prezzo":
        context.user_data["reinvia_edit_state"] = "prezzo"
        await query.message.reply_text("💰 Scrivi il nuovo prezzo attuale:")
        return

    if data == "reinvia_edit_vecchio":
        context.user_data["reinvia_edit_state"] = "vecchio"
        await query.message.reply_text("🏷 Scrivi il nuovo prezzo precedente oppure NO:")
        return

    if data == "reinvia_edit_link":
        context.user_data["reinvia_edit_state"] = "link"
        await query.message.reply_text("🔗 Inviami il nuovo link Amazon:")
        return

    if data == "reinvia_edit_immagine":
        if draft.get("foto_file_id"):
            kb = [
                [InlineKeyboardButton("🔄 SOSTITUISCI IMMAGINE", callback_data="reinvia_img_sostituisci")],
                [InlineKeyboardButton("🗑 RIMUOVI IMMAGINE", callback_data="reinvia_img_rimuovi")],
                [InlineKeyboardButton("⬅️ INDIETRO", callback_data="reinvia_modifica")],
            ]
        else:
            kb = [
                [InlineKeyboardButton("📷 AGGIUNGI IMMAGINE", callback_data="reinvia_img_aggiungi")],
                [InlineKeyboardButton("⬅️ INDIETRO", callback_data="reinvia_modifica")],
            ]
        await query.message.reply_text("🖼 GESTIONE IMMAGINE", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data in ("reinvia_img_aggiungi", "reinvia_img_sostituisci"):
        context.user_data["reinvia_attesa_foto"] = True
        await query.message.reply_text("📷 Inviami la nuova immagine.")
        return

    if data == "reinvia_img_rimuovi":
        draft["foto_file_id"] = None
        draft["modificato"] = True
        await query.message.reply_text("✅ Immagine rimossa.")
        await mostra_anteprima_reinvio(query.message, context)
        return

    if data == "reinvia_edit_template":
        await query.message.reply_text(
            "🎨 Scegli il nuovo template:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ PULITO", callback_data="reinvia_tpl_pulito")],
                [InlineKeyboardButton("🚨 AGGRESSIVO", callback_data="reinvia_tpl_aggressivo")],
                [InlineKeyboardButton("⚡ TECH", callback_data="reinvia_tpl_tech")],
            ]),
        )
        return

    if data.startswith("reinvia_tpl_"):
        draft["template"] = data.replace("reinvia_tpl_", "")
        draft["modificato"] = True
        await query.message.reply_text("✅ Template aggiornato.")
        await mostra_anteprima_reinvio(query.message, context)


async def ricevi_modifica_testo_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stato = context.user_data.get("reinvia_edit_state")
    if not stato:
        return

    if not await controlla_autorizzazione(update):
        return

    draft = await _dati_reinvio(context)
    if not draft:
        return

    valore = update.message.text.strip()
    if stato == "nome":
        if not valore:
            await update.message.reply_text("❌ Il nome non può essere vuoto.")
            return
        draft["nome"] = valore
    elif stato == "prezzo":
        draft["prezzo"] = pulisci_prezzo(valore)
    elif stato == "vecchio":
        draft["vecchio_prezzo"] = "NO" if valore.upper() == "NO" else pulisci_prezzo(valore)
    elif stato == "link":
        if "amazon." not in valore and "amzn." not in valore:
            await update.message.reply_text("❌ Mandami un link Amazon valido.")
            return
        draft["link"] = valore

    draft["modificato"] = True
    context.user_data.pop("reinvia_edit_state", None)
    await update.message.reply_text("✅ Modifica salvata.")
    await mostra_anteprima_reinvio(update.message, context)


async def ricevi_foto_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("reinvia_attesa_foto"):
        return
    if not await controlla_autorizzazione(update):
        return

    draft = await _dati_reinvio(context)
    if not draft:
        return

    draft["foto_file_id"] = update.message.photo[-1].file_id
    draft["modificato"] = True
    context.user_data.pop("reinvia_attesa_foto", None)
    await update.message.reply_text("✅ Immagine aggiornata.")
    await mostra_anteprima_reinvio(update.message, context)


async def reinvia_offerta_storica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query
    await query.answer()

    minuti_rimanenti = minuti_rimanenti_prima_del_prossimo_invio()
    if minuti_rimanenti > 0:
        await query.message.reply_text(
            f"⏳ Attendi ancora {minuti_rimanenti} minuto/i.\n\n"
            f"Tra un post e l'altro devono passare almeno {DISTANZA_MINIMA_MINUTI} minuti."
        )
        return

    draft = await _dati_reinvio(context)
    if not draft:
        await query.message.reply_text("❌ Offerta non trovata.")
        return

    messaggio = _messaggio_reinvio(draft)
    messaggio_con_link = (
        f"{messaggio}\n\n👉 {draft['link']}\n\n"
        "⚡ Prezzo e disponibilità possono variare."
    )
    bottoni = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 CLUB", url="https://t.me/BestPrice24h_bot"),
        InlineKeyboardButton("🛒 APRI", url=draft["link"]),
    ]])

    if draft.get("foto_file_id"):
        await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=draft["foto_file_id"],
            caption=messaggio_con_link,
            reply_markup=bottoni,
        )
    else:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=messaggio_con_link,
            reply_markup=bottoni,
        )

    salva_offerta_recap(
        draft["nome"], draft["link"], draft["prezzo"], draft.get("vecchio_prezzo", "NO"),
        messaggio=messaggio,
        foto_file_id=draft.get("foto_file_id"),
        template=draft.get("template", "pulito"),
    )

    numero = context.user_data.get("reinvia_numero")
    for chiave in ("reinvia_offerta_id", "reinvia_numero", "reinvia_draft", "reinvia_edit_state", "reinvia_attesa_foto"):
        context.user_data.pop(chiave, None)

    await query.message.reply_text(
        f"✅ OFFERTA #{numero} INVIATA DI NUOVO!",
        reply_markup=menu_dopo_pubblicazione(),
    )


async def prepara_programmazione_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collega INVIA DI NUOVO allo stesso flusso calendario dei post normali."""
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    draft = await _dati_reinvio(context)
    if not draft:
        await query.message.reply_text("❌ Dati dell'offerta mancanti. Riprova.")
        return ConversationHandler.END

    # Copia il draft nei campi standard usati dalla programmazione normale.
    context.user_data["nome"] = draft["nome"]
    context.user_data["link"] = draft["link"]
    context.user_data["prezzo"] = draft["prezzo"]
    context.user_data["vecchio_prezzo"] = draft.get("vecchio_prezzo", "NO")
    context.user_data["template"] = draft.get("template", "pulito")
    context.user_data["foto_file_id"] = draft.get("foto_file_id")
    context.user_data["messaggio"] = _messaggio_reinvio(draft)
    context.user_data["programmazione_da_reinvio"] = True

    tastiera = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 OGGI", callback_data="prog_giorno_0")],
            [InlineKeyboardButton("📅 DOMANI", callback_data="prog_giorno_1")],
            [InlineKeyboardButton("📅 TRA 2 GIORNI", callback_data="prog_giorno_2")],
            [InlineKeyboardButton("❌ ANNULLA", callback_data="annulla")],
        ]
    )

    await query.message.reply_text(
        "📅 PROGRAMMA INVIO\n\n"
        "Stai usando lo stesso calendario dei POST PROGRAMMATI.\n"
        "Scegli il giorno:",
        reply_markup=tastiera,
    )

    # Da qui prosegue esattamente negli stati standard CONFERMA -> PROGRAMMA_ORA.
    return CONFERMA


async def scegli_giorno_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    giorni = int(query.data.rsplit("_", 1)[1])
    data = datetime.now(ROMA_TZ).date() + timedelta(days=giorni)
    context.user_data["reinvia_data"] = data.isoformat()
    context.user_data["attesa_ora_reinvio"] = True
    await query.message.reply_text(
        f"📅 {data.strftime('%d/%m/%Y')}\n\n🕒 Scrivi l'orario nel formato HH:MM."
    )


async def ricevi_ora_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Prima gestisce eventuali modifiche testuali dell'offerta storica.
    if context.user_data.get("reinvia_edit_state"):
        await ricevi_modifica_testo_reinvio(update, context)
        return

    if not context.user_data.get("attesa_ora_reinvio"):
        return

    # Se è stato selezionato un post programmato, questo handler non deve
    # mai interpretare il testo come orario.
    if context.user_data.get("prog_id"):
        return

    if not await controlla_autorizzazione(update):
        return

    try:
        ora = datetime.strptime(update.message.text.strip(), "%H:%M").time()
    except ValueError:
        await update.message.reply_text("❌ Orario non corretto. Scrivilo nel formato HH:MM.")
        return

    data_iso = context.user_data.get("reinvia_data")
    draft = await _dati_reinvio(context)
    if not draft or not data_iso:
        await update.message.reply_text("❌ Dati mancanti. Riprova.")
        return

    data = datetime.fromisoformat(data_iso).date()
    data_locale = datetime.combine(data, ora, tzinfo=ROMA_TZ)

    if data_locale <= datetime.now(ROMA_TZ):
        await update.message.reply_text("❌ Questo orario è già passato. Inserisci un orario futuro.")
        return

    conflitti = trova_conflitto(data_locale)
    if conflitti:
        vicino = conflitti[0]
        await update.message.reply_text(
            "⚠️ POST TROPPO VICINO\n\n"
            f"Hai già un'offerta alle {vicino['datetime'].strftime('%H:%M')}.\n"
            f"Scegli un orario distante almeno {DISTANZA_MINIMA_MINUTI} minuti."
        )
        return

    messaggio = _messaggio_reinvio(draft)
    programmazione_id, invio_previsto = salva_programmazione(
        draft["nome"], messaggio, draft["link"], draft["prezzo"], data_locale
    )
    salva_foto_programmazione(programmazione_id, draft.get("foto_file_id"))

    numero = context.user_data.get("reinvia_numero")
    for chiave in ("reinvia_offerta_id", "reinvia_numero", "reinvia_draft", "reinvia_data", "attesa_ora_reinvio", "reinvia_edit_state", "reinvia_attesa_foto"):
        context.user_data.pop(chiave, None)

    await update.message.reply_text(
        f"✅ OFFERTA #{numero} PROGRAMMATA!\n\n"
        f"📅 {invio_previsto.strftime('%d/%m/%Y')}\n"
        f"🕒 {invio_previsto.strftime('%H:%M')}\n"
        f"📦 {draft['nome']}\n"
        f"💰 {draft['prezzo']} €\n\n"
        f"🆔 Programmazione: #{programmazione_id}",
        reply_markup=menu_principale(),
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

    # Funziona sia con /annulla sia con il pulsante inline ANNULLA.
    if update.callback_query:
        query = update.callback_query

        try:
            await query.edit_message_text(
                "❌ Operazione annullata.",
                reply_markup=menu_principale(),
            )
        except Exception:
            await query.message.reply_text(
                "❌ Operazione annullata.",
                reply_markup=menu_principale(),
            )

    elif update.message:
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
    inizializza_programmazioni()
    inizializza_recap()
    inizializza_automazione()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .post_init(avvia_programmazioni)
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

            CallbackQueryHandler(
                prepara_programmazione_reinvio,
                pattern="^reinvia_programma$",
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

            PROGRAMMA_ORA: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_ora_programmazione,
                )
            ],

            CONFERMA_ORARIO: [
                CallbackQueryHandler(
                    conferma_orario_vicino,
                    pattern=(
                        "^(conferma_orario_vicino|"
                        "cambia_orario)$"
                    ),
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

            FOTO_SCELTA: [
                CallbackQueryHandler(
                    scelta_immagine,
                    pattern="^(foto_aggiungi|foto_salta)$",
                )
            ],

            FOTO_ATTESA: [
                MessageHandler(
                    filters.PHOTO,
                    ricevi_immagine,
                )
            ],

            CONFERMA: [
                CallbackQueryHandler(
                    conferma,
                    pattern=(
                        "^(pubblica|"
                        "programma|"
                        "prog_giorno_0|"
                        "prog_giorno_1|"
                        "prog_giorno_2|"
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

    configurazione_automatica = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                richiedi_intervallo_automatico,
                pattern="^auto_intervallo$",
            ),
            CallbackQueryHandler(
                richiedi_fascia_automatica,
                pattern="^auto_fascia$",
            ),
        ],
        states={
            AUTO_INTERVALLO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_intervallo_automatico,
                )
            ],
            AUTO_FASCIA: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_fascia_automatica,
                )
            ],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
        allow_reentry=True,
    )

    app.add_handler(configurazione_automatica)

    app.add_handler(
        CallbackQueryHandler(
            menu_automazione,
            pattern="^auto_menu$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_automazione,
            pattern=r"^(auto_toggle|auto_sconto|auto_disc_[0-9]+|auto_categorie|auto_cat_[a-z]+)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            testa_ricerca_automatica,
            pattern="^auto_test$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            ultime,
            pattern="^ultime$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            mostra_reinvio_menu,
            pattern=r"^(reinvia_menu|reinvia_pagina_[0-9]+)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            reinvia_nop,
            pattern="^reinvia_nop$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            scegli_offerta_reinvio,
            pattern=r"^reinvia_scegli_[0-9]+_[0-9]+$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            reinvia_offerta_storica,
            pattern="^reinvia_ora$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            menu_modifica_reinvio,
            pattern="^reinvia_modifica$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_modifica_reinvio,
            pattern=(
                r"^(reinvia_anteprima|reinvia_edit_nome|reinvia_edit_prezzo|"
                r"reinvia_edit_vecchio|reinvia_edit_link|reinvia_edit_immagine|"
                r"reinvia_img_aggiungi|reinvia_img_sostituisci|reinvia_img_rimuovi|"
                r"reinvia_edit_template|reinvia_tpl_pulito|reinvia_tpl_aggressivo|reinvia_tpl_tech)$"
            ),
        )
    )


    gestione_programmati = ConversationHandler(

        entry_points=[
            CallbackQueryHandler(
                mostra_programmati,
                pattern="^programmati$",
            )
        ],

        states={

            PROG_SELEZIONE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    seleziona_programmato,
                ),
                CallbackQueryHandler(
                    esci_programmati,
                    pattern="^prog_esci$",
                ),
            ],

            PROG_GESTIONE: [
                CallbackQueryHandler(
                    gestisci_programmato,
                    pattern=(
                        "^(prog_modifica|"
                        "prog_elimina|"
                        "prog_elimina_si|"
                        "prog_elimina_no|"
                        "prog_indietro)$"
                    ),
                ),
            ],

            PROG_MODIFICA_MENU: [
                CallbackQueryHandler(
                    menu_modifica_programmato,
                    pattern=(
                        "^(prog_edit_nome|prog_edit_immagine|"
                        "prog_edit_prezzo|"
                        "prog_edit_vecchio|"
                        "prog_edit_link|"
                        "prog_edit_dataora|"
                        "prog_edit_template|"
                        "prog_tpl_pulito|"
                        "prog_tpl_aggressivo|"
                        "prog_tpl_tech|"
                        "prog_torna_scheda)$"
                    ),
                ),
            ],

            PROG_EDIT_NOME: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_nome,
                )
            ],

            PROG_EDIT_PREZZO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_prezzo,
                )
            ],

            PROG_EDIT_VECCHIO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_vecchio,
                )
            ],

            PROG_EDIT_LINK: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_link,
                )
            ],

            PROG_EDIT_DATA_ORA: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_dataora,
                )
            ],

            PROG_IMMAGINE_MENU: [
                CallbackQueryHandler(
                    gestisci_immagine_programmata,
                    pattern=(
                        "^(prog_img_aggiungi|"
                        "prog_img_sostituisci|"
                        "prog_img_rimuovi|"
                        "prog_img_indietro)$"
                    ),
                )
            ],

            PROG_IMMAGINE_ATTESA: [
                MessageHandler(
                    filters.PHOTO,
                    ricevi_immagine_programmata,
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
        gestione_programmati
    )

    # Deve stare dopo gestione_programmati: altrimenti intercetta
    # il numero digitato per modificare un post programmato.
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            ricevi_ora_reinvio,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            ricevi_foto_reinvio,
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

    app.add_handler(
        CallbackQueryHandler(
            torna_menu_admin,
            pattern="^menu_admin$",
        )
    )


    app.add_handler(
        CallbackQueryHandler(
            mostra_categorie,
            pattern="^categorie$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            categoria_work_in_progress,
            pattern=r"^wip_",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            torna_menu_utente,
            pattern="^menu_utente$",
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
