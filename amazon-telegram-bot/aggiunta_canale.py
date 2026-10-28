"""Aggiunta guidata: verifica Telegram, conferma e persistenza del registro."""
import re
import sqlite3
from canali import nuovo_canale, reset_flusso
from menu_canali import tastiera, menu_iniziale
from interfaccia_legacy import UpdateScoped

INPUT = 'V2_AGGIUNTA_CANALE'


async def avvia(s, update, context):
    if not await s.controlla_autorizzazione(update):
        return s.ConversationHandler.END
    reset_flusso(context)
    context.user_data['nuovo_canale'] = {'passo': 'nome'}
    await update.effective_message.reply_text('➕ NUOVO CANALE\n\nPrima aggiungi il bot come amministratore del canale con il permesso di pubblicare.\nOra scrivi il nome da mostrare nel menu, ad esempio SPORT.',
        reply_markup=tastiera(s, [[('⬅️ Menu principale', 'v2_home')]]))
    return INPUT


async def ricevi(s, update, context):
    if not await s.controlla_autorizzazione(update):
        return s.ConversationHandler.END
    draft = context.user_data.get('nuovo_canale')
    if not draft:
        return s.ConversationHandler.END
    update = UpdateScoped(update, s, 'v2m', 'global')
    value = update.message.text.strip()
    if draft['passo'] == 'nome':
        if not value or len(value) > 80:
            await update.message.reply_text('Usa un nome da 1 a 80 caratteri.')
            return INPUT
        draft['nome'], draft['passo'] = value, 'chiave'
        await update.message.reply_text('Scrivi una chiave univoca, ad esempio sport: lettere minuscole, numeri o _, massimo 24 caratteri; deve iniziare con una lettera.')
    elif draft['passo'] == 'chiave':
        try:
            nuovo_canale(s.CANALI, value, draft['nome'], '__verifica__')
        except ValueError as error:
            await update.message.reply_text(str(error))
            return INPUT
        draft['chiave'], draft['passo'] = value, 'destinazione'
        await update.message.reply_text('Invia lo @username del canale oppure il suo ID numerico -100… . Verifico il permesso di pubblicazione prima di aggiungerlo.')
    elif draft['passo'] == 'destinazione':
        if not re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{4,31}|-100[0-9]+', value):
            await update.message.reply_text('Invia uno @username valido o un ID -100… .')
            return INPUT
        try:
            target = await context.bot.get_chat(value)
            if target.type != 'channel':
                raise ValueError('La destinazione deve essere un canale Telegram.')
            member = await context.bot.get_chat_member(target.id, context.bot.id)
            if member.status != 'creator' and not (member.status == 'administrator' and getattr(member, 'can_post_messages', False)):
                raise ValueError('Assegna al bot il permesso di pubblicare nel canale.')
            # Confronta anche le destinazioni configurate tramite username.
            for existing in s.CANALI.values():
                if existing.chat_id == str(target.id) or existing.chat_id.casefold() == value.casefold():
                    raise ValueError('Questo canale è già configurato.')
                if existing.chat_id.startswith('@'):
                    other = await context.bot.get_chat(existing.chat_id)
                    if other.id == target.id:
                        raise ValueError('Questo canale è già configurato.')
            nuovo_canale(s.CANALI, draft['chiave'], draft['nome'], str(target.id))
        except ValueError as error:
            await update.message.reply_text(str(error))
            return INPUT
        except Exception:
            await update.message.reply_text('Non riesco a verificare tutti i collegamenti. Controlla ID, username e permessi del bot, poi riprova.')
            return INPUT
        draft['chat_id'], draft['passo'] = str(target.id), 'conferma'
        await update.message.reply_text(f"Confermi l’aggiunta di {draft['nome']}?\nChiave: {draft['chiave']}\nCanale: {target.title}\nID: {target.id}\n\nLe impostazioni saranno indipendenti dagli altri canali.",
            reply_markup=tastiera(s, [[('✅ Conferma aggiunta', 'v2_add_save')], [('⬅️ Indietro', 'v2_add_back')], [('🏠 Menu principale', 'v2_home')]]))
    else:
        await update.message.reply_text('Premi Conferma aggiunta oppure Annulla.')
    return INPUT


async def conferma(s, update, context):
    if not await s.controlla_autorizzazione(update):
        return s.ConversationHandler.END
    draft = context.user_data.get('nuovo_canale')
    if not draft or draft.get('passo') != 'conferma':
        await update.effective_message.reply_text('Richiesta scaduta. Apri nuovamente Aggiungi canale.', reply_markup=menu_iniziale(s, update.effective_user.id))
        return s.ConversationHandler.END
    try:
        channel = nuovo_canale(s.CANALI, draft['chiave'], draft['nome'], draft['chat_id'])
        s.ARCHIVIO.salva_canale(channel)
    except (ValueError, sqlite3.IntegrityError) as error:
        await update.effective_message.reply_text('Canale non aggiunto: chiave o destinazione già presenti. Riapri Aggiungi canale.', reply_markup=menu_iniziale(s, update.effective_user.id))
        return s.ConversationHandler.END
    s.CANALI[channel.chiave] = channel
    s.ARCHIVIO.inizializza(list(s.CANALI.values()), s.config_fascia_manuale())
    reset_flusso(context)
    await update.effective_message.reply_text('✅ Canale aggiunto: ' + channel.nome + '. Ora puoi selezionarlo. Rimane salvato anche dopo un riavvio.',
                                            reply_markup=menu_iniziale(s, update.effective_user.id))
    return s.ConversationHandler.END


async def indietro(s, update, context):
    if not await s.controlla_autorizzazione(update):
        return s.ConversationHandler.END
    draft = context.user_data.get('nuovo_canale')
    if not draft:
        from menu_canali import gestisci
        return await gestisci(s, update, context, data_override='v2_home')
    previous = {'chiave': 'nome', 'destinazione': 'chiave', 'conferma': 'destinazione'}
    draft['passo'] = previous.get(draft['passo'], 'nome')
    prompts = {'nome': 'Scrivi il nome da mostrare nel menu.',
               'chiave': 'Scrivi la chiave univoca del canale.',
               'destinazione': 'Invia lo @username del canale oppure il suo ID -100… .'}
    rows = [[('⬅️ Indietro', 'v2_add_back')]] if draft['passo'] != 'nome' else []
    rows.append([('🏠 Menu principale', 'v2_home')])
    await update.effective_message.reply_text(prompts[draft['passo']], reply_markup=tastiera(s, rows))
    return INPUT
