"""Filtro d'ingresso condiviso: non certifica disponibilità o marketplace finale."""
import re
from urllib.parse import urlsplit


def link_amazon_valido(link):
    try:
        parsed = urlsplit(str(link or '').strip())
        host = (parsed.hostname or '').lower()
        return parsed.scheme in ('http', 'https') and (
            host in {'amzn.to', 'amzn.eu', 'a.co', 'link.amazon'}
            or host == 'amazon.it' or host.endswith('.amazon.it')
            or bool(re.fullmatch(r'(?:www\.)?amazon\.(?:[a-z]{2,3}|(?:co|com)\.[a-z]{2})', host))
        )
    except (ValueError, TypeError):
        return False
