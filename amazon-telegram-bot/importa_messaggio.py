"""Importazione di link da testo, didascalie, entità e pulsanti disponibili."""
import re
from link_amazon import link_amazon_valido


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
    return [link for link in unici if link_amazon_valido(link)], sum(not link_amazon_valido(link) for link in unici)


async def apri(servizi, update, context):
    import invio_multiplo
    return await invio_multiplo.rapido_da_comando(servizi, update, context, importa=True)
