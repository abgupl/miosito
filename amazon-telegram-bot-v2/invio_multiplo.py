"""Logica invio multiplo.

Il parametro servizi esplicito fornisce database, lettura Amazon e funzioni
condivise del coordinatore. Non importa manual_bot e non avvia servizi.
Questo adattatore mantiene i callback esistenti durante la migrazione.
"""
from __future__ import annotations


def filtra_duplicati_recenti_multiplo(servizi, draft):
    validi = []
    for prodotto in draft['pronti']:
        asin = prodotto.get('asin') or servizi.estrai_asin_da_link(prodotto['link'])
        if servizi.prodotto_inviato_ultime_24h(asin, servizi._chat_id_per_canale(draft['canale'])):
            draft['scartati'].append(f"{prodotto.get('link_originale') or prodotto['link']} — già pubblicato nelle ultime 24 ore nel canale {draft['canale'].upper()}")
        else:
            validi.append(prodotto)
    if draft.get('tipo') == 'repost':
        with servizi.sqlite3.connect(servizi.DB_PATH, timeout=30) as db:
            links_in_coda = db.execute("SELECT link FROM programmazioni WHERE stato IN ('attesa','in_invio','da_verificare') AND CAST(COALESCE(telegram_chat_id,?) AS TEXT)=?", (str(servizi.CHANNEL_ID), servizi._chat_id_per_canale(draft['canale']))).fetchall()
        asin_in_coda = {servizi.estrai_asin_da_link(link) for link, in links_in_coda}
        restanti = []
        for prodotto in validi:
            if (prodotto.get('asin') or servizi.estrai_asin_da_link(prodotto['link'])) in asin_in_coda:
                draft['scartati'].append(f"{prodotto.get('link_originale') or prodotto['link']} — prodotto già in Programmati")
            else:
                restanti.append(prodotto)
        validi = restanti
    draft['pronti'] = validi


def intervallo_multiplo(servizi, utente, valore=None, canale=None):
    destinazione = servizi._chat_id_per_canale(canale or 'tech')
    if valore is not None:
        servizi.ARCHIVIO.salva(destinazione, 'intervallo', valore)
    return servizi.ARCHIVIO.impostazioni(destinazione)['intervallo']


def tastiera_annulla_elaborazione(servizi):
    return servizi.InlineKeyboardMarkup([[servizi.InlineKeyboardButton('🛑 ANNULLA REPOST / LETTURA', callback_data='multi_annulla')]])


def tastiera_multiplo(servizi, draft):
    if draft.get('tipo') == 'singolo_cronologia':
        return servizi.tastiera_confronto_cronologia(bool(draft.get('pronti')) and not draft.get('elaborazione'))
    rows = [[servizi.InlineKeyboardButton(f"⏱ Intervallo: {draft['minuti']} min", callback_data='multi_timing')]]
    if draft.get('pronti') and not draft.get('elaborazione'):
        rows.append([servizi.InlineKeyboardButton('🚀 CONFERMA E AVVIA', callback_data='multi_avvia')])
    rows.append([servizi.InlineKeyboardButton('❌ ANNULLA', callback_data='multi_annulla')])
    return servizi.InlineKeyboardMarkup(rows)


def link_affiliato_multiplo(servizi, link, asin, canale=None):
    tag = servizi.tag_canale(canale)
    if not tag:
        raise ValueError('Imposta AMAZON_PARTNER_TAG su Railway con il tuo tag affiliato Amazon')
    if not asin:
        raise ValueError('ASIN del prodotto non trovato')
    return 'https://www.amazon.it/dp/' + asin + '?' + servizi.urlencode({'tag': tag})


def piano_multiplo(servizi, prodotti, minuti, destinazione, salva=False, origine='multiplo'):
    """Ricalcola e prenota l'intero lotto in un'unica transazione SQLite."""
    cfg = servizi.config_fascia_manuale(canale=destinazione)
    with servizi.sqlite3.connect(servizi.DB_PATH, timeout=30) as db:
        db.execute('BEGIN IMMEDIATE')
        righe = db.execute("SELECT invio_previsto FROM programmazioni WHERE stato IN ('attesa','in_invio','da_verificare') AND (telegram_chat_id=? OR (telegram_chat_id IS NULL AND ?=?))", (str(destinazione), str(destinazione), str(servizi.CHANNEL_ID))).fetchall()
        occupati = [servizi.datetime.fromisoformat(r[0]).astimezone(servizi.timezone.utc) for r in righe]
        passo = servizi.timedelta(minutes=minuti)
        quando = servizi.datetime.now(servizi.timezone.utc).replace(microsecond=0) + servizi.timedelta(minutes=servizi.minuti_rimanenti_prima_del_prossimo_invio(destinazione))
        piano = []
        for prodotto in prodotti:
            quando = servizi.slot_manuale_libero(quando, occupati, minuti, dict(cfg, _canale=str(destinazione)))
            pid = None
            if salva:
                corpo = servizi.crea_messaggio_programmato(prodotto['nome'], prodotto['prezzo'], prodotto['vecchio_prezzo'], 'pulito', prodotto.get('categoria'), prodotto.get('coupon'))
                cur = db.execute("INSERT INTO programmazioni\n                    (nome,messaggio,link,prezzo,vecchio_prezzo,template,foto_file_id,telegram_chat_id,invio_previsto,stato,data_creazione,origine)\n                    VALUES (?,?,?,?,?,'pulito',?,?,?,'attesa',?,'multiplo')", (prodotto['nome'], corpo, prodotto['link'], prodotto['prezzo'], prodotto['vecchio_prezzo'], prodotto.get('foto_file_id'), str(destinazione), quando.isoformat(timespec='seconds'), servizi.datetime.now(servizi.timezone.utc).isoformat(timespec='seconds')))
                pid = cur.lastrowid
                db.execute('UPDATE programmazioni SET intervallo_minuti=?,origine=? WHERE id=?', (minuti, 'repost' if origine == 'repost' else 'multiplo', pid))
            piano.append((pid, quando))
            occupati.append(quando)
            quando += passo
    return piano


def arma_avvio_multiplo(servizi, messaggio, context, draft):
    token = object()
    draft['timer_token'] = token
    context.application.create_task(servizi.avvio_multiplo_differito(messaggio, context, draft, token))


async def avvio_multiplo_differito(servizi, messaggio, context, draft, token):
    await servizi.asyncio.sleep(120)
    if context.user_data.get('multiplo') is draft and draft.get('timer_token') is token and (not draft.get('elaborazione')):
        await servizi.avvia_lotto_multiplo(messaggio, context, draft, automatico=True)


async def avvia_lotto_multiplo(servizi, messaggio, context, draft, automatico=False):
    if draft.get('tipo') == 'singolo_cronologia':
        return False
    async with servizi.MULTIPLO_LOCK:
        if context.user_data.get('multiplo') is not draft or draft.get('conferma_in_corso') or (not draft.get('pronti')):
            return False
        draft['conferma_in_corso'] = True
        draft.pop('timer_token', None)
        try:
            servizi.filtra_duplicati_recenti_multiplo(draft)
            piano = servizi.piano_multiplo(draft['pronti'], draft['minuti'], servizi._chat_id_per_canale(draft['canale']), salva=True, origine=draft.get('tipo', 'multiplo'))
        except Exception:
            draft.pop('conferma_in_corso', None)
            await messaggio.reply_text('⚠️ Salvataggio non riuscito. Il lotto non è stato aggiunto: premi CONFERMA E AVVIA per riprovare.', reply_markup=servizi.tastiera_multiplo(draft))
            return False
        context.user_data.pop('multiplo', None)
    righe = [f"✅ {('Avvio automatico dopo 2 minuti' if automatico else 'Avvio confermato')}", f"📅 {len(piano)} post aggiunti a Programmati — {draft['canale'].upper()}.", f'Primo invio: {piano[0][1].astimezone(servizi.ROMA_TZ):%d/%m %H:%M}' if piano else 'Nessun invio: tutti i prodotti sono stati scartati.', f"Intervallo: {draft['minuti']} minuti. Orari già occupati rispettati.", f"Richiesti: {draft['richiesti']} · Validati: {len(piano)}" if draft.get('richiesti') else '', 'Il primo post partirà al primo orario libero, rispettando le Pause Caffè.', f"Duplicati ignorati: {draft['duplicati']}"]
    if draft['scartati']:
        righe += ['', '❌ LINK SCARTATI / ERRORI:'] + list(draft['scartati'])
    else:
        righe.append('✅ Nessun link scartato per errori o dati mancanti.')
    testo = '\n'.join(righe)
    try:
        for pos in range(0, len(testo), 3500):
            await messaggio.reply_text(testo[pos:pos + 3500])
    except Exception as exc:
        print(f'Invio multiplo salvato, notifica non consegnata: {type(exc).__name__}')
    return True


async def riepilogo_multiplo(servizi, messaggio, draft, context=None):
    if draft.get('tipo') == 'singolo_cronologia':
        return await servizi.mostra_confronto_cronologia(messaggio, context, draft)
    servizi.filtra_duplicati_recenti_multiplo(draft)
    piano = servizi.piano_multiplo(draft['pronti'], draft['minuti'], servizi._chat_id_per_canale(draft['canale']))
    righe = [f"{('🔁 REPOST' if draft.get('tipo') == 'repost' else '📦 INVIO MULTIPLO')} — {draft['canale'].upper()}", f"⏱ Intervallo: {draft['minuti']} minuti", f"✅ Pronti: {len(piano)} · Scartati: {len(draft['scartati'])} · Duplicati: {draft['duplicati']}", '']
    if draft.get('richiesti'):
        righe.append(f"Richiesti: {draft['richiesti']} · Preparati: {len(piano)} · Candidati disponibili per il controllo: {draft.get('candidati', 0)}")
    if piano:
        giorni_piano = {quando.astimezone(servizi.ROMA_TZ).date() for _, quando in piano}
        eventi = servizi.descrizione_pause_programmate(servizi._chat_id_per_canale(draft['canale']), giorni_piano)
        if eventi:
            righe.append('☕ Pause Caffè considerate nella programmazione:')
            righe.extend((testo.replace('\n', ' · ') for _, testo in eventi))
            righe.append('')
    for prodotto, (_, quando) in zip(draft['pronti'], piano):
        righe.append(f"{quando.astimezone(servizi.ROMA_TZ):%d/%m %H:%M} · {prodotto['nome'][:75]} · {prodotto['prezzo']} €")
    for motivo in draft['scartati']:
        righe.append('❌ ' + motivo)
    if draft['pronti']:
        righe.append('\n⏳ Avvio automatico tra 2 minuti. Premi CONFERMA E AVVIA per partire subito oppure ANNULLA per fermare il lotto.')
    righe.append('\nOrari italiani. Gli orari saranno ricontrollati alla conferma. Prezzi rilevati durante la preparazione.')
    testo = '\n'.join(righe)
    for pos in range(0, len(testo), 3500):
        await messaggio.reply_text(testo[pos:pos + 3500], reply_markup=servizi.tastiera_multiplo(draft) if pos + 3500 >= len(testo) else None)
    if context is not None and draft['pronti']:
        servizi.arma_avvio_multiplo(messaggio, context, draft)


async def rapido_da_comando(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
    if not await servizi.richiedi_canale(update, context):
        return servizi.ConversationHandler.END
    channel = servizi.canale_corrente(context)
    servizi.reset_flusso(context)
    draft = {'canale': channel.chiave, 'minuti': servizi.intervallo_multiplo(update.effective_user.id, canale=channel.chiave), 'pronti': [], 'scartati': [], 'duplicati': 0, 'elaborazione': False}
    context.user_data['multiplo'] = draft
    await update.effective_message.reply_text('📦 INVIO MULTIPLO — ' + channel.nome + '\n\nScegli l’intervallo, poi incolla i link Amazon, uno per riga (massimo 50).\nOgni prodotto ha fino a 3 tentativi di lettura.\nDopo il riepilogo il lotto parte automaticamente entro 2 minuti: puoi confermare subito o annullare.', reply_markup=servizi.tastiera_multiplo(draft))
    return servizi.RAPIDO


async def rapido_da_pulsante(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await servizi.rapido_da_comando(update, context)


async def prepara_lotto_multiplo(servizi, messaggio, context, draft, links, seconda_passata=False):
    visti = set()
    da_riprovare = []
    try:
        for indice, candidato in enumerate(links, 1):
            storico = candidato if isinstance(candidato, dict) else {}
            link = storico.get('link') if storico else candidato
            if draft.get('richiesti') and len(draft['pronti']) >= draft['richiesti']:
                break
            if context.user_data.get('multiplo') is not draft or draft.get('annullato'):
                return
            if draft.get('tipo') == 'repost':
                stato = f"🔁 REPOST: {len(draft['pronti'])}/{draft['richiesti']} post pronti\n🔎 Candidato esaminato: {indice} (gli altri sono riserve)"
            else:
                stato = f'🔎 Prodotto {indice}/{len(links)} — preparazione in corso…'
            try:
                await messaggio.edit_text(stato, reply_markup=servizi.tastiera_annulla_elaborazione())
            except Exception:
                pass
            asin_iniziale = await servizi.asyncio.to_thread(servizi.risolvi_asin_da_link, link)
            if draft.get('tipo') != 'singolo_cronologia' and servizi.prodotto_inviato_ultime_24h(asin_iniziale, servizi._chat_id_per_canale(draft['canale'])):
                draft['scartati'].append(f"{link} — già pubblicato nelle ultime 24 ore nel canale {draft['canale'].upper()}")
                continue

            async def mostra_tentativo_multiplo(numero):
                if numero < 3:
                    try:
                        if context.user_data.get('multiplo') is draft and (not draft.get('annullato')):
                            await messaggio.edit_text(f"🔎 Tentativo {numero}/3 — {len(draft['pronti'])}/{draft.get('richiesti', len(links))} post pronti. Riprovo…", reply_markup=servizi.tastiera_annulla_elaborazione())
                    except Exception:
                        pass
            if draft.get('tipo') == 'repost':
                dati, motivo_repost = await servizi.leggi_offerta_repost(link, storico, mostra_tentativo_multiplo)
            else:
                dati = await servizi.leggi_offerta_con_sei_tentativi(link, richiedi_immagine=True, callback=mostra_tentativo_multiplo)
                motivo_repost = None
            if context.user_data.get('multiplo') is not draft or draft.get('annullato'):
                return
            if not dati:
                if not seconda_passata:
                    da_riprovare.append(candidato)
                    print(f'Invio multiplo: {link} in coda per seconda passata dopo 20 secondi.')
                else:
                    draft['scartati'].append(f"{link} — {motivo_repost or 'lettura non completata dopo 6 tentativi (vedi log Railway)'}")
                continue
            tipo = servizi.tipo_o_fallback(link, dati)
            dati['tipologia_amazon'] = tipo
            if draft.get('tipo') == 'repost' and (not servizi.offerta_attuale_rilevata(dati)):
                draft['scartati'].append(f'{link} — nessuno sconto attuale né coupon rilevato')
                continue
            try:
                asin = dati.get('asin') or asin_iniziale
                if draft.get('tipo') != 'singolo_cronologia' and servizi.prodotto_inviato_ultime_24h(asin, servizi._chat_id_per_canale(draft['canale'])):
                    draft['scartati'].append(f"{link} — già pubblicato nelle ultime 24 ore nel canale {draft['canale'].upper()}")
                    continue
                if asin in visti:
                    draft['duplicati'] += 1
                    continue
                affiliato = servizi.link_affiliato_multiplo(link, asin, draft['canale'])
                foto_storica = dati.get('_foto_storica_repost') if draft.get('tipo') == 'repost' else None
                if foto_storica:
                    foto = foto_storica
                else:
                    foto = await servizi.prepara_foto_automatica(dati['immagine'])
                if context.user_data.get('multiplo') is not draft or draft.get('annullato'):
                    return
                anteprima = await messaggio.reply_photo(photo=foto, caption=f"📦 Preparato {indice}/{len(links)}: {str(dati['nome'])[:700]}")
                if context.user_data.get('multiplo') is not draft or draft.get('annullato'):
                    return
                visti.add(asin)
                draft['pronti'].append({'nome': ' '.join(str(dati['nome']).split())[:500], 'prezzo': servizi.pulisci_prezzo(dati['prezzo']), 'vecchio_prezzo': servizi.pulisci_prezzo(dati['vecchio_prezzo']) if dati.get('vecchio_prezzo') else 'NO', 'link': affiliato, 'foto_file_id': anteprima.photo[-1].file_id, 'categoria': dati.get('categoria'), 'asin': asin, 'link_originale': link, 'coupon': dati.get('coupon')})
            except Exception as exc:
                draft['scartati'].append(f'{link} — {str(exc)[:120]}')
        if da_riprovare and (not seconda_passata) and (context.user_data.get('multiplo') is draft) and (not draft.get('annullato')):
            try:
                await messaggio.edit_text(f'⏳ Prima passata terminata. {len(da_riprovare)} prodotti in attesa: riprovo tra 20 secondi (3 tentativi ciascuno).', reply_markup=servizi.tastiera_annulla_elaborazione())
            except Exception:
                pass
            await servizi.asyncio.sleep(20)
            if context.user_data.get('multiplo') is not draft or draft.get('annullato'):
                return
            await servizi.prepara_lotto_multiplo(messaggio, context, draft, da_riprovare, seconda_passata=True)
            return
        if context.user_data.get('multiplo') is draft and (not draft.get('annullato')):
            draft['elaborazione'] = False
            if draft.get('tipo') == 'singolo_cronologia':
                await servizi.mostra_confronto_cronologia(messaggio, context, draft)
            else:
                await servizi.riepilogo_multiplo(messaggio, draft, context)
    except Exception as exc:
        draft['elaborazione'] = False
        if context.user_data.get('multiplo') is draft:
            await messaggio.reply_text(f'⚠️ Preparazione interrotta: {type(exc).__name__}. Puoi confermare i prodotti già pronti o annullare.', reply_markup=servizi.tastiera_multiplo(draft))


async def ricevi_rapido(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    draft = context.user_data.get('multiplo')
    if not draft:
        return await servizi.rapido_da_comando(update, context)
    if draft.get('elaborazione'):
        await update.message.reply_text('⏳ Sto preparando il lotto. Attendi il riepilogo oppure usa /annulla.')
        return servizi.RAPIDO
    if draft.pop('timing_personalizzato', False):
        try:
            minuti = int(update.message.text.strip())
            if not 1 <= minuti <= 1440:
                raise ValueError
        except ValueError:
            draft['timing_personalizzato'] = True
            await update.message.reply_text('Inserisci un numero intero da 1 a 1440 minuti.')
            return servizi.RAPIDO
        draft['minuti'] = servizi.intervallo_multiplo(update.effective_user.id, minuti, canale=draft['canale'])
        if draft['pronti']:
            await servizi.riepilogo_multiplo(update.message, draft, context)
        else:
            await update.message.reply_text(f'✅ Intervallo salvato: {minuti} minuti.', reply_markup=servizi.tastiera_multiplo(draft))
        return servizi.RAPIDO
    if draft.get('repost_attesa_quantita'):
        testo = update.message.text.strip()
        if not testo.isdigit() or not 1 <= int(testo) <= 50:
            await update.message.reply_text('Scrivi quanti prodotti vuoi ripubblicare: un numero da 1 a 50.')
            return servizi.RAPIDO
        if not servizi.tag_canale(draft['canale']):
            await update.message.reply_text('⚠️ Imposta AMAZON_PARTNER_TAG su Railway con il tuo tag affiliato prima di avviare Repost.')
            return servizi.RAPIDO
        quantita = int(testo)
        draft['elaborazione'] = True
        draft['richiesti'] = quantita
        draft.pop('repost_attesa_quantita', None)
        attesa = await update.message.reply_text(f'🔁 REPOST — Obiettivo: {quantita} post.\nPotrei esaminare più prodotti come riserve se alcuni non sono validi.\nPremi ANNULLA per interrompere.', reply_markup=servizi.tastiera_annulla_elaborazione())
        context.application.create_task(servizi.prepara_repost(attesa, context, draft), update=update)
        return servizi.RAPIDO
    if draft.get('pronti'):
        await update.message.reply_text('Conferma o annulla il lotto già preparato prima di inviare altri link.')
        return servizi.RAPIDO
    if not servizi.tag_canale(draft['canale']):
        await update.message.reply_text('⚠️ Prima imposta AMAZON_PARTNER_TAG nelle variabili Railway con il TUO tag affiliato Amazon, poi reinvia i link.')
        return servizi.RAPIDO
    links = servizi.re.findall('https?://[^\\s<>]+', update.message.text)
    links = [x.rstrip('.,;)]') for x in links]
    validi = []
    for link in links:
        host = (servizi.urlparse(link).hostname or '').lower()
        if host in {'amazon.it', 'www.amazon.it', 'amzn.to', 'amzn.eu', 'link.amazon', 'link.amazon.it', 'a.co'} or host.endswith('.amazon.it'):
            validi.append(link)
    if not validi or len(validi) > 50:
        await update.message.reply_text('Invia da 1 a 50 link Amazon Italia validi, uno per riga.')
        return servizi.RAPIDO
    unici = list(dict.fromkeys(validi))
    draft['duplicati'] = len(validi) - len(unici)
    draft['scartati'] = [f'{len(links) - len(validi)} link non Amazon Italia ignorati'] if len(links) != len(validi) else []
    draft['elaborazione'] = True
    attesa = await update.message.reply_text(f'🔎 Preparo {len(unici)} prodotti. Puoi usare /annulla per interrompere.')
    context.application.create_task(servizi.prepara_lotto_multiplo(attesa, context, draft, unici), update=update)
    return servizi.RAPIDO


async def gestisci_multiplo(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    query = update.callback_query
    await query.answer()
    draft = context.user_data.get('multiplo')
    if not draft:
        await query.message.reply_text('Lotto non più disponibile. Apri nuovamente Invio multiplo.')
        return servizi.ConversationHandler.END
    azione = query.data
    if azione == 'multi_annulla':
        draft['annullato'] = True
        context.user_data.pop('multiplo', None)
        await query.edit_message_text('🛑 Elaborazione annullata. Nessun nuovo post verrà preparato o programmato.\nLa lettura Amazon già avviata potrebbe terminare in background, ma il risultato sarà ignorato.')
        return servizi.ConversationHandler.END
    if draft.get('elaborazione') or draft.get('conferma_in_corso'):
        await query.message.reply_text("⏳ Attendi il completamento dell'operazione in corso.")
        return servizi.RAPIDO
    if azione == 'multi_timing':
        draft.pop('timer_token', None)
        await query.message.reply_text("⏱ Scegli l'intervallo tra i post:", reply_markup=servizi.InlineKeyboardMarkup([[servizi.InlineKeyboardButton(f'{m} min', callback_data=f'multi_min_{m}') for m in (10, 20, 30)], [servizi.InlineKeyboardButton(f'{m} min', callback_data=f'multi_min_{m}') for m in (40, 60)], [servizi.InlineKeyboardButton('✏️ Personalizzato', callback_data='multi_personalizzato')]]))
    elif azione == 'multi_personalizzato':
        draft['timing_personalizzato'] = True
        await query.message.reply_text("Scrivi l'intervallo desiderato in minuti (1–1440):")
    elif azione.startswith('multi_min_'):
        draft['minuti'] = servizi.intervallo_multiplo(update.effective_user.id, int(azione.rsplit('_', 1)[1]), canale=draft['canale'])
        draft.pop('timing_personalizzato', None)
        if draft['pronti']:
            await servizi.riepilogo_multiplo(query.message, draft, context)
        else:
            await query.message.reply_text(f"✅ Intervallo: {draft['minuti']} minuti", reply_markup=servizi.tastiera_multiplo(draft))
    elif azione.startswith('multi_canale_'):
        await query.message.reply_text('La destinazione del lotto è fissa. Usa Cambia canale dal menu per iniziare un nuovo lotto.')
    elif azione == 'multi_avvia' and draft['pronti']:
        riuscito = await servizi.avvia_lotto_multiplo(query.message, context, draft)
        if riuscito:
            return servizi.ConversationHandler.END
    return servizi.RAPIDO
