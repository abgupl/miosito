"""Quiz condiviso, con prenotazione e stato distinti per destinazione."""


def inizializza(s):
    with s.sqlite3.connect(s.DB_PATH, timeout=30) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS quiz_uscite_canali (
            giorno TEXT NOT NULL, canale TEXT NOT NULL, stato TEXT NOT NULL,
            message_id INTEGER, pubblicato_il TEXT, errore TEXT,
            PRIMARY KEY(giorno,canale))''')
        # Gli invii della versione precedente erano sul solo canale TECH.
        db.execute('''INSERT OR IGNORE INTO quiz_uscite_canali
            SELECT giorno,?,stato,message_id,pubblicato_il,errore FROM quiz_uscite''',
                   (str(s.CHANNEL_ID),))


def voto_ufficiale(s, db, query, giorno):
    message = query.message
    if not message or message.chat.type not in {'channel', 'supergroup'}:
        return False
    chat_id = str(message.chat_id)
    username = '@' + message.chat.username if message.chat.username else chat_id
    return bool(db.execute("""SELECT 1 FROM quiz_uscite_canali
        WHERE giorno=? AND stato='inviato' AND message_id=? AND (canale=? OR lower(canale)=lower(?))""",
        (giorno, message.message_id, chat_id, username)).fetchone())


async def pubblica(s, app, adesso=None):
    adesso = adesso or s.datetime.now(s.ROMA_TZ)
    async with s.QUIZ_LOCK:
        cfg = s.configurazione_quiz()
        if not cfg['attivo'] or adesso.strftime('%H:%M') < cfg['ora']:
            return
        giorno = adesso.date().isoformat()
        with s.sqlite3.connect(s.DB_PATH, timeout=30) as db:
            disponibile = db.execute('SELECT 1 FROM quiz_giorni WHERE giorno=?', (giorno,)).fetchone()
        if not disponibile:
            if cfg.get('esaurimento') != giorno and s.ADMIN_ID:
                await app.bot.send_message(chat_id=s.ADMIN_ID, text=f'⚠️ Nessun quiz caricato per {giorno}. Apri ☕ Rubrica → Quiz.')
                s.imposta_quiz('esaurimento', giorno)
            return
        for channel in tuple(s.CANALI.values()):
            destination = str(channel.chat_id)
            with s.sqlite3.connect(s.DB_PATH, timeout=30) as db:
                booked = db.execute("INSERT OR IGNORE INTO quiz_uscite_canali(giorno,canale,stato) VALUES (?,?,'in_invio')", (giorno, destination)).rowcount
                db.execute("INSERT OR IGNORE INTO quiz_uscite(giorno,stato) VALUES (?,'in_invio')", (giorno,))
            if not booked:
                continue
            try:
                message = await s.invia_quiz(app.bot, destination, giorno)
                with s.sqlite3.connect(s.DB_PATH, timeout=30) as db:
                    db.execute("UPDATE quiz_uscite_canali SET stato='inviato',message_id=?,pubblicato_il=? WHERE giorno=? AND canale=?",
                               (message.message_id, adesso.isoformat(timespec='seconds'), giorno, destination))
            except Exception as error:
                with s.sqlite3.connect(s.DB_PATH, timeout=30) as db:
                    db.execute("UPDATE quiz_uscite_canali SET stato='da_verificare',errore=? WHERE giorno=? AND canale=?", (str(error)[:500], giorno, destination))
                if s.ADMIN_ID:
                    await app.bot.send_message(chat_id=s.ADMIN_ID, text=f'⚠️ Quiz del {giorno} su {channel.nome} da verificare. Nessun reinvio automatico per evitare doppioni.')
        # Il riepilogo giornaliero mantiene compatibili calendario e blocco modifica.
        with s.sqlite3.connect(s.DB_PATH, timeout=30) as db:
            rows = db.execute('SELECT canale,stato,message_id,pubblicato_il FROM quiz_uscite_canali WHERE giorno=?', (giorno,)).fetchall()
            current = [r for r in rows if r[0] in {str(c.chat_id) for c in s.CANALI.values()}]
            if current:
                state = 'inviato' if all(r[1] == 'inviato' for r in current) else 'da_verificare'
                example = next((r for r in current if r[0] == str(s.CHANNEL_ID)), current[0])
                db.execute('UPDATE quiz_uscite SET stato=?,message_id=?,pubblicato_il=? WHERE giorno=?', (state, example[2], example[3], giorno))
