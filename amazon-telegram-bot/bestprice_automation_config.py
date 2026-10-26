"""Configurazioni indipendenti delle automazioni BestPrice24h.

Fase 4: configurazioni persistenti per ogni canale registrato.
Le automazioni di nuovi canali restano disabilitate finché lo scheduler non è migrato.
"""
import sqlite3
import bestprice_channels as registry

FIELDS = (
    'attiva', 'intervallo_minuti', 'ora_inizio', 'ora_fine',
    'prossimo_invio', 'sconto_minimo', 'qualita_prodotti',
    'punteggio_minimo', 'bonus_sconto_da', 'priorita_amazon',
    'tentativi_ricerca', 'giorni_blocco_duplicati', 'raggruppa_varianti',
)


def _validate(db_path, channel):
    if channel is None or not str(channel).strip():
        raise ValueError('Canale non selezionato')
    for item in registry.channels(db_path):
        if str(channel) in (str(item['chat_id']), str(item.get('legacy_key') or '')):
            return item.get('legacy_key') or str(item['chat_id'])
    raise ValueError('Canale inesistente o disattivato')


def config_key(channel, key, db_path=None):
    if db_path is None:
        if channel not in ('tech', 'casa'):
            raise ValueError('Database necessario per un nuovo canale')
        canonical = channel
    else:
        canonical = _validate(db_path, channel)
    if not isinstance(key, str) or not key.strip():
        raise ValueError('Chiave configurazione mancante')
    return key if canonical == 'tech' else f'{canonical}:{key}'


def read_config(db_path, channel, tech_categories, casa_categories):
    canonical = _validate(db_path, channel)
    with sqlite3.connect(db_path, timeout=20) as db:
        raw = dict(db.execute('SELECT chiave, valore FROM configurazione_automatica'))
        vals = {key: raw[config_key(canonical, key, db_path)] for key in FIELDS if config_key(canonical, key, db_path) in raw}
        allowed = tech_categories if canonical == 'tech' else casa_categories if canonical == 'casa' else set(tech_categories) | set(casa_categories)
        categories = [r[0] for r in db.execute(
            'SELECT categoria FROM categorie_automatiche_canali WHERE canale=? ORDER BY categoria',
            (canonical,)) if r[0] in allowed]
    return {
        'attiva': vals.get('attiva', '0') == '1',
        'intervallo_minuti': int(vals.get('intervallo_minuti', '120')),
        'ora_inizio': vals.get('ora_inizio', '09:00'),
        'ora_fine': vals.get('ora_fine', '21:00'),
        'prossimo_invio': vals.get('prossimo_invio', ''),
        'sconto_minimo': int(vals.get('sconto_minimo', '20')),
        'qualita_prodotti': vals.get('qualita_prodotti', 'selettiva'),
        'punteggio_minimo': int(vals.get('punteggio_minimo', '4')),
        'bonus_sconto_da': int(vals.get('bonus_sconto_da', '30')),
        'priorita_amazon': vals.get('priorita_amazon', '1') == '1',
        'tentativi_ricerca': 3,
        'giorni_blocco_duplicati': int(vals.get('giorni_blocco_duplicati', '10')),
        'raggruppa_varianti': vals.get('raggruppa_varianti', '1') == '1',
        'categorie': categories,
    }


def write_config(db_path, key, value, channel):
    if key not in FIELDS and not key.startswith(('raccolte_',)):
        raise ValueError('Chiave di automazione non riconosciuta')
    with sqlite3.connect(db_path, timeout=20) as db:
        db.execute('INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)',
                   (config_key(channel, key, db_path), str(value)))
