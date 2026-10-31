"""Riepilogo operativo in sola lettura, con paginazione per canale."""
import os
import sqlite3
from datetime import datetime, timedelta
import monitoraggio

VERSIONE = '2026.10.31-sole-luna'


def data_locale(s, value):
    if not value:
        return 'non previsto'
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=s.ROMA_TZ)
        return dt.astimezone(s.ROMA_TZ).strftime('%d/%m %H:%M')
    except ValueError:
        return 'data non valida'


def riepilogo(s, user_id, pagina=0):
    now = datetime.now(s.ROMA_TZ)
    channels = [c for c in s.CANALI.values() if c.accessibile(user_id)]
    pages = max(1, (len(channels) + 3) // 4)
    pagina = min(max(0, pagina), pages - 1)
    seconds = max(0, int((now - s._LOG_STARTED).total_seconds()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    commit = os.environ.get('RAILWAY_GIT_COMMIT_SHA', '').strip()
    lines = ['📊 STATO DEL BOT', 'Aggiornato: ' + now.strftime('%d/%m/%Y %H:%M:%S') + ' · Italia',
             'Versione: ' + VERSIONE,
             'Commit Railway: ' + (commit[:12] if commit else 'non disponibile'),
             f'Avvio processo: {data_locale(s, s._LOG_STARTED.isoformat())} · acceso da {days}g {hours}h {remainder // 60}m',
             'Monitoraggio post globale: ' + ('ATTIVO' if monitoraggio.attivo(s.DB_PATH) else 'DISATTIVATO'),
             'Ricerca nuove offerte: sorgente ' + ('disponibile' if s.SORGENTE_RICERCA_ATTIVA else 'DISABILITATA'),
             f'\n📢 Canali accessibili: {len(channels)} · Pagina {pagina+1}/{pages}']
    with sqlite3.connect(s.DB_PATH, timeout=30) as db:
        for channel in channels[pagina*4:pagina*4+4]:
            counts = dict(db.execute('SELECT stato,count(*) FROM programmazioni WHERE CAST(telegram_chat_id AS TEXT)=? GROUP BY stato', (str(channel.chat_id),)))
            post = db.execute("SELECT id,nome,invio_previsto FROM programmazioni WHERE CAST(telegram_chat_id AS TEXT)=? AND stato='attesa' ORDER BY invio_previsto,id LIMIT 1", (str(channel.chat_id),)).fetchone()
            cfg = s.leggi_config_automatica(channel.chiave)
            auto = 'DISATTIVATO' if not cfg['attiva'] else ('ATTIVO' if s.SORGENTE_RICERCA_ATTIVA else 'ABILITATO, BLOCCATO: sorgente assente')
            lines.extend(['\n' + channel.nome[:80],
                          f"Coda: {counts.get('attesa',0)} in attesa · {counts.get('in_invio',0)} in invio · {counts.get('da_verificare',0)} da verificare",
                          'Prossimo: ' + (f'#{post[0]} · {str(post[1] or "Senza titolo")[:65]} · {data_locale(s,post[2])} (previsto)' if post else 'nessun post in attesa'),
                          'Automatico: ' + auto])
            if cfg['attiva'] and s.SORGENTE_RICERCA_ATTIVA:
                lines.append('Prossima ricerca: ' + data_locale(s, cfg.get('prossimo_invio')))
        lines.append('\n☕ RUBRICA GLOBALE')
        quiz = s.configurazione_quiz()
        oro = s.configurazione_oroscopo()
        for label, enabled, slots, table, photo in [
            ('Quiz', quiz['attivo'], [quiz['ora']], 'quiz_giorni', quiz.get('foto')),
            ('Oroscopo', oro['attivo'], [time for _,time in s.orari_oroscopo(oro)], 'oroscopo_giorni', all(oro.get('foto_luna' if slot == 2 else 'foto_sole') or oro.get('foto') for slot, _ in s.orari_oroscopo(oro)))]:
            lines.append(label + ': ' + ('ATTIVO' if enabled else 'DISATTIVATO') + ' · ' + ', '.join(slots))
            if enabled:
                appointments = [datetime.fromisoformat((now.date()+timedelta(days=d)).isoformat()+'T'+time).replace(tzinfo=s.ROMA_TZ) for d in (0,1) for time in slots]
                next_slot = min(dt for dt in appointments if dt > now)
                available = db.execute('SELECT 1 FROM '+table+' WHERE giorno=? LIMIT 1', (next_slot.date().isoformat(),)).fetchone()
                lines.append('Prossimo orario: '+next_slot.strftime('%d/%m %H:%M')+' · testi '+('presenti' if available else 'MANCANTI')+' · foto '+('presente' if photo else 'MANCANTE'))
    lines.append('\n⚠️ ERRORI RECENTI (processo corrente)')
    entries = s._diagnostic_entries('errors')[-3:]
    lines.extend('['+stamp+'] '+ ' '.join(s._redact_log_line(line).split())[:180] for stamp,_,line in entries)
    if not entries:
        lines.append('Nessun errore registrato.')
    lines.append('\nGli orari sono previsti; non certificano permessi Telegram o disponibilità delle API.')
    return '\n'.join(lines), pagina, pages


async def apri(s, update, user_id, pagina=0):
    from menu_canali import tastiera
    text, page, pages = riepilogo(s, user_id, pagina)
    rows = []
    nav = []
    if page:
        nav.append(('⬅️ Canali precedenti', 'v2_status_'+str(page-1)))
    if page+1 < pages:
        nav.append(('Canali successivi ➡️', 'v2_status_'+str(page+1)))
    if nav:
        rows.append(nav)
    rows.extend([[('🔄 Aggiorna stato', 'v2_status_'+str(page))], [('⬅️ Impostazioni', 'v2_settings')]])
    await update.effective_message.reply_text(text, reply_markup=tastiera(s, rows))
