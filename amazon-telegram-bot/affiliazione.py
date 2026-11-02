"""Unico tag affiliato persistente per tutti i canali; fallback all'ambiente."""
import re
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from link_amazon import link_amazon_valido


def _tabella(db):
    db.execute('CREATE TABLE IF NOT EXISTS affiliazione_globale (id INTEGER PRIMARY KEY CHECK(id=1), tag TEXT NOT NULL)')


def leggi(path, env):
    with sqlite3.connect(path, timeout=30) as db:
        _tabella(db)
        row = db.execute('SELECT tag FROM affiliazione_globale WHERE id=1').fetchone()
    return row[0] if row else (env.get('AMAZON_PARTNER_TAG') or env.get('AMAZON_ASSOCIATE_TAG') or '').strip()


def salva(path, tag):
    tag = str(tag).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', tag):
        raise ValueError('Tag non valido: inserisci soltanto il tag, non il link Amazon.')
    with sqlite3.connect(path, timeout=30) as db:
        _tabella(db)
        db.execute('INSERT OR REPLACE INTO affiliazione_globale VALUES (1,?)', (tag,))


def applica(link, tag):
    if not tag:
        raise ValueError('Configura il tuo tag in Impostazioni generali → Tag affiliato.')
    if not link_amazon_valido(link):
        raise ValueError('Link Amazon non valido.')
    url = urlsplit(link)
    parametri = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True) if k.lower() != 'tag']
    parametri.append(('tag', tag))
    return urlunsplit((url.scheme, url.netloc, url.path, urlencode(parametri), url.fragment))
