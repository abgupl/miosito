"""Oroscopo e quiz legacy, con menu vincolati al canale d'accesso."""
from interfaccia_legacy import UpdateScoped, verifica

INPUT = 'V2_RUBRICA_INPUT'


async def apri(s, update, context):
    if not all(c.accessibile(update.effective_user.id) for c in s.CANALI.values()):
        await update.effective_message.reply_text('La rubrica è condivisa: la gestione richiede accesso a tutti i canali.')
        return s.ConversationHandler.END
    channel = s.canale_corrente(context)
    proxy = UpdateScoped(update, s, 'v2r', channel.chiave)
    await proxy.effective_message.reply_text('☕ RUBRICA CONDIVISA\n\nCome nel legacy: testi e impostazioni dell’oroscopo sono comuni, con canali di destinazione selezionabili. Il quiz resta dedicato a TECH.')
    await s.mostra_rubrica(proxy.effective_message)
    return s.ConversationHandler.END


async def gestisci(s, update, context):
    checked = await verifica(s, update, context, 'v2r')
    if checked is None:
        return s.ConversationHandler.END
    if not all(c.accessibile(update.effective_user.id) for c in s.CANALI.values()):
        await update.callback_query.answer('La rubrica condivisa richiede accesso a tutti i canali.', show_alert=True)
        return s.ConversationHandler.END
    channel, action = checked
    await update.callback_query.answer()
    context.user_data.pop('oroscopo_modalita', None)
    proxy = UpdateScoped(update, s, 'v2r', channel.chiave, action)
    try:
        if action == 'rub_menu':
            await s.mostra_rubrica(proxy.effective_message)
        elif action.startswith('oro_'):
            await s.azione_oroscopo(action, proxy.effective_message, context)
        elif action.startswith('quiz_'):
            await s.azione_quiz(action, proxy.effective_message, context)
        else:
            raise ValueError('Azione rubrica non valida.')
    except ValueError as error:
        await proxy.effective_message.reply_text(str(error), reply_markup=s.oroscopo_indietro())
    return INPUT if context.user_data.get('oroscopo_modalita') else s.ConversationHandler.END


async def ricevi(s, update, context):
    if not await s.controlla_autorizzazione(update) or not await s.richiedi_canale(update, context):
        return s.ConversationHandler.END
    channel = s.canale_corrente(context)
    mode = context.user_data.get('oroscopo_modalita')
    if not mode:
        return s.ConversationHandler.END
    msg = UpdateScoped(update, s, 'v2r', channel.chiave).effective_message
    try:
        if str(mode).startswith('quiz_'):
            await s.input_quiz(msg, context, mode)
        else:
            await s.ricevi_input_oroscopo(msg, context, mode)
    except ValueError as error:
        await msg.reply_text(str(error), reply_markup=s.oroscopo_indietro())
    return INPUT if context.user_data.get('oroscopo_modalita') else s.ConversationHandler.END
