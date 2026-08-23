import os
import sqlite3
from datetime import datetime, timedelta

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


# =========================================================
# CONFIGURAZIONE CLUB
# =========================================================

DB_PATH = os.environ.get(
    "CLUB_DB_PATH",
    "club.db"
)

CHANNEL_ID = os.environ["TELEGRAM_CHAT_ID"]

CHANNEL_URL = os.environ.get(
    "TELEGRAM_CHANNEL_URL",
    "https://t.me/TUO_CANALE"
)

ADMIN_ID = os.environ.get(
    "ADMIN_TELEGRAM_ID"
)

# 2 punti per ogni amico verificato
PUNTI_INVITO = 2

# L'amico viene verificato dopo 7 giorni
GIORNI_VERIFICA = 7

# Massimo 5 amici premiati al mese
MAX_INVITI_MESE = 5

# Premio principale
PREMIO_5_EURO_PUNTI = 10


# =========================================================
# DATABASE
# =========================================================

def connessione():

    db = sqlite3.connect(DB_PATH)

    return db


def ora():

    return datetime.now().isoformat(
        timespec="seconds"
    )


def inizializza_database():

    db = connessione()
    cur = db.cursor()

    # UTENTI
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

    # INVITI
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

    # PREMI
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

    # STORICO PUNTI
    cur.execute("""
        CREATE TABLE IF NOT EXISTS movimenti_punti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            variazione INTEGER NOT NULL,
            motivo TEXT NOT NULL,
            data_movimento TEXT NOT NULL
        )
    """)

    db.commit()

    # Se esistono utenti della V1 che avevano già punti,
    # registriamo una voce iniziale nello storico.
    cur.execute("""
        SELECT telegram_id, punti
        FROM utenti
        WHERE punti != 0
    """)

    utenti_con_punti = cur.fetchall()

    for user_id, punti in utenti_con_punti:

        cur.execute("""
            SELECT COUNT(*)
            FROM movimenti_punti
            WHERE telegram_id = ?
        """, (user_id,))

        numero = cur.fetchone()[0]

        if numero == 0:

            cur.execute("""
                INSERT INTO movimenti_punti (
                    telegram_id,
                    variazione,
                    motivo,
                    data_movimento
                )
                VALUES (?, ?, ?, ?)
            """, (
                user_id,
                punti,
                "Saldo iniziale V2",
                ora(),
            ))

    db.commit()
    db.close()


# =========================================================
# SICUREZZA ADMIN
# =========================================================

def e_admin(user_id):

    if not ADMIN_ID:
        return False

    return str(user_id) == str(ADMIN_ID)


async def verifica_admin(update):

    user = update.effective_user

    if (
        not user
        or not e_admin(user.id)
    ):

        if update.callback_query:

            await update.callback_query.answer(
                "⛔ Non autorizzato.",
                show_alert=True,
            )

        return False

    return True


# =========================================================
# UTENTI
# =========================================================

def utente_esiste(user_id):

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT telegram_id
        FROM utenti
        WHERE telegram_id = ?
    """, (user_id,))

    risultato = cur.fetchone()

    db.close()

    return risultato is not None


def registra_utente(
    user,
    invitato_da=None,
):

    nuovo = not utente_esiste(user.id)

    db = connessione()
    cur = db.cursor()

    if nuovo:

        # Non può invitare se stesso
        if invitato_da == user.id:
            invitato_da = None

        # L'invitante deve essere già registrato
        if (
            invitato_da
            and not utente_esiste(invitato_da)
        ):
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
            ora(),
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
                ora(),
            ))

    else:

        cur.execute("""
            UPDATE utenti
            SET
                username = ?,
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

    cur.execute("""
        SELECT punti
        FROM utenti
        WHERE telegram_id = ?
    """, (user_id,))

    risultato = cur.fetchone()

    db.close()

    if not risultato:
        return 0

    return risultato[0]


# =========================================================
# MODIFICA PUNTI + STORICO
# =========================================================

def modifica_punti(
    user_id,
    variazione,
    motivo,
):

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT punti
        FROM utenti
        WHERE telegram_id = ?
    """, (user_id,))

    risultato = cur.fetchone()

    if not risultato:

        db.close()
        return False

    saldo_attuale = risultato[0]

    nuovo_saldo = (
        saldo_attuale
        + variazione
    )

    # Il saldo non può diventare negativo
    if nuovo_saldo < 0:

        db.close()
        return False

    cur.execute("""
        UPDATE utenti
        SET punti = ?
        WHERE telegram_id = ?
    """, (
        nuovo_saldo,
        user_id,
    ))

    cur.execute("""
        INSERT INTO movimenti_punti (
            telegram_id,
            variazione,
            motivo,
            data_movimento
        )
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        variazione,
        motivo,
        ora(),
    ))

    db.commit()
    db.close()

    return True


# =========================================================
# MENU UTENTE
# =========================================================

def menu_club():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⭐ I MIEI PUNTI",
                callback_data="club_punti",
            )
        ],
        [
            InlineKeyboardButton(
                "👥 INVITA AMICI",
                callback_data="club_invita",
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 PREMI",
                callback_data="club_premi",
            )
        ],
        [
            InlineKeyboardButton(
                "🔥 VAI AL CANALE",
                url=CHANNEL_URL,
            )
        ],
    ])


# =========================================================
# INVITI PREMIATI NEL MESE
# =========================================================

def inviti_premiati_questo_mese(user_id):

    oggi = datetime.now()

    mese = (
        f"{oggi.year:04d}-"
        f"{oggi.month:02d}"
    )

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


# =========================================================
# VERIFICA INVITI
# =========================================================

async def verifica_inviti(
    bot,
    invitante_id,
):

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

        WHERE
            inviti.invitante_id = ?
            AND inviti.stato = 'attesa'
    """, (invitante_id,))

    inviti = cur.fetchall()

    db.close()

    nuovi_punti = 0

    for (
        invito_id,
        invitato_id,
        data_invito,
        attivita,
    ) in inviti:

        data = datetime.fromisoformat(
            data_invito
        )

        # Devono essere trascorsi almeno 7 giorni
        if (
            datetime.now()
            < data + timedelta(
                days=GIORNI_VERIFICA
            )
        ):
            continue

        # L'amico deve aver usato il bot
        # almeno due volte.
        if attivita < 2:
            continue

        # Massimo 5 amici premiati al mese
        if (
            inviti_premiati_questo_mese(
                invitante_id
            )
            >= MAX_INVITI_MESE
        ):
            break

        # Deve essere ancora iscritto al canale
        try:

            membro = await bot.get_chat_member(
                chat_id=CHANNEL_ID,
                user_id=invitato_id,
            )

            if membro.status not in (
                "member",
                "administrator",
                "creator",
            ):
                continue

        except Exception as errore:

            print(
                "Errore verifica membro "
                f"{invitato_id}: {errore}"
            )

            continue

        db = connessione()
        cur = db.cursor()

        # Anti doppio accredito
        cur.execute("""
            SELECT stato
            FROM inviti
            WHERE id = ?
        """, (invito_id,))

        stato = cur.fetchone()

        if (
            not stato
            or stato[0] != "attesa"
        ):

            db.close()
            continue

        cur.execute("""
            UPDATE inviti
            SET
                stato = 'verificato',
                data_verifica = ?
            WHERE id = ?
        """, (
            ora(),
            invito_id,
        ))

        db.commit()
        db.close()

        successo = modifica_punti(
            invitante_id,
            PUNTI_INVITO,
            (
                "Amico verificato "
                f"(utente {invitato_id})"
            ),
        )

        if successo:

            nuovi_punti += PUNTI_INVITO

    return nuovi_punti


# =========================================================
# I MIEI PUNTI
# =========================================================

async def mostra_punti(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    user_id = update.effective_user.id

    aggiungi_attivita(
        user_id
    )

    nuovi = await verifica_inviti(
        context.bot,
        user_id,
    )

    punti = get_punti(
        user_id
    )

    db = connessione()
    cur = db.cursor()

    # Inviti ancora in attesa
    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
        WHERE
            invitante_id = ?
            AND stato = 'attesa'
    """, (user_id,))

    in_attesa = cur.fetchone()[0]

    # Totale inviti verificati
    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
        WHERE
            invitante_id = ?
            AND stato = 'verificato'
    """, (user_id,))

    verificati_totali = cur.fetchone()[0]

    db.close()

    # Quanti amici sono stati premiati questo mese
    premiati_mese = inviti_premiati_questo_mese(
        user_id
    )

    # Quanti amici restano premiabili questo mese
    amici_rimanenti = max(
        0,
        MAX_INVITI_MESE - premiati_mese
    )

    # Quanti punti può ancora ottenere questo mese
    punti_ancora_mese = (
        amici_rimanenti
        * PUNTI_INVITO
    )

    # Quanto manca al buono da 5 €
    punti_mancanti_premio = max(
        0,
        PREMIO_5_EURO_PUNTI - punti
    )

    testo = (
        "⭐ I TUOI PUNTI\n\n"
        f"💰 Saldo: {punti} punti\n\n"

        f"👥 Amici premiati questo mese: "
        f"{premiati_mese}/{MAX_INVITI_MESE}\n"

        f"🎯 Puoi ottenere ancora "
        f"{punti_ancora_mese} punti questo mese\n\n"

        f"✅ Amici verificati totali: "
        f"{verificati_totali}\n"

        f"⏳ Amici in attesa: "
        f"{in_attesa}\n\n"

        "🎁 Prossimo premio:\n"
        "Buono Amazon da 5 €\n"
        f"⭐ Servono {PREMIO_5_EURO_PUNTI} punti"
    )

    if punti_mancanti_premio > 0:

        testo += (
            f"\n👉 Ti mancano "
            f"{punti_mancanti_premio} punti"
        )

    else:

        testo += (
            "\n🎉 Hai abbastanza punti "
            "per richiedere il premio!"
        )

    if nuovi:

        testo += (
            f"\n\n🎉 Hai appena ricevuto "
            f"+{nuovi} punti per nuovi "
            "amici verificati!"
        )

    await query.message.reply_text(
        testo,
        reply_markup=menu_club(),
    )


# =========================================================
# INVITA AMICI
# =========================================================

async def invita_amici(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    user_id = update.effective_user.id

    aggiungi_attivita(
        user_id
    )

    bot_info = await context.bot.get_me()

    link = (
        f"https://t.me/"
        f"{bot_info.username}"
        f"?start={user_id}"
    )

    premiati_mese = inviti_premiati_questo_mese(
        user_id
    )

    amici_rimanenti = max(
        0,
        MAX_INVITI_MESE - premiati_mese
    )

    punti_ancora = (
        amici_rimanenti
        * PUNTI_INVITO
    )

    testo = (
        "👥 INVITA AMICI\n\n"

        "Condividi il tuo link personale:\n\n"
        f"{link}\n\n"

        f"🎁 Ogni amico valido ti fa guadagnare "
        f"{PUNTI_INVITO} punti.\n\n"

        f"📌 Puoi ricevere punti per massimo "
        f"{MAX_INVITI_MESE} amici al mese.\n"

        "Dal 6° amico in poi non vengono assegnati "
        "altri punti durante quel mese.\n"
        "Il conteggio riparte il mese successivo.\n\n"

        f"👥 Questo mese: "
        f"{premiati_mese}/{MAX_INVITI_MESE} amici premiati\n"

        f"⭐ Puoi ottenere ancora "
        f"{punti_ancora} punti questo mese.\n\n"

        f"⏳ Un amico diventa valido dopo "
        f"{GIORNI_VERIFICA} giorni, se è ancora "
        "iscritto al canale e ha utilizzato il bot."
    )

    await query.message.reply_text(
        testo,
        reply_markup=menu_club(),
    )


# =========================================================
# PREMI
# =========================================================

async def mostra_premi(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    user_id = update.effective_user.id

    aggiungi_attivita(
        user_id
    )

    punti = get_punti(
        user_id
    )

    tastiera = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 5 € — 10 punti",
                callback_data="premio_5",
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 10 € — 20 punti",
                callback_data="premio_10",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ TORNA AL CLUB",
                callback_data="club_home",
            )
        ],
    ])

    await query.message.reply_text(
        "🎁 PREMI\n\n"
        f"⭐ Hai {punti} punti.\n\n"
        "Puoi richiedere:\n\n"
        "🎫 Buono Amazon 5 € → 10 punti\n"
        "🎫 Buono Amazon 10 € → 20 punti\n\n"
        "Il premio verrà controllato e inviato "
        "manualmente dall'amministratore.",
        reply_markup=tastiera,
    )


# =========================================================
# RICHIESTA PREMIO
# =========================================================

async def richiedi_premio(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    user = update.effective_user

    if query.data == "premio_5":

        valore = 5
        costo = 10

    elif query.data == "premio_10":

        valore = 10
        costo = 20

    else:

        return

    punti = get_punti(
        user.id
    )

    if punti < costo:

        await query.answer(
            f"Ti servono {costo} punti.",
            show_alert=True,
        )

        return

    successo = modifica_punti(
        user.id,
        -costo,
        (
            f"Richiesta premio "
            f"{valore} €"
        ),
    )

    if not successo:

        await query.answer(
            "Punti insufficienti.",
            show_alert=True,
        )

        return

    db = connessione()
    cur = db.cursor()

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
        ora(),
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
                    callback_data=(
                        "approva_premio_"
                        f"{premio_id}"
                    ),
                ),
                InlineKeyboardButton(
                    "❌ RIFIUTA",
                    callback_data=(
                        "rifiuta_premio_"
                        f"{premio_id}"
                    ),
                ),
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
            reply_markup=tastiera_admin,
        )


# =========================================================
# APPROVA / RIFIUTA PREMIO
# =========================================================

async def gestisci_premio_admin(
    update,
    context,
):

    query = update.callback_query

    if not await verifica_admin(
        update
    ):
        return

    await query.answer()

    parti = query.data.split("_")

    azione = parti[0]
    premio_id = int(parti[-1])

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT
            telegram_id,
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

    (
        user_id,
        punti,
        valore,
        stato,
    ) = premio

    if stato != "attesa":

        db.close()

        await query.answer(
            "Richiesta già gestita.",
            show_alert=True,
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
            "Ora puoi inviare il codice "
            "del buono all'utente."
        )

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 Il tuo premio è stato approvato!\n\n"
                    f"🎁 Buono Amazon da {valore} €\n\n"
                    "L'amministratore ti invierà il premio."
                ),
            )

        except Exception as errore:

            print(
                "Errore notifica premio: "
                f"{errore}"
            )

    elif azione == "rifiuta":

        cur.execute("""
            UPDATE premi
            SET stato = 'rifiutato'
            WHERE id = ?
        """, (premio_id,))

        db.commit()
        db.close()

        modifica_punti(
            user_id,
            punti,
            (
                "Restituzione punti "
                f"premio {valore} € "
                "rifiutato"
            ),
        )

        await query.edit_message_text(
            "❌ PREMIO RIFIUTATO\n\n"
            f"⭐ {punti} punti "
            "restituiti all'utente."
        )

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ La richiesta premio "
                    "non è stata approvata.\n\n"
                    f"⭐ I tuoi {punti} punti "
                    "sono stati restituiti."
                ),
            )

        except Exception as errore:

            print(
                "Errore notifica rifiuto: "
                f"{errore}"
            )


# =========================================================
# HOME CLUB
# =========================================================

async def club_home(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    aggiungi_attivita(
        update.effective_user.id
    )

    await query.message.reply_text(
        "🔥 CLUB OFFERTE\n\n"
        "Cosa vuoi fare?",
        reply_markup=menu_club(),
    )


# =========================================================
# =========================================================
# PANNELLO AMMINISTRATORE CLUB
# =========================================================
# =========================================================


# =========================================================
# MENU GESTIONE CLUB
# =========================================================

async def admin_club_menu(
    update,
    context,
):

    if not await verifica_admin(
        update
    ):
        return

    query = update.callback_query

    await query.answer()

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT COUNT(*)
        FROM utenti
    """)

    utenti = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(punti), 0)
        FROM utenti
    """)

    punti = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
    """)

    inviti = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
        WHERE stato = 'verificato'
    """)

    verificati = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
        WHERE stato = 'attesa'
    """)

    attesa = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM premi
        WHERE stato = 'attesa'
    """)

    premi_attesa = cur.fetchone()[0]

    db.close()

    tastiera = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👤 UTENTI",
                callback_data="adm_utenti",
            )
        ],
        [
            InlineKeyboardButton(
                "⭐ MOVIMENTI PUNTI",
                callback_data="adm_movimenti",
            )
        ],
        [
            InlineKeyboardButton(
                "👥 INVITI",
                callback_data="adm_inviti",
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 PREMI",
                callback_data="adm_premi",
            )
        ],
    ])

    await query.message.reply_text(
        "📊 GESTIONE CLUB\n\n"
        f"👤 Utenti registrati: {utenti}\n"
        f"⭐ Punti in circolazione: {punti}\n"
        f"👥 Inviti totali: {inviti}\n"
        f"✅ Inviti verificati: {verificati}\n"
        f"⏳ Inviti in attesa: {attesa}\n"
        f"🎁 Premi in attesa: {premi_attesa}",
        reply_markup=tastiera,
    )


# =========================================================
# LISTA UTENTI
# =========================================================

async def admin_club_utenti(
    update,
    context,
):

    if not await verifica_admin(
        update
    ):
        return

    query = update.callback_query

    await query.answer()

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT
            telegram_id,
            nome,
            username,
            punti
        FROM utenti
        ORDER BY data_iscrizione DESC
        LIMIT 30
    """)

    utenti = cur.fetchall()

    db.close()

    if not utenti:

        await query.message.reply_text(
            "👤 Nessun utente registrato."
        )

        return

    tastiera = []

    for (
        user_id,
        nome,
        username,
        punti,
    ) in utenti:

        identita = (
            f"@{username}"
            if username
            else nome
            or str(user_id)
        )

        tastiera.append([
            InlineKeyboardButton(
                (
                    f"👤 {identita} "
                    f"— ⭐ {punti}"
                ),
                callback_data=(
                    f"adm_user_{user_id}"
                ),
            )
        ])

    tastiera.append([
        InlineKeyboardButton(
            "⬅️ GESTIONE CLUB",
            callback_data="admin_club",
        )
    ])

    await query.message.reply_text(
        "👤 UTENTI REGISTRATI\n\n"
        "Mostro gli ultimi 30:",
        reply_markup=InlineKeyboardMarkup(
            tastiera
        ),
    )


# =========================================================
# SCHEDA UTENTE
# =========================================================

async def admin_club_utente(
    update,
    context,
):

    if not await verifica_admin(
        update
    ):
        return

    query = update.callback_query

    await query.answer()

    try:

        user_id = int(
            query.data.replace(
                "adm_user_",
                ""
            )
        )

    except ValueError:
        return

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT
            nome,
            username,
            punti,
            data_iscrizione,
            attivita
        FROM utenti
        WHERE telegram_id = ?
    """, (user_id,))

    utente = cur.fetchone()

    if not utente:

        db.close()
        return

    (
        nome,
        username,
        punti,
        data_iscrizione,
        attivita,
    ) = utente

    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
        WHERE
            invitante_id = ?
            AND stato = 'verificato'
    """, (user_id,))

    verificati = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM inviti
        WHERE
            invitante_id = ?
            AND stato = 'attesa'
    """, (user_id,))

    attesa = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM premi
        WHERE telegram_id = ?
    """, (user_id,))

    premi = cur.fetchone()[0]

    db.close()

    premiati_mese = inviti_premiati_questo_mese(
        user_id
    )

    username_testo = (
        f"@{username}"
        if username
        else "—"
    )

    data_testo = (
        data_iscrizione[:10]
        if data_iscrizione
        else "—"
    )

    tastiera = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ 1",
                callback_data=(
                    f"adm_pts_{user_id}_1"
                ),
            ),
            InlineKeyboardButton(
                "➕ 5",
                callback_data=(
                    f"adm_pts_{user_id}_5"
                ),
            ),
        ],
        [
            InlineKeyboardButton(
                "➖ 1",
                callback_data=(
                    f"adm_pts_{user_id}_m1"
                ),
            ),
            InlineKeyboardButton(
                "➖ 5",
                callback_data=(
                    f"adm_pts_{user_id}_m5"
                ),
            ),
        ],
        [
            InlineKeyboardButton(
                "📜 STORICO PUNTI",
                callback_data=(
                    f"adm_storico_{user_id}"
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ UTENTI",
                callback_data="adm_utenti",
            )
        ],
    ])

    await query.message.reply_text(
        "👤 SCHEDA UTENTE\n\n"
        f"Nome: {nome or '—'}\n"
        f"Username: {username_testo}\n"
        f"🆔 {user_id}\n\n"
        f"⭐ Saldo: {punti} punti\n"
        f"👥 Amici premiati questo mese: "
        f"{premiati_mese}/{MAX_INVITI_MESE}\n"
        f"✅ Inviti verificati totali: {verificati}\n"
        f"⏳ Inviti in attesa: {attesa}\n"
        f"🎁 Premi richiesti: {premi}\n"
        f"📱 Interazioni bot: {attivita}\n"
        f"📅 Registrato: {data_testo}",
        reply_markup=tastiera,
    )


# =========================================================
# ADMIN: AGGIUNGI / TOGLI PUNTI
# =========================================================

async def admin_modifica_punti(
    update,
    context,
):

    if not await verifica_admin(
        update
    ):
        return

    query = update.callback_query

    await query.answer()

    parti = query.data.split("_")

    try:

        user_id = int(
            parti[2]
        )

        valore_testo = (
            parti[3]
        )

    except (
        ValueError,
        IndexError,
    ):
        return

    if valore_testo == "m1":

        variazione = -1

    elif valore_testo == "m5":

        variazione = -5

    else:

        try:

            variazione = int(
                valore_testo
            )

        except ValueError:
            return

    successo = modifica_punti(
        user_id,
        variazione,
        "Modifica manuale amministratore",
    )

    if not successo:

        await query.answer(
            "Operazione impossibile: "
            "saldo insufficiente.",
            show_alert=True,
        )

        return

    nuovo_saldo = get_punti(
        user_id
    )

    segno = (
        "+"
        if variazione > 0
        else ""
    )

    await query.message.reply_text(
        "✅ PUNTI AGGIORNATI\n\n"
        f"{segno}{variazione} punti\n"
        f"⭐ Nuovo saldo: {nuovo_saldo}"
    )


# =========================================================
# STORICO UTENTE
# =========================================================

async def admin_storico_utente(
    update,
    context,
):

    if not await verifica_admin(
        update
    ):
        return

    query = update.callback_query

    await query.answer()

    try:

        user_id = int(
            query.data.replace(
                "adm_storico_",
                ""
            )
        )

    except ValueError:
        return

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT
            variazione,
            motivo,
            data_movimento
        FROM movimenti_punti
        WHERE telegram_id = ?
        ORDER BY id DESC
        LIMIT 20
    """, (user_id,))

    movimenti = cur.fetchall()

    db.close()

    if not movimenti:

        testo = (
            "📜 Nessun movimento "
            "registrato."
        )

    else:

        righe = [
            "📜 STORICO PUNTI\n"
        ]

        for (
            variazione,
            motivo,
            data,
        ) in movimenti:

            segno = (
                "+"
                if variazione > 0
                else ""
            )

            data_breve = (
                data
                .replace("T", " ")
                [:16]
            )

            righe.append(
                f"{segno}{variazione} ⭐\n"
                f"{motivo}\n"
                f"📅 {data_breve}\n"
            )

        testo = "\n".join(
            righe
        )

    await query.message.reply_text(
        testo
    )


# =========================================================
# TUTTI I MOVIMENTI
# =========================================================

async def admin_movimenti(
    update,
    context,
):

    if not await verifica_admin(
        update
    ):
        return

    query = update.callback_query

    await query.answer()

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT
            utenti.nome,
            utenti.username,
            movimenti_punti.variazione,
            movimenti_punti.motivo,
            movimenti_punti.data_movimento
        FROM movimenti_punti

        LEFT JOIN utenti
        ON utenti.telegram_id
           = movimenti_punti.telegram_id

        ORDER BY
            movimenti_punti.id DESC

        LIMIT 30
    """)

    dati = cur.fetchall()

    db.close()

    if not dati:

        await query.message.reply_text(
            "⭐ Nessun movimento punti."
        )

        return

    righe = [
        "⭐ ULTIMI MOVIMENTI\n"
    ]

    for (
        nome,
        username,
        variazione,
        motivo,
        data,
    ) in dati:

        persona = (
            f"@{username}"
            if username
            else nome
            or "Utente"
        )

        segno = (
            "+"
            if variazione > 0
            else ""
        )

        data_breve = (
            data
            .replace("T", " ")
            [:16]
        )

        righe.append(
            f"👤 {persona}\n"
            f"{segno}{variazione} ⭐ "
            f"— {motivo}\n"
            f"📅 {data_breve}\n"
        )

    await query.message.reply_text(
        "\n".join(
            righe
        )
    )


# =========================================================
# ADMIN INVITI
# =========================================================

async def admin_inviti(
    update,
    context,
):

    if not await verifica_admin(
        update
    ):
        return

    query = update.callback_query

    await query.answer()

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT
            i.invitante_id,
            i.invitato_id,
            i.stato,
            i.data_invito,
            u1.username,
            u2.username
        FROM inviti i

        LEFT JOIN utenti u1
        ON u1.telegram_id = i.invitante_id

        LEFT JOIN utenti u2
        ON u2.telegram_id = i.invitato_id

        ORDER BY i.id DESC

        LIMIT 30
    """)

    dati = cur.fetchall()

    db.close()

    if not dati:

        await query.message.reply_text(
            "👥 Nessun invito registrato."
        )

        return

    righe = [
        "👥 ULTIMI INVITI\n"
    ]

    for (
        invitante,
        invitato,
        stato,
        data,
        username1,
        username2,
    ) in dati:

        da = (
            f"@{username1}"
            if username1
            else str(invitante)
        )

        a = (
            f"@{username2}"
            if username2
            else str(invitato)
        )

        simbolo = (
            "✅"
            if stato == "verificato"
            else "⏳"
        )

        righe.append(
            f"{simbolo} {da}\n"
            f"↳ ha invitato {a}\n"
            f"Stato: {stato}\n"
        )

    await query.message.reply_text(
        "\n".join(
            righe
        )
    )


# =========================================================
# ADMIN PREMI
# =========================================================

async def admin_premi(
    update,
    context,
):

    if not await verifica_admin(
        update
    ):
        return

    query = update.callback_query

    await query.answer()

    db = connessione()
    cur = db.cursor()

    cur.execute("""
        SELECT
            premi.id,
            utenti.nome,
            utenti.username,
            premi.valore_euro,
            premi.punti_usati,
            premi.stato,
            premi.data_richiesta
        FROM premi

        LEFT JOIN utenti
        ON utenti.telegram_id = premi.telegram_id

        ORDER BY premi.id DESC

        LIMIT 30
    """)

    dati = cur.fetchall()

    db.close()

    if not dati:

        await query.message.reply_text(
            "🎁 Nessun premio richiesto."
        )

        return

    righe = [
        "🎁 ULTIME RICHIESTE PREMIO\n"
    ]

    for (
        premio_id,
        nome,
        username,
        valore,
        punti,
        stato,
        data,
    ) in dati:

        persona = (
            f"@{username}"
            if username
            else nome
            or "Utente"
        )

        if stato == "approvato":
            simbolo = "✅"

        elif stato == "rifiutato":
            simbolo = "❌"

        else:
            simbolo = "⏳"

        righe.append(
            f"{simbolo} #{premio_id} "
            f"{persona}\n"
            f"🎫 {valore} € "
            f"— {punti} punti\n"
            f"Stato: {stato}\n"
        )

    await query.message.reply_text(
        "\n".join(
            righe
        )
    )
