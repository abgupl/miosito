"""Menu V2 con callback legati al canale della schermata."""
import re
from canali import reset_flusso, selezionato

INPUT = 'V2_IMPOSTAZIONE'


def tastiera(s, rows):
    return s.InlineKeyboardMarkup([[s.InlineKeyboardButton(label, callback_data=data)
                                    for label, data in row] for row in rows])


def menu_iniziale(s, user_id=None):
    rows = [[(c.nome, 'v2_select_' + c.chiave)] for c in s.CANALI.values()
            if user_id is None or c.accessibile(user_id)]
    rows.append([('☕ Rubrica', 'v2_rubrica')])
    rows.append([('⚙️ Impostazioni generali', 'v2_settings')])
    return tastiera(s, rows)


def menu_canale(s, channel):
    prefix = 'v2c:' + channel.chiave + ':'
    return tastiera(s, [
        [('✍️ Nuovi post', prefix + 'posts')],
        [('♻️ Repost', prefix + 'repost')],
        [('🤖 Invio automatico', prefix + 'automatic')],
        [('📅 Programmati e code', prefix + 'queue:0')],
        [('📚 Cronologia', prefix + 'history:0')],
        [('⚙️ Impostazioni canale', prefix + 'settings')],
        [('🔄 Cambia canale', 'v2_home')],
    ])


async def mostra(s, update, text, keyboard):
    # Anche da anteprime fotografiche: non tenta edit_message_text su una foto.
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def gestisci(s, update, context, data_override=None):
    if not await s.controlla_autorizzazione(update):
        return s.ConversationHandler.END
    q = update.callback_query
    if q:
        await q.answer()
    data = data_override or (q.data if q else 'v2_home')
    if data == 'v2_rubrica':
        import rubrica
        reset_flusso(context)
        context.user_data.pop('canale_attivo', None)
        return await rubrica.apri(s, update, context)
    if data == 'v2_add_channel':
        import aggiunta_canale
        return await aggiunta_canale.avvia(s, update, context)
    if data == 'v2_add_save':
        import aggiunta_canale
        return await aggiunta_canale.conferma(s, update, context)
    if data == 'v2_home':
        reset_flusso(context)
        context.user_data.pop('canale_attivo', None)
        await mostra(s, update, '📢 SCEGLI IL CANALE DA GESTIRE', menu_iniziale(s, update.effective_user.id))
        return s.ConversationHandler.END
    if data == 'v2_settings':
        reset_flusso(context)
        await mostra(s, update,
                     '⚙️ IMPOSTAZIONI GENERALI\n\n'
                     'Fuso orario: Europe/Rome\n'
                     'Tag affiliato predefinito: ' + (s.tag_canale(None) or 'non configurato') + '\n\n'
                     'I canali ereditano il tag generale finché non impostano il proprio.\n'
                     'Destinazioni e amministratori si configurano nelle variabili del servizio.',
                     tastiera(s, [[('📢 Canali configurati', 'v2_channels')],
                                  [('➕ Aggiungi canale', 'v2_add_channel')],
                                  [('📊 Stato del bot', 'v2_status')],
                                  [('📋 Log e diagnostica', 'diag_logs_all_0')],
                                  [('⬅️ Scelta canale', 'v2_home')]]))
        return s.ConversationHandler.END
    if data in ('v2_channels', 'v2_status'):
        rows = [c for c in s.CANALI.values() if c.accessibile(update.effective_user.id)]
        text = '📢 CANALI CONFIGURATI\n\n' + '\n'.join(c.nome + ' → ' + c.chat_id for c in rows)
        if data == 'v2_status':
            text = '📊 Bot in esecuzione\nFuso orario: Europe/Rome\n\n' + text
        text += '\n\nLa configurazione non certifica i permessi Telegram: usa Verifica collegamento dentro il canale.'
        await mostra(s, update, text, tastiera(s, [[('⬅️ Impostazioni generali', 'v2_settings')]]))
        return s.ConversationHandler.END
    if data.startswith('v2_select_'):
        key = data.removeprefix('v2_select_')
        channel = s.CANALI.get(key)
        if channel is None or not channel.accessibile(update.effective_user.id):
            await mostra(s, update, 'Canale non disponibile.', menu_iniziale(s, update.effective_user.id))
            return s.ConversationHandler.END
        reset_flusso(context)
        context.user_data['canale_attivo'] = key
        await mostra(s, update, '📢 GESTIONE ' + channel.nome, menu_canale(s, channel))
        return s.ConversationHandler.END
    channel = selezionato(context, s.CANALI, update.effective_user.id)
    if channel is None:
        await mostra(s, update, 'Seleziona prima un canale.', menu_iniziale(s, update.effective_user.id))
        return s.ConversationHandler.END
    prefix = 'v2c:' + channel.chiave + ':'
    if not data.startswith(prefix):
        await mostra(s, update, 'Questa schermata appartiene a un altro canale. Apri il menu corrente.', menu_canale(s, channel))
        return s.ConversationHandler.END
    action = data[len(prefix):]
    reset_flusso(context)
    settings = s.ARCHIVIO.impostazioni(channel.chat_id)
    back = [('⬅️ Menu ' + channel.nome, prefix + 'menu')]
    if action == 'automatic':
        import invio_automatico
        return await invio_automatico.apri(s, update, context)
    elif action == 'rubrica':
        import rubrica
        return await rubrica.apri(s, update, context)
    elif action == 'posts':
        await mostra(s, update, '✍️ NUOVI POST — ' + channel.nome + '\n\nLa destinazione rimane questo canale per tutta la preparazione.',
                     tastiera(s, [[('📝 Invio singolo', 'nuova')], [('📦 Invio multiplo', 'rapido')], back]))
    elif action == 'repost':
        await mostra(s, update, '♻️ REPOST — ' + channel.nome +
                     f"\n\nCronologia: ultimi {settings['repost_giorni']} giorni.\n"
                     'Esclusi i prodotti delle ultime 24 ore e quelli già in coda nello stesso canale.\n'
                     f"Intervallo: {settings['intervallo']} minuti.\n\n"
                     'La ricerca parte quando scegli Avvia ricerca. Il lotto validato parte dopo conferma oppure dopo 2 minuti dal riepilogo.',
                     tastiera(s, [[('🎲 Avvia ricerca', 'repost')],
                                  [('🗓 7 giorni', prefix + 'days:7'), ('30 giorni', prefix + 'days:30'), ('90 giorni', prefix + 'days:90')],
                                  [('⏱ Impostazioni canale', prefix + 'settings')], back]))
    elif action.startswith('days:'):
        value = action.split(':')[1]
        if value in {'7', '30', '90'}:
            s.ARCHIVIO.salva(channel.chat_id, 'repost_giorni', value)
        await mostra(s, update, '✅ Periodo della cronologia salvato per ' + channel.nome,
                     tastiera(s, [[('♻️ Torna al repost', prefix + 'repost')], back]))
    elif action == 'settings':
        await mostra(s, update, '⚙️ IMPOSTAZIONI — ' + channel.nome +
                     f"\n\nIntervallo multiplo/repost: {settings['intervallo']} minuti\n"
                     f"Fascia: {settings['inizio']}–{settings['fine']} ({'attiva' if settings['attiva'] else 'disattivata'})\n"
                     'Tag affiliato: ' + (s.tag_canale(channel.chiave) or 'non configurato'),
                     tastiera(s, [[('⏱ Intervallo', prefix + 'edit:intervallo')],
                                  [('🕒 Fascia oraria', prefix + 'edit:fascia')],
                                  [('🔘 Attiva/disattiva fascia', prefix + 'toggle')],
                                  [('🔗 Tag affiliato', prefix + 'edit:tag')],
                                  [('🔎 Verifica collegamento', prefix + 'check')], back]))
    elif action == 'toggle':
        s.ARCHIVIO.salva(channel.chat_id, 'attiva', '0' if settings['attiva'] else '1')
        s.riallinea_programmati_fascia()
        await mostra(s, update, '✅ Fascia aggiornata per ' + channel.nome,
                     tastiera(s, [[('⚙️ Impostazioni canale', prefix + 'settings')], back]))
    elif action.startswith('edit:'):
        field = action.split(':')[1]
        prompts = {'intervallo': 'Scrivi l’intervallo in minuti, da 1 a 1440.',
                   'fascia': 'Scrivi inizio e fine nel formato HH:MM-HH:MM, ad esempio 08:30-21:30.',
                   'tag': 'Scrivi il tag affiliato del canale oppure PREDEFINITO per usare quello generale.'}
        if field in prompts:
            context.user_data['v2_input'] = (channel.chiave, field)
            await mostra(s, update, channel.nome + '\n\n' + prompts[field], tastiera(s, [back]))
            return INPUT
    elif action == 'check':
        try:
            member = await context.bot.get_chat_member(channel.chat_id, context.bot.id)
            valid = member.status == 'creator' or (member.status == 'administrator' and bool(getattr(member, 'can_post_messages', False)))
            text = '✅ Permesso di pubblicazione confermato.' if valid else '⚠️ Il bot non ha il permesso di pubblicare in questo canale.'
        except Exception:
            text = '⚠️ Collegamento non verificato. Controlla destinazione e permessi del bot.'
        await mostra(s, update, channel.nome + '\n\n' + text, tastiera(s, [back]))
    elif action.startswith(('history:', 'queue:')):
        kind, page = action.split(':')
        if not page.isdigit():
            return s.ConversationHandler.END
        table = 'recap_offerte' if kind == 'history' else 'programmazioni'
        rows, count, page = s.ARCHIVIO.lista(table, channel.chat_id, int(page))
        text = ('📚 CRONOLOGIA' if kind == 'history' else '📅 PROGRAMMATI E CODE') + ' — ' + channel.nome
        text += f'\n\nTotale: {count} · Pagina {page + 1}\n'
        buttons = []
        for row in rows:
            when = row.get('invio_previsto') or row.get('pubblicata_il')
            text += f"\n#{row['id']} · {str(row.get('nome') or '')[:80]}\n{s._data_archivio(when)} · {row.get('origine') or 'manuale'}\n"
        nav = []
        if page:
            nav.append(('⬅️ Precedenti', prefix + f'{kind}:{page - 1}'))
        if (page + 1) * 8 < count:
            nav.append(('Successivi ➡️', prefix + f'{kind}:{page + 1}'))
        if nav:
            buttons.append(nav)
        buttons.append(back)
        if rows:
            text += '\nQuale # vuoi aprire? Scrivi il numero del post, ad esempio 123 oppure #123.'
            context.user_data['v2_input'] = (channel.chiave, 'apri_' + kind)
        await mostra(s, update, text, tastiera(s, buttons))
        if rows:
            return INPUT
    elif action.startswith('editqueue:'):
        number = action.split(':')[1]
        row = s.ARCHIVIO.dettaglio('programmazioni', channel.chat_id, int(number)) if number.isdigit() else None
        if row and row['stato'] == 'attesa':
            context.user_data['prog_id'] = row['id']
            await s.invia_scheda_programmato(update.effective_message, row['id'])
            return s.PROG_GESTIONE
        await mostra(s, update, 'Post non più modificabile in questo canale.', tastiera(s, [back]))
    elif action.startswith(('view:', 'cancel:', 'cancelok:')):
        parts = action.split(':')
        kind = parts[1] if parts[0] == 'view' else 'queue'
        number = parts[-1]
        if kind not in {'history', 'queue'} or not number.isdigit():
            return s.ConversationHandler.END
        table = 'recap_offerte' if kind == 'history' else 'programmazioni'
        row = s.ARCHIVIO.dettaglio(table, channel.chat_id, int(number))
        if not row:
            await mostra(s, update, 'Post non trovato nella cronologia/coda di questo canale.', tastiera(s, [back]))
        elif parts[0] == 'cancelok':
            done = s.ARCHIVIO.annulla_programmato(channel.chat_id, row['id'])
            await mostra(s, update, '✅ Invio annullato.' if done else 'Il post non è più in attesa.', tastiera(s, [back]))
        elif parts[0] == 'cancel':
            await mostra(s, update, f"Annullare il post #{row['id']} su {channel.nome}?", tastiera(s, [[('✅ Conferma annullamento', prefix + 'cancelok:' + number)], back]))
        else:
            buttons = [back]
            if kind == 'queue' and row['stato'] == 'attesa':
                buttons.insert(0, [('❌ Annulla invio', prefix + 'cancel:' + number)])
                buttons.insert(0, [('✏️ Modifica post', prefix + 'editqueue:' + number)])
            text = channel.nome + f" · #{row['id']}\n\n{row.get('nome') or ''}\nPrezzo: {row.get('prezzo') or '—'} €\n{row.get('link') or ''}\nStato: {row.get('stato') or 'pubblicata'}"
            await mostra(s, update, text[:4000], tastiera(s, buttons))
    else:
        await mostra(s, update, '📢 GESTIONE ' + channel.nome, menu_canale(s, channel))
    return s.ConversationHandler.END


async def ricevi_impostazione(s, update, context):
    if not await s.controlla_autorizzazione(update):
        return s.ConversationHandler.END
    channel = selezionato(context, s.CANALI, update.effective_user.id)
    pending = context.user_data.get('v2_input')
    if channel is None or not pending or pending[0] != channel.chiave:
        return s.ConversationHandler.END
    field = pending[1]
    value = update.message.text.strip()
    if field in {'apri_history', 'apri_queue'}:
        number = value.removeprefix('#').strip()
        kind = field.removeprefix('apri_')
        table = 'recap_offerte' if kind == 'history' else 'programmazioni'
        row = s.ARCHIVIO.dettaglio(table, channel.chat_id, int(number)) if re.fullmatch(r'[0-9]{1,18}', number) else None
        if not row or (kind == 'queue' and row['stato'] not in {'attesa', 'in_invio', 'da_verificare'}):
            await update.message.reply_text('❌ Numero non valido o post non presente nell’elenco di questo canale. Quale # vuoi aprire?')
            return INPUT
        return await gestisci(s, update, context, data_override=f'v2c:{channel.chiave}:view:{kind}:{number}')
    if field == 'intervallo' and value.isdigit() and 1 <= int(value) <= 1440:
        s.ARCHIVIO.salva(channel.chat_id, field, int(value))
    elif field == 'fascia' and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d', value) and value[:5] < value[6:]:
        s.ARCHIVIO.salva(channel.chat_id, 'inizio', value[:5])
        s.ARCHIVIO.salva(channel.chat_id, 'fine', value[6:])
        s.riallinea_programmati_fascia()
    elif field == 'tag' and (value.upper() == 'PREDEFINITO' or re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value)):
        s.ARCHIVIO.salva(channel.chat_id, field, '' if value.upper() == 'PREDEFINITO' else value)
    else:
        await update.message.reply_text('❌ Valore non valido. Riprova oppure usa /annulla.')
        return INPUT
    context.user_data.pop('v2_input', None)
    await mostra(s, update, '✅ Impostazione salvata per ' + channel.nome, menu_canale(s, channel))
    return s.ConversationHandler.END
