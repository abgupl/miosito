"""Selezione deterministica di prodotti già reperiti per collage multicanale.

Non cerca prodotti su Amazon e non abilita alcuno scheduler.
"""
from decimal import Decimal, InvalidOperation
from bestprice_link_validation import valid_amazon_link

from bestprice_collections import read_config
from bestprice_collections_multichannel import require_channel


def _number(value):
    try:
        return Decimal(str(value).replace('€', '').replace(',', '.').strip())
    except (InvalidOperation, TypeError, ValueError):
        return None


def _amazon_link(url):
    """Reject deceptive non-Amazon destinations in automatically generated collages."""
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        return False
    host = url.hostname.lower().rstrip('.')
    return host in {'amazon.it', 'www.amazon.it', 'amzn.to', 'www.amzn.to',
                    'link.amazon', 'www.link.amazon'}


def select(db_path, chat_id, candidates, *, max_products=6):
    """Seleziona candidati validi rispettando i filtri del canale, senza fallback."""
    chat_id = require_channel(db_path, chat_id)
    config = read_config(db_path, chat_id)
    limit = min(int(config['quantita']), int(max_products), 6)
    if limit < 1:
        raise ValueError('Quantità non valida')
    selected, seen = [], set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        asin = str(candidate.get('asin') or '').strip().upper()
        name = str(candidate.get('nome') or '').strip()
        link = str(candidate.get('link') or '').strip()
        if not name or not valid_amazon_link(link):
            continue
        key = asin or link
        if key in seen:
            continue
        price = _number(candidate.get('prezzo'))
        discount = _number(candidate.get('sconto'))
        if price is None or price <= 0 or discount is None:
            continue
        if price > config['prezzo_massimo'] or discount < config['sconto_minimo']:
            continue
        seen.add(key)
        selected.append(candidate.copy())
        if len(selected) == limit:
            break
    return selected
