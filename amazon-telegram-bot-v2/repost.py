"""Logica repost.

Il parametro servizi esplicito fornisce database, lettura Amazon e funzioni
condivise del coordinatore. Non importa manual_bot e non avvia servizi.
Questo adattatore mantiene i callback esistenti durante la migrazione.
"""
from __future__ import annotations


def asin_in_programmati(servizi, destinazione):
    with servizi.sqlite3.connect(servizi.DB_PATH, timeout=30) as db:
        links = db.execute("SELECT link FROM programmazioni WHERE stato IN ('attesa','in_invio','da_verificare') AND CAST(COALESCE(telegram_chat_id,?) AS TEXT)=?", (str(servizi.CHANNEL_ID), str(destinazione))).fetchall()
    return {asin for link, in links if (asin := servizi.risolvi_asin_da_link(link))}


def candidati_repost(servizi, canale, quantita):
    """Storico completo per il repost; metadata storici NON validano offerte attuali."""
    destinazione = servizi._chat_id_per_canale(canale)
    adesso = servizi.datetime.now(servizi.timezone.utc)
    config = servizi.ARCHIVIO.impostazioni(destinazione)
    limite = adesso - servizi.timedelta(days=config['repost_giorni'])
    with servizi.sqlite3.connect(servizi.DB_PATH, timeout=30) as db:
        righe = db.execute("SELECT asin,link,pubblicata_il,nome,foto_file_id,categoria\n            FROM recap_offerte WHERE CAST(telegram_chat_id AS TEXT)=?\n            AND COALESCE(origine,'manuale')<>'raccolta'\n            ORDER BY pubblicata_il DESC,id DESC", (destinazione,)).fetchall()
    in_coda = servizi.asin_in_programmati(destinazione)
    visti = set()
    candidati = []
    for asin, link, data, nome, foto_id, categoria in righe:
        quando = servizi._data_sqlite(data)
        if not quando or not limite <= quando.astimezone(servizi.timezone.utc) <= adesso:
            continue
        asin = asin or servizi.risolvi_asin_da_link(link)
        if not asin or asin in visti:
            continue
        visti.add(asin)
        if asin in in_coda or servizi.prodotto_inviato_ultime_24h(asin, destinazione):
            continue
        candidati.append({'link': 'https://www.amazon.it/dp/' + asin, 'nome': nome, 'foto_file_id': foto_id, 'categoria': categoria})
    servizi.random.shuffle(candidati)
    candidati.sort(key=lambda r: bool(r.get('nome')) + bool(r.get('foto_file_id')), reverse=True)
    return candidati[:min(300, max(30, quantita * 6))]


async def leggi_offerta_repost(servizi, link, storico, callback=None):
    """Storico per nome/foto; prezzi, sconto, coupon e disponibilita' da lettura corrente."""
    dati = await servizi.leggi_offerta_con_sei_tentativi(link, richiedi_immagine=False, callback=callback)
    if not dati:
        return (None, 'prezzo, disponibilita’ o condizione non verificabili (vedi log Railway)')
    if not servizi.offerta_attuale_rilevata(dati):
        return (None, 'nessuno sconto o coupon attuale rilevato')
    dati['nome'] = dati.get('nome') or storico.get('nome')
    dati['_foto_storica_repost'] = storico.get('foto_file_id')
    dati['categoria'] = dati.get('categoria') or storico.get('categoria')
    if not dati.get('nome') or not (dati.get('immagine') or storico.get('foto_file_id')):
        return (None, 'nome o foto mancanti anche nella cronologia')
    return (dati, None)


async def repost_da_pulsante(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    await update.callback_query.answer()
    if not await servizi.richiedi_canale(update, context):
        return servizi.ConversationHandler.END
    channel = servizi.canale_corrente(context)
    servizi.reset_flusso(context)
    draft = {'tipo': 'repost', 'canale': channel.chiave, 'minuti': servizi.intervallo_multiplo(update.effective_user.id, canale=channel.chiave), 'pronti': [], 'scartati': [], 'duplicati': 0, 'elaborazione': False, 'repost_attesa_quantita': True}
    context.user_data['multiplo'] = draft
    await update.effective_message.reply_text('🔁 REPOST — ' + channel.nome + '\n\nScrivi quanti prodotti vuoi ripubblicare (1–50).\nEscludo prodotti già inviati nelle ultime 24 ore e già programmati nello stesso canale.\nControllo dati, prezzi, disponibilità e coupon. Dopo il riepilogo: conferma subito oppure avvio automatico tra 2 minuti. Gli invii rispettano la fascia manuale/multiplo.', reply_markup=servizi.tastiera_multiplo(draft))
    return servizi.RAPIDO


async def prepara_repost(servizi, messaggio, context, draft):
    try:
        links = await servizi.asyncio.to_thread(servizi.candidati_repost, draft['canale'], draft['richiesti'])
        if context.user_data.get('multiplo') is not draft or draft.get('annullato'):
            return
        draft['candidati'] = len(links)
        if not links:
            draft['elaborazione'] = False
            draft['repost_attesa_quantita'] = True
            await messaggio.reply_text('ℹ️ Nessun prodotto disponibile per Repost: servono pubblicazioni nel periodo configurato, più vecchie di 24 ore e non già in coda. Puoi cambiare canale o annullare.', reply_markup=servizi.tastiera_multiplo(draft))
            return
        await servizi.prepara_lotto_multiplo(messaggio, context, draft, links)
    except Exception as exc:
        draft['elaborazione'] = False
        draft['repost_attesa_quantita'] = True
        await messaggio.reply_text(f'⚠️ Ricerca Repost interrotta: {type(exc).__name__}. Riprova indicando la quantità.')


def offerta_attuale_rilevata(servizi, dati):
    """Non confronta mai il prezzo con quello della pubblicazione storica."""
    attuale = servizi.numero_da_prezzo(dati.get('prezzo'))
    precedente = servizi.numero_da_prezzo(dati.get('vecchio_prezzo'))
    return bool(attuale is not None and attuale > 0 and (precedente is not None) and (precedente > attuale) or servizi.frase_coupon(dati.get('coupon')))
