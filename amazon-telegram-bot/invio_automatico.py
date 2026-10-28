"""Instradamento multicanale della logica e dei filtri conservati dal legacy."""
from interfaccia_legacy import UpdateScoped, verifica
from filtri_canale import ambito


async def apri(s, update, context):
    channel = s.canale_corrente(context)
    context.user_data['auto_canale'] = channel.chiave
    scoped = UpdateScoped(update, s, 'v2a', channel.chiave)
    await s.aggiorna_menu_automazione(scoped.callback_query, context)
    return s.ConversationHandler.END


async def gestisci(s, update, context):
    checked = await verifica(s, update, context, 'v2a')
    if checked is None:
        return s.ConversationHandler.END
    with ambito(checked[0].chiave):
        return await _gestisci(s, update, context, checked)


async def _gestisci(s, update, context, checked):
    channel, action = checked
    if action.startswith('offer_search_') and action.removeprefix('offer_search_') != channel.chiave:
        await update.callback_query.answer('La ricerca deve usare il canale corrente.', show_alert=True)
        return s.ConversationHandler.END
    context.user_data['auto_canale'] = channel.chiave
    proxy = UpdateScoped(update, s, 'v2a', channel.chiave, action)
    if action == 'auto_toggle' and not s.leggi_config_automatica(channel.chiave)['attiva']:
        if not s.SORGENTE_RICERCA_ATTIVA:
            await update.callback_query.answer()
            await proxy.effective_message.reply_text('⚠️ Nel codice legacy la sorgente Creators API è disabilitata. I filtri sono disponibili, ma la ricerca di nuove offerte non può essere attivata finché la sorgente non viene ripristinata.')
            return s.ConversationHandler.END
    if not s.SORGENTE_RICERCA_ATTIVA and (action == 'auto_test' or action.startswith('os_count_') or action.endswith('_bundle_test')):
        await update.callback_query.answer()
        await proxy.effective_message.reply_text('⚠️ Ricerca non eseguita: la sorgente Creators API è disabilitata anche nel legacy. Nessun prodotto è stato cercato o pubblicato.')
        return s.ConversationHandler.END
    filters = {
        'filter_brand_add': s.FILTRO_MARCHIO_AGGIUNGI,
        'filter_brand_remove': s.FILTRO_MARCHIO_RIMUOVI,
        'filter_word_add': s.FILTRO_PAROLA_AGGIUNGI,
        'filter_word_remove': s.FILTRO_PAROLA_RIMUOVI,
    }
    if action in filters:
        return await s._imposta_stato_filtro(filters[action])(proxy, context)
    if action in {'priority_add', 'priority_remove', 'priority_access_add', 'priority_access_remove'}:
        return await s.richiedi_modifica_priorita(proxy, context)
    if action.startswith('selective_'):
        handler = s.gestisci_selettiva
    elif action == 'auto_filtri':
        await update.callback_query.answer()
        await s.mostra_menu_selettiva(proxy.callback_query, context)
        return s.ConversationHandler.END
    elif action.startswith('filter_'):
        context.user_data['filtri_da_selettiva'] = True
        handler = s.gestisci_filtri
    elif action.startswith('priority_'):
        handler = s.gestisci_priorita
    elif action.startswith(('casa_', 'tech_')):
        expected = 'casa' if action.startswith('casa_') else 'tech'
        if expected != channel.chiave:
            await update.callback_query.answer('Raccolta non disponibile per questo canale.', show_alert=True)
            return s.ConversationHandler.END
        handler = s.gestisci_raccolte_casa if expected == 'casa' else s.gestisci_raccolte_tech
    elif action.startswith('os_program_'):
        handler = s.prepara_programmazione_ricerca_offerte
    elif action.startswith(('offer_search', 'os_')):
        handler = s.gestisci_ricerca_offerte
    elif action.startswith('prog_giorno_'):
        handler = s.conferma
    else:
        handler = {
            'auto_menu': s.menu_automazione,
            'auto_status': s.mostra_stato_automazioni,
            'auto_intervallo': s.richiedi_intervallo_automatico,
            'auto_fascia': s.richiedi_fascia_automatica,
            'auto_test': s.testa_ricerca_automatica,
        }.get(action, s.gestisci_automazione)
    result = await handler(proxy, context)
    return result if result is not None else s.ConversationHandler.END


async def ricevi(s, update, context, function):
    if not await s.controlla_autorizzazione(update) or not await s.richiedi_canale(update, context):
        return s.ConversationHandler.END
    channel = s.canale_corrente(context)
    if context.user_data.get('auto_canale') != channel.chiave:
        return s.ConversationHandler.END
    with ambito(channel.chiave):
        result = await getattr(s, function)(UpdateScoped(update, s, 'v2a', channel.chiave), context)
    return result if result is not None else s.ConversationHandler.END
