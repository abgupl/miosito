"""Importazione di link da testo, didascalie, entità e pulsanti disponibili."""
import re
from redirect_amazon import link_importabile


def estrai_link(messaggio):
    trovati = []
    for campo, entita in (('text', 'entities'), ('caption', 'caption_entities')):
        testo = getattr(messaggio, campo, None) or ''
        posizioni = [(m.start(), m.group()) for m in re.finditer(r'https?://[^\s<>;"\u201c\u201d]+', testo, re.IGNORECASE)]
        for e in getattr(messaggio, entita, None) or ():
            if e.type != 'text_link':
                continue
            # Telegram misura offset e lunghezza in unità UTF-16, anche con emoji.
            inizio = len(testo.encode('utf-16-le')[:e.offset * 2].decode('utf-16-le'))
            link = e.url
            posizioni.append((inizio, link))
        trovati.extend(link.rstrip('.,;:!?)]}\u00bb') for _, link in sorted(posizioni, key=lambda item: item[0]))
    markup = getattr(messaggio, 'reply_markup', None)
    for riga in getattr(markup, 'inline_keyboard', ()) or ():
        trovati.extend(b.url for b in riga if getattr(b, 'url', None))
    # Deduplica le due rappresentazioni dello stesso collegamento Telegram.
    unici = list(dict.fromkeys(trovati))
    return [link for link in unici if link_importabile(link)], sum(not link_importabile(link) for link in unici)


async def raccogli(servizi, update, context, draft, links, ignorati):
    raccolti = draft.setdefault('link_raccolti', [])
    nuovi = [link for link in links if link not in raccolti]
    if len(raccolti) + len(nuovi) > 50:
        await update.message.reply_text('Limite di 50 link per lotto: questo messaggio non è stato aggiunto. Elabora quelli già raccolti oppure annulla.', reply_markup=servizi.tastiera_multiplo(draft))
        return servizi.RAPIDO
    identita = (getattr(update.message, 'chat_id', None), getattr(update.message, 'message_id', None))
    visti = draft.setdefault('messaggi_importati', set())
    if identita[1] is not None and identita in visti:
        return servizi.RAPIDO
    if identita[1] is not None:
        visti.add(identita)
    raccolti.extend(nuovi)
    draft['messaggi_ricevuti'] = draft.get('messaggi_ricevuti', 0) + 1
    draft['ricevuti'] = draft.get('ricevuti', 0) + len(links)
    draft['duplicati'] += len(links) - len(nuovi)
    if ignorati:
        draft['scartati'].append(f'{ignorati} link non supportati ignorati nel messaggio {draft["messaggi_ricevuti"]}')
    await update.message.reply_text(
        f'📩 Messaggi raccolti: {draft["messaggi_ricevuti"]}\n🔗 Link distinti: {len(raccolti)}\n\n'
        'Puoi inoltrare altri messaggi. Quando hai finito premi Elabora messaggi: la lettura non parte prima.',
        reply_markup=servizi.tastiera_multiplo(draft))
    return servizi.RAPIDO


async def apri(servizi, update, context):
    import invio_multiplo
    return await invio_multiplo.rapido_da_comando(servizi, update, context, importa=True)
