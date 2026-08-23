import os
import sqlite3
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# =========================================================
# CONFIGURAZIONE CLUB
# =========================================================

DB_PATH = os.environ.get("CLUB_DB_PATH", "club.db")

CHANNEL_ID = os.environ["TELEGRAM_CHAT_ID"]

CHANNEL_URL = os.environ.get(
    "TELEGRAM_CHANNEL_URL",
    "https://t.me/TUO_CANALE"
)

ADMIN_ID = os.environ.get("ADMIN_TELEGRAM_ID")

PUNTI_INVITO = 2
GIORNI_VERIFICA = 7
MAX_INVITI_MESE = 5


# =========================================================
# DATABASE
# =========================================================

def connessione():
    return sqlite3.connect(DB_PATH)


def inizializza_database():

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS utenti (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            nome TEXT,
            punti INTEGER DEFAULT 0,
            invitato_da INTEGER,
            data_iscrizione TEXT,
            attivita INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inviti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invitante_id INTEGER NOT NULL,
            invitato_id INTEGER UNIQUE NOT NULL,
            data_invito TEXT NOT NULL,
            data_verifica TEXT,
            stato TEXT DEFAULT 'attesa'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS premi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            punti_usati INTEGER NOT NULL,
            valore_euro INTEGER NOT NULL,
            stato TEXT DEFAULT 'attesa',
            data_richiesta TEXT NOT NULL
        )
    """)

    db.commit()
    db.close()


# =========================================================
# UTENTI
# =========================================================

def utente_esiste(user_id):

    db = connessione()
    cur = db.cursor()

    cur.execute(
        "SELECT telegram_id FROM utenti WHERE telegram_id = ?",
        (user_id,)
    )

    risultato = cur.fetchone()

    db.close()

    return risultato is not None


def registra_utente(user, invitato_da=None):

    nuovo = not utente_esiste(user.id)

    db = connessione()
    cur = db.cursor()

    if nuovo:

        if invitato_da == user.id:
            invitato_da = None

        # L'invitante deve già esistere
        if invitato_da and not utente_esiste(invitato_da):
            invitato_da = None

        cur.execute("""
            INSERT INTO utenti (
                telegram_id,
                username,
                nome,
                punti,
                invitato_da,
                data_iscrizione,
                attivita
            )
            VALUES (?, ?, ?, 0, ?, ?, 1)
        """, (
            user.id,
            user.username,
            user.first_name,
            invitato_da,
            datetime.now().isoformat(),
        ))

        if invitato_da:

            cur.execute("""
                INSERT OR IGNORE INTO inviti (
                    invitante_id,
                    invitato_id,
                    data_invito,
                    stato
                )
                VALUES (?, ?, ?, 'attesa')
            """, (
                invitato_da,
                user.id,
                datetime.now().isoformat(),
            ))

    else:

        cur.execute("""
            UPDATE utenti
            SET username = ?,
                nome = ?,
                attivita = attivita + 1
            WHERE telegram_id = ?
        """, (
            user.username,
            user.first_name,
            user.id,
        ))

    db.commit()
    db.close()

    return nuovo


def aggiungi_attivita(user_id):

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        UPDATE utenti
        SET attivita = attivita + 1
        WHERE telegram_id = ?
    """, (user_id,))

    db.commit()
    db.close()


def get_punti(user_id):

    db = connessione()
    cur = db.cursor()

    cur.execute(
        "SELECT punti FROM utenti WHERE telegram_id = ?",
        (user_id,)
    )

    risultato = cur.fetchone()

    db.close()

    if not risultato:
        return 0

    return risultato[0]


# =========================================================
# MENU UTENTE
# =========================================================

def menu_club():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⭐ I MIEI PUNTI",
                callback_data="club_punti"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 INVITA AMICI",
                callback_data="club_invita"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 PREMI",
                callback_data="club_premi"
            )
        ],
        [
            InlineKeyboardButton(
                "🔥 VAI AL CANALE",
                url=CHANNEL_URL
            )
        ],
    ])


# =========================================================
# VERIFICA INVITI
# =========================================================

def inviti_premiati_questo_mese(user_id):

    oggi = datetime.now()

    mese = f"{oggi.year:04d}-{oggi.month:02d}"

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
        WHERE invitante_id = ?
          AND stato = 'verificato'
          AND substr(data_verifica, 1, 7) = ?
    """, (
        user_id,
        mese,
    ))

    numero = cur.fetchone()[0]

    db.close()

    return numero


async def verifica_inviti(bot, invitante_id):

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT
            inviti.id,
            inviti.invitato_id,
            inviti.data_invito,
            utenti.attivita
        FROM inviti
        JOIN utenti
        ON utenti.telegram_id = inviti.invitato_id
        WHERE inviti.invitante_id = ?
          AND inviti.stato = 'attesa'
    """, (invitante_id,))

    inviti = cur.fetchall()

    db.close()

    nuovi_punti = 0

    for invito_id, invitato_id, data_invito, attivita in inviti:

        data = datetime.fromisoformat(data_invito)

        # Devono essere passati almeno 7 giorni
        if datetime.now() < data + timedelta(days=GIORNI_VERIFICA):
            continue

        # Deve aver utilizzato il bot almeno due volte
        if attivita < 2:
            continue

        # Massimo 5 referral premiati al mese
        if inviti_premiati_questo_mese(invitante_id) >= MAX_INVITI_MESE:
            break

        try:

            membro = await bot.get_chat_member(
                chat_id=CHANNEL_ID,
                user_id=invitato_id
            )

            if membro.status not in (
                "member",
                "administrator",
                "creator",
            ):
                continue

        except Exception as errore:

            print(
                f"Errore verifica membro {invitato_id}: {errore}"
            )

            continue

        db = connessione()
        cur = db.cursor()

        # Ricontrollo stato per evitare doppio accredito
        cur.execute("""
            SELECT stato
            FROM inviti
            WHERE id = ?
        """, (invito_id,))

        stato = cur.fetchone()

        if not stato or stato[0] != "attesa":
            db.close()
            continue

        cur.execute("""
            UPDATE inviti
            SET stato = 'verificato',
                data_verifica = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(),
            invito_id,
        ))

        cur.execute("""
            UPDATE utenti
            SET punti = punti + ?
            WHERE telegram_id = ?
        """, (
            PUNTI_INVITO,
            invitante_id,
        ))

        db.commit()
        db.close()

        nuovi_punti += PUNTI_INVITO

    return nuovi_punti


# =========================================================
# I MIEI PUNTI
# =========================================================

async def mostra_punti(update, context):

    query = update.callback_query

    await query.answer()

    user_id = update.effective_user.id

    aggiungi_attivita(user_id)

    nuovi = await verifica_inviti(
        context.bot,
        user_id
    )

    punti = get_punti(user_id)

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
        WHERE invitante_id = ?
          AND stato = 'attesa'
    """, (user_id,))

    in_attesa = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
        WHERE invitante_id = ?
          AND stato = 'verificato'
    """, (user_id,))

    verificati = cur.fetchone()[0]

    db.close()

    testo = (
        "⭐ IL TUO SALDO\n\n"
        f"💰 Punti disponibili: {punti}\n\n"
        f"✅ Amici verificati: {verificati}\n"
        f"⏳ Inviti in attesa: {in_attesa}\n"
    )

    if nuovi:
        testo += (
            f"\n🎉 Hai appena ricevuto +{nuovi} punti "
            "per nuovi inviti verificati!"
        )

    await query.message.reply_text(
        testo,
        reply_markup=menu_club()
    )


# =========================================================
# INVITA AMICI
# =========================================================

async def invita_amici(update, context):

    query = update.callback_query

    await query.answer()

    aggiungi_attivita(
        update.effective_user.id
    )

    bot_info = await context.bot.get_me()

    user_id = update.effective_user.id

    link = (
        f"https://t.me/{bot_info.username}"
        f"?start={user_id}"
    )

    testo = (
        "👥 INVITA UN AMICO\n\n"
        "Condividi il tuo link personale:\n\n"
        f"{link}\n\n"
        f"🎁 Ricevi {PUNTI_INVITO} punti "
        "quando l'amico viene verificato.\n\n"
        f"⏳ La verifica avviene dopo "
        f"{GIORNI_VERIFICA} giorni.\n\n"
        "L'amico deve essere ancora iscritto "
        "al canale e aver utilizzato realmente il bot.\n\n"
        f"📌 Massimo {MAX_INVITI_MESE} "
        "inviti premiati al mese."
    )

    await query.message.reply_text(
        testo,
        reply_markup=menu_club()
    )


# =========================================================
# PREMI
# =========================================================

async def mostra_premi(update, context):

    query = update.callback_query

    await query.answer()

    user_id = update.effective_user.id

    aggiungi_attivita(user_id)

    punti = get_punti(user_id)

    tastiera = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 5 € — 25 punti",
                callback_data="premio_5"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 10 € — 50 punti",
                callback_data="premio_10"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ TORNA AL CLUB",
                callback_data="club_home"
            )
        ],
    ])

    await query.message.reply_text(
        "🎁 PREMI\n\n"
        f"⭐ Hai {punti} punti.\n\n"
        "Puoi richiedere:\n\n"
        "🎫 Buono Amazon 5 € → 25 punti\n"
        "🎫 Buono Amazon 10 € → 50 punti\n\n"
        "Il premio verrà controllato e inviato "
        "manualmente dall'amministratore.",
        reply_markup=tastiera
    )


# =========================================================
# RICHIESTA PREMIO
# =========================================================

async def richiedi_premio(update, context):

    query = update.callback_query

    await query.answer()

    user = update.effective_user

    if query.data == "premio_5":
        valore = 5
        costo = 25

    elif query.data == "premio_10":
        valore = 10
        costo = 50

    else:
        return

    punti = get_punti(user.id)

    if punti < costo:

        await query.answer(
            f"Ti servono {costo} punti.",
            show_alert=True
        )

        return

    db = connessione()
    cur = db.cursor()

    # Scala immediatamente i punti
    # così non può richiedere più premi
    # usando lo stesso saldo.
    cur.execute("""
        UPDATE utenti
        SET punti = punti - ?
        WHERE telegram_id = ?
          AND punti >= ?
    """, (
        costo,
        user.id,
        costo,
    ))

    if cur.rowcount == 0:

        db.close()

        await query.answer(
            "Punti insufficienti.",
            show_alert=True
        )

        return

    cur.execute("""
        INSERT INTO premi (
            telegram_id,
            punti_usati,
            valore_euro,
            stato,
            data_richiesta
        )
        VALUES (?, ?, ?, 'attesa', ?)
    """, (
        user.id,
        costo,
        valore,
        datetime.now().isoformat(),
    ))

    premio_id = cur.lastrowid

    db.commit()
    db.close()

    await query.message.reply_text(
        "🎉 RICHIESTA INVIATA!\n\n"
        f"🎁 Premio: Buono Amazon {valore} €\n"
        f"⭐ Punti utilizzati: {costo}\n\n"
        "Riceverai il premio dopo "
        "l'approvazione dell'amministratore."
    )

    if ADMIN_ID:

        username = (
            f"@{user.username}"
            if user.username
            else "nessun username"
        )

        tastiera_admin = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ APPROVA",
                    callback_data=f"approva_premio_{premio_id}"
                ),
                InlineKeyboardButton(
                    "❌ RIFIUTA",
                    callback_data=f"rifiuta_premio_{premio_id}"
                )
            ]
        ])

        await context.bot.send_message(
            chat_id=int(ADMIN_ID),
            text=(
                "🎁 NUOVA RICHIESTA PREMIO\n\n"
                f"👤 {user.first_name}\n"
                f"🔗 {username}\n"
                f"🆔 {user.id}\n\n"
                f"🎫 Buono Amazon: {valore} €\n"
                f"⭐ Punti utilizzati: {costo}"
            ),
            reply_markup=tastiera_admin
        )


# =========================================================
# APPROVA / RIFIUTA PREMIO
# =========================================================

async def gestisci_premio_admin(update, context):

    query = update.callback_query

    if str(update.effective_user.id) != str(ADMIN_ID):

        await query.answer(
            "Non autorizzato.",
            show_alert=True
        )

        return

    await query.answer()

    parti = query.data.split("_")

    azione = parti[0]
    premio_id = int(parti[-1])

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT telegram_id,
               punti_usati,
               valore_euro,
               stato
        FROM premi
        WHERE id = ?
    """, (premio_id,))

    premio = cur.fetchone()

    if not premio:

        db.close()
        return

    user_id, punti, valore, stato = premio

    if stato != "attesa":

        db.close()

        await query.answer(
            "Richiesta già gestita.",
            show_alert=True
        )

        return

    if azione == "approva":

        cur.execute("""
            UPDATE premi
            SET stato = 'approvato'
            WHERE id = ?
        """, (premio_id,))

        db.commit()
        db.close()

        await query.edit_message_text(
            "✅ PREMIO APPROVATO\n\n"
            f"🎫 Buono: {valore} €\n"
            f"👤 Telegram ID: {user_id}\n\n"
            "Ora puoi inviare il codice del "
            "buono all'utente."
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 Il tuo premio è stato approvato!\n\n"
                f"🎁 Buono Amazon da {valore} €\n\n"
                "L'amministratore ti invierà "
                "il premio."
            )
        )

    elif azione == "rifiuta":

        # Restituisce i punti
        cur.execute("""
            UPDATE utenti
            SET punti = punti + ?
            WHERE telegram_id = ?
        """, (
            punti,
            user_id,
        ))

        cur.execute("""
            UPDATE premi
            SET stato = 'rifiutato'
            WHERE id = ?
        """, (premio_id,))

        db.commit()
        db.close()

        await query.edit_message_text(
            "❌ PREMIO RIFIUTATO\n\n"
            f"⭐ {punti} punti restituiti "
            "all'utente."
        )

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ La richiesta premio non è stata "
                "approvata.\n\n"
                f"⭐ I tuoi {punti} punti sono stati "
                "restituiti."
            )
        )


# =========================================================
# HOME CLUB
# =========================================================

async def club_home(update, context):

    query = update.callback_query

    await query.answer()

    aggiungi_attivita(
        update.effective_user.id
    )

    await query.message.reply_text(
        "🔥 CLUB OFFERTE\n\n"
        "Cosa vuoi fare?",
        reply_markup=menu_club()
    )
