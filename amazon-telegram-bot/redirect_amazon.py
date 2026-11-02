"""Segue soltanto redirect HTTP conosciuti e accetta prodotti Amazon verificati."""
import re
from urllib.parse import urljoin, urlsplit
import requests
from link_amazon import link_amazon_valido


def link_esterno_supportato(link):
    try:
        url = urlsplit(link)
        return url.scheme in ('http', 'https') and url.hostname in {'ofclub.click', 'www.ofclub.click'} and not url.username and url.port in (None, 80, 443)
    except (ValueError, TypeError):
        return False


def link_importabile(link):
    return link_amazon_valido(link) or link_esterno_supportato(link)


def risolvi(link):
    """Restituisce (link Amazon canonico, motivo). Non legge il corpo delle pagine."""
    corrente = link
    visti = set()
    try:
        for _ in range(6):
            url = urlsplit(corrente)
            if not link_importabile(corrente):
                return None, 'Destinazione non Amazon: ' + (url.hostname or 'indirizzo non valido')
            if link_amazon_valido(corrente):
                asin = re.search(r'^/(?:.*?/)?(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:/|$)', url.path, re.IGNORECASE)
                if url.hostname == 'link.amazon':
                    asin = re.fullmatch(r'/([A-Z0-9]{10})/?', url.path, re.IGNORECASE)
                if asin:
                    return 'https://www.amazon.it/dp/' + asin.group(1).upper(), None
            if corrente in visti:
                return None, 'Ciclo di reindirizzamenti: nessun prodotto Amazon identificato'
            visti.add(corrente)
            with requests.get(corrente, allow_redirects=False, stream=True, timeout=10,
                              headers={'User-Agent': 'Mozilla/5.0'}) as risposta:
                if risposta.status_code in (301, 302, 303, 307, 308):
                    destinazione = risposta.headers.get('Location')
                    if not destinazione:
                        return None, 'Reindirizzamento privo di destinazione'
                    corrente = urljoin(corrente, destinazione)
                elif risposta.status_code >= 400:
                    return None, f'Link breve non raggiungibile (HTTP {risposta.status_code})'
                else:
                    return None, 'La pagina non fornisce un reindirizzamento HTTP a un prodotto Amazon'
        return None, 'Troppi reindirizzamenti: prodotto Amazon non identificato'
    except requests.Timeout:
        return None, 'Timeout durante la risoluzione del link breve'
    except (requests.RequestException, ValueError):
        return None, 'Errore durante la risoluzione del link breve'
