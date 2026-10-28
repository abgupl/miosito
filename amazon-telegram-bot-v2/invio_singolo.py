"""Logica invio singolo.

Il parametro servizi esplicito fornisce database, lettura Amazon e funzioni
condivise del coordinatore. Non importa manual_bot e non avvia servizi.
Questo adattatore mantiene i callback esistenti durante la migrazione.
"""
from __future__ import annotations


async def nuova_da_comando(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    if not await servizi.richiedi_canale(update, context):
        return servizi.ConversationHandler.END
    servizi.reset_flusso(context)
    context.user_data['telegram_chat_id'] = servizi.canale_corrente(context).chat_id
    await update.message.reply_text('🔗 ' + servizi.canale_corrente(context).nome + '\nInviami il link Amazon del prodotto:')
    return servizi.LINK


async def nuova_da_pulsante(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    query = update.callback_query
    await query.answer()
    if not await servizi.richiedi_canale(update, context):
        return servizi.ConversationHandler.END
    servizi.reset_flusso(context)
    context.user_data['telegram_chat_id'] = servizi.canale_corrente(context).chat_id
    await query.message.reply_text('🔗 ' + servizi.canale_corrente(context).nome + '\nInviami il link Amazon del prodotto:')
    return servizi.LINK


async def ricevi_link(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    link = update.message.text.strip()
    if not servizi.link_amazon_valido(link):
        await update.message.reply_text('❌ Non sembra un link Amazon.\n\nInviami un link Amazon valido:')
        return servizi.LINK
    context.user_data.setdefault('telegram_chat_id', servizi.canale_corrente(context).chat_id)
    context.user_data['link'] = link
    messaggio_attesa = await update.message.reply_text('🔎 Sto provando a leggere automaticamente i dati del prodotto...')

    async def mostra_tentativo(numero):
        if numero < 3:
            try:
                await messaggio_attesa.edit_text(f'🔎 Lettura offerta Amazon: tentativo {numero}/3 incompleto. Riprovo automaticamente…')
            except Exception:
                pass
    dati = await servizi.leggi_offerta_con_sei_tentativi(link, callback=mostra_tentativo)
    if not dati:
        await messaggio_attesa.edit_text('⏭️ PRODOTTO SALTATO\n\nLettura non completata: prezzo, disponibilità o condizione non verificabili. Controlla i log Railway e riprova con un link Amazon diretto.')
        servizi.reset_flusso(context)
        return servizi.LINK
    if servizi.tag_canale(context.user_data['canale_attivo']):
        context.user_data['link'] = servizi.link_affiliato_multiplo(link, dati.get('asin') or servizi.risolvi_asin_da_link(link), context.user_data['canale_attivo'])
    if dati.get('immagine'):
        context.user_data['foto_url_automatica'] = dati['immagine']
    if dati.get('asin'):
        context.user_data['asin'] = dati['asin']
    tipo = servizi.tipo_o_fallback(link, dati)
    context.user_data['tipologia_amazon'] = tipo
    context.user_data['condizione'] = dati.get('condizione')
    context.user_data['categoria'] = dati.get('categoria')
    context.user_data['coupon'] = dati.get('coupon')
    nome = dati.get('nome')
    prezzo = dati.get('prezzo')
    vecchio = dati.get('vecchio_prezzo')
    context.user_data['nome'] = ' '.join(str(nome).split()).strip()
    context.user_data['prezzo'] = servizi.pulisci_prezzo(prezzo)
    if vecchio:
        context.user_data['vecchio_prezzo'] = servizi.pulisci_prezzo(vecchio)
    else:
        context.user_data['vecchio_prezzo'] = 'NO'
    vecchio_testo = context.user_data['vecchio_prezzo']
    tastiera = servizi.InlineKeyboardMarkup([[servizi.InlineKeyboardButton('✅ USA QUESTI DATI', callback_data='dati_ok')], [servizi.InlineKeyboardButton('✏️ INSERISCI MANUALMENTE', callback_data='dati_manual')]])
    await messaggio_attesa.edit_text(f"✅ DATI TROVATI\n\n📦 {context.user_data['nome']}\n\n💰 Prezzo: {context.user_data['prezzo']} €\n🏷️ Prima: {vecchio_testo}{(' €' if vecchio_testo != 'NO' else '')}\n\nControlla che prezzo e prodotto siano corretti.", reply_markup=tastiera)
    return servizi.DATI_AUTOMATICI


async def conferma_dati_automatici(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    query = update.callback_query
    await query.answer()
    if query.data == 'dati_riprova':
        link = context.user_data.get('link')
        if not link:
            await query.edit_message_text("❌ Non trovo più il link del prodotto. Invia nuovamente l'offerta.")
            return servizi.ConversationHandler.END
        await query.edit_message_text('🔄 Riprovo la ricerca del prodotto: eseguirò fino a 3 nuovi tentativi...')

        class _MessaggioRiprova:

            def __init__(self, message, testo):
                self._message = message
                self.text = testo

            async def reply_text(self, *args, **kwargs):
                return await self._message.reply_text(*args, **kwargs)

        class _UpdateRiprova:

            def __init__(self, update_originale, message):
                self.effective_user = update_originale.effective_user
                self.effective_chat = update_originale.effective_chat
                self.message = _MessaggioRiprova(message, link)
        return await servizi.ricevi_link(_UpdateRiprova(update, query.message), context)
    if query.data == 'dati_ok':
        await query.edit_message_text('✅ Dati confermati.')
        return await servizi.prova_foto_automatica_o_chiedi(update, context)
    if query.data == 'dati_manual':
        link = context.user_data.get('link')
        foto_url_automatica = context.user_data.get('foto_url_automatica')
        asin = context.user_data.get('asin')
        destinazione = context.user_data['telegram_chat_id']
        servizi.reset_flusso(context)
        context.user_data['telegram_chat_id'] = destinazione
        context.user_data['link'] = link
        if foto_url_automatica:
            context.user_data['foto_url_automatica'] = foto_url_automatica
        if asin:
            context.user_data['asin'] = asin
        await query.edit_message_text('✏️ Inserimento manuale selezionato.')
        await query.message.reply_text('📦 Scrivi il nome del prodotto:')
        return servizi.NOME


async def ricevi_nome(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    context.user_data['nome'] = ' '.join(update.message.text.strip().split())
    await update.message.reply_text('💰 Qual è il prezzo attuale?')
    return servizi.PREZZO


async def ricevi_prezzo(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    context.user_data['prezzo'] = servizi.pulisci_prezzo(update.message.text.strip())
    await update.message.reply_text('🏷️ Qual era il prezzo precedente?\n\nOppure scrivi: NO')
    return servizi.VECCHIO_PREZZO


async def ricevi_vecchio_prezzo(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    valore = update.message.text.strip()
    if valore.upper() == 'NO':
        context.user_data['vecchio_prezzo'] = 'NO'
    else:
        context.user_data['vecchio_prezzo'] = servizi.pulisci_prezzo(valore)
    return await servizi.prova_foto_automatica_o_chiedi(update, context)


async def prova_foto_automatica_o_chiedi(servizi, update, context):
    """Cerca e brandizza la foto; se non riesce passa alla scelta manuale."""
    messaggio = update.message if update.message else update.callback_query.message
    foto_url = context.user_data.get('foto_url_automatica')
    if not foto_url:
        link = context.user_data.get('link')
        try:
            prodotto = await servizi.asyncio.to_thread(servizi.leggi_prodotto_amazon, link)
        except Exception as errore:
            print(f'Errore ricerca foto pagina Amazon: {errore}')
            prodotto = None
        if prodotto:
            foto_url = prodotto.get('immagine')
            context.user_data['foto_url_automatica'] = foto_url
    if foto_url:
        attesa = await messaggio.reply_text('🖼 Foto trovata. Creo automaticamente la locandina BestPrice24h…')
        try:
            foto_brandizzata = await servizi.asyncio.to_thread(servizi.crea_immagine_brandizzata, foto_url)
            context.user_data['foto_file_id'] = foto_brandizzata
            await attesa.edit_text('✅ Foto trovata e locandina creata.')
            return await servizi.mostra_anteprima(update, context)
        except Exception as errore:
            print(f'Errore locandina automatica manuale: {errore}')
            context.user_data.pop('foto_file_id', None)
            await attesa.edit_text('⚠️ Non sono riuscito a preparare automaticamente la foto.')
    return await servizi.chiedi_immagine(update, context)


async def chiedi_immagine(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    tastiera = servizi.InlineKeyboardMarkup([[servizi.InlineKeyboardButton('📷 AGGIUNGI IMMAGINE', callback_data='foto_aggiungi')], [servizi.InlineKeyboardButton('➡️ CONTINUA SENZA IMMAGINE', callback_data='foto_salta')]])
    if update.message:
        await update.message.reply_text("🖼 Vuoi aggiungere un'immagine al post?", reply_markup=tastiera)
    else:
        await update.callback_query.message.reply_text("🖼 Vuoi aggiungere un'immagine al post?", reply_markup=tastiera)
    return servizi.FOTO_SCELTA


async def scelta_immagine(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'foto_salta':
        context.user_data.pop('foto_file_id', None)
        await query.edit_message_text('➡️ Continuo senza immagine.')
        return await servizi.mostra_anteprima(update, context)
    if query.data == 'foto_aggiungi':
        await query.edit_message_text('📷 Inviami la foto del prodotto.')
        return servizi.FOTO_ATTESA
    return servizi.FOTO_SCELTA


async def ricevi_immagine(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text('❌ Inviami una foto valida.')
        return servizi.FOTO_ATTESA
    foto = update.message.photo[-1]
    try:
        file_telegram = await foto.get_file()
        contenuto = await file_telegram.download_as_bytearray()
        foto_brandizzata = await servizi.asyncio.to_thread(servizi.crea_immagine_brandizzata_da_bytes, bytes(contenuto))
        context.user_data['foto_file_id'] = foto_brandizzata
        await update.message.reply_text('✅ Immagine aggiunta e locandina creata.')
    except Exception as errore:
        print(f'Errore brandizzazione foto manuale: {errore}')
        context.user_data['foto_file_id'] = foto.file_id
        await update.message.reply_text('⚠️ Ho aggiunto la foto originale perché non sono riuscito a creare la locandina.')
    return await servizi.mostra_anteprima(update, context)


async def mostra_anteprima(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    messaggio = servizi.crea_messaggio(context)
    context.user_data['messaggio'] = messaggio
    link = context.user_data.get('link', '')
    tastiera = servizi.InlineKeyboardMarkup([[servizi.InlineKeyboardButton('📤 PUBBLICA ORA', callback_data='pubblica')], [servizi.InlineKeyboardButton('🕒 PROGRAMMA INVIO', callback_data='programma')], [servizi.InlineKeyboardButton('🎨 FORMATO AUTOMATICO', callback_data='cambia_template')], [servizi.InlineKeyboardButton('❌ ANNULLA', callback_data='annulla')]])
    testo = '👀 ANTEPRIMA — ' + servizi.canale_corrente(context).nome + '\n\n──────────────\n\n' + servizi.crea_caption_con_link(messaggio, link)
    foto_file_id = context.user_data.get('foto_file_id')
    if update.message:
        if foto_file_id:
            inviato = await update.message.reply_photo(photo=foto_file_id, caption=testo, parse_mode='HTML', reply_markup=tastiera)
            if inviato.photo:
                context.user_data['foto_file_id'] = inviato.photo[-1].file_id
        else:
            inviato = await update.message.reply_text(testo, parse_mode='HTML', reply_markup=tastiera)
    elif foto_file_id:
        inviato = await update.callback_query.message.reply_photo(photo=foto_file_id, caption=testo, parse_mode='HTML', reply_markup=tastiera)
        if inviato.photo:
            context.user_data['foto_file_id'] = inviato.photo[-1].file_id
    else:
        inviato = await update.callback_query.message.reply_text(testo, parse_mode='HTML', reply_markup=tastiera)
    context.user_data['anteprima_id'] = inviato.message_id
    return servizi.CONFERMA


async def conferma(servizi, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await servizi.controlla_autorizzazione(update):
        return servizi.ConversationHandler.END
    query = update.callback_query
    await query.answer()
    if query.data in {'pubblica', 'programma', 'cambia_template'} or query.data.startswith('tpl_'):
        if context.user_data.get('anteprima_id') != query.message.message_id:
            await query.message.reply_text('Questa anteprima è scaduta. Usa quella dell’offerta attualmente in preparazione.')
            return servizi.CONFERMA
    if query.data == 'programma':
        tastiera = servizi.InlineKeyboardMarkup([[servizi.InlineKeyboardButton('📅 OGGI', callback_data='prog_giorno_0')], [servizi.InlineKeyboardButton('📅 DOMANI', callback_data='prog_giorno_1')], [servizi.InlineKeyboardButton('📅 TRA 2 GIORNI', callback_data='prog_giorno_2')], [servizi.InlineKeyboardButton('❌ ANNULLA', callback_data='annulla')]])
        await query.message.reply_text('📅 PROGRAMMA INVIO\n\nScegli il giorno:', reply_markup=tastiera)
        return servizi.CONFERMA
    if query.data.startswith('prog_giorno_'):
        try:
            giorni = int(query.data.replace('prog_giorno_', ''))
        except ValueError:
            return servizi.CONFERMA
        data_scelta = servizi.datetime.now(servizi.ROMA_TZ).date() + servizi.timedelta(days=giorni)
        context.user_data['data_programmata'] = data_scelta.isoformat()
        etichetta = 'oggi' if giorni == 0 else 'domani' if giorni == 1 else 'tra 2 giorni'
        eventi = servizi.programmazioni_del_giorno(data_scelta, context.user_data['telegram_chat_id'])
        if eventi:
            orari_occupati = ', '.join((evento['datetime'].strftime('%H:%M') for evento in eventi))
        else:
            orari_occupati = 'nessuno'
        suggerito = servizi.suggerisci_prossimo_slot(data_scelta, context.user_data['telegram_chat_id'])
        if suggerito:
            suggerimento_testo = f"💡 Prossimo spazio consigliato: {suggerito.strftime('%H:%M')}\n\n"
        else:
            suggerimento_testo = '⚠️ Non trovo altri spazi consigliati oggi.\n\n'
        await query.message.reply_text(f"🕒 Hai scelto {etichetta}.\n\n📅 Orari già programmati: {orari_occupati}\n\n{suggerimento_testo}Ora scrivi solo l'orario.")
        return servizi.PROGRAMMA_ORA
    if query.data == 'annulla':
        return await servizi.annulla(update, context)
    if query.data == 'cambia_template':
        await query.message.reply_text('🎨 Il formato è unico e automatico: Offerta sotto il 30%, Super offerta dal 30% al 69%, Sconto extra dal 70%. Coupon e categoria vengono inclusi quando disponibili.')
        return servizi.CONFERMA
    if query.data.startswith('tpl_'):
        template = query.data.replace('tpl_', '')
        context.user_data['template'] = template
        await query.edit_message_text(f'✅ Template selezionato: {template}')
        return await servizi.mostra_anteprima(update, context)
    if query.data == 'pubblica':
        dati = context.user_data
        destinazione = dati.get('telegram_chat_id')
        channel = servizi.canale_corrente(context)
        if not channel or destinazione != channel.chat_id or not dati.get('messaggio') or not dati.get('link'):
            await query.message.reply_text('❌ Bozza scaduta o canale cambiato. Prepara nuovamente il post.')
            return servizi.ConversationHandler.END
        ora = servizi.datetime.now(servizi.ROMA_TZ)
        pid, quando = servizi.salva_programmazione(dati.get('nome'), dati['messaggio'], dati['link'], dati.get('prezzo'), ora, destinazione)
        servizi.salva_foto_programmazione(pid, dati.get('foto_file_id'))
        servizi.reset_flusso(context)
        await query.message.reply_text(f'✅ Post #{pid} confermato per {channel.nome}.\nInvio al primo spazio libero: {quando:%d/%m/%Y %H:%M}, ora italiana. Se lo spazio è libero parte entro circa 30 secondi.', reply_markup=servizi.menu_dopo_pubblicazione())
        return servizi.ConversationHandler.END
    return servizi.CONFERMA
