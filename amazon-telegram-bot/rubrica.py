"""Oroscopo e quiz condivisi, accessibili senza selezionare un canale."""
from interfaccia_legacy import UpdateScoped

INPUT = 'V2_RUBRICA_INPUT'


async def apri(s, update, context):
    if not await s.controlla_autorizzazione(update):
        return s.ConversationHandler.END
    if not all(c.accessibile(update.effective_user.id) for c in s.CANALI.values()):
        await update.effective_message.reply_text('La rubrica è condivisa: la gestione richiede accesso a tutti i canali.')
        return s.ConversationHandler.END
    proxy = UpdateScoped(update, s, 'v2r', 'global')
    await proxy.effective_message.reply_text('☕ RUBRICA CONDIVISA\n\nQuiz e oroscopo hanno impostazioni comuni e, quando attivati, vengono pubblicati su tutti i canali configurati, inclusi quelli aggiunti in futuro.')
    await s.mostra_rubrica(proxy.effective_message)
    return s.ConversationHandler.END


async def gestisci(s, update, context):
    if not await s.controlla_autorizzazione(update):
        return s.ConversationHandler.END
    if not all(c.accessibile(update.effective_user.id) for c in s.CANALI.values()):
        await update.callback_query.answer('La rubrica condivisa richiede accesso a tutti i canali.', show_alert=True)
        return s.ConversationHandler.END
    prefix = 'v2r:global:'
    if not (update.callback_query.data or '').startswith(prefix):
        await update.callback_query.answer('Riapri la rubrica dalla prima schermata.', show_alert=True)
        return s.ConversationHandler.END
    action = update.callback_query.data[len(prefix):]
    await update.callback_query.answer()
    context.user_data.pop('oroscopo_modalita', None)
    proxy = UpdateScoped(update, s, 'v2r', 'global', action)
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
    if not await s.controlla_autorizzazione(update):
        return s.ConversationHandler.END
    if not all(c.accessibile(update.effective_user.id) for c in s.CANALI.values()):
        return s.ConversationHandler.END
    mode = context.user_data.get('oroscopo_modalita')
    if not mode:
        return s.ConversationHandler.END
    msg = UpdateScoped(update, s, 'v2r', 'global').effective_message
    try:
        if str(mode).startswith('quiz_'):
            await s.input_quiz(msg, context, mode)
        else:
            await s.ricevi_input_oroscopo(msg, context, mode)
    except ValueError as error:
        await msg.reply_text(str(error), reply_markup=s.oroscopo_indietro())
    return INPUT if context.user_data.get('oroscopo_modalita') else s.ConversationHandler.END
