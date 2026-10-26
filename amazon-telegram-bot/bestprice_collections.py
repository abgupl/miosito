"""BestPrice24h - raccolte multi-prodotto: configurazioni isolate per canale.

Modulo preparatorio: non abilita la pubblicazione per nuovi canali.
Le raccolte storiche TECH/CASA restano gestite dal codice legacy.
"""
import sqlite3

DEFAULTS = {
    'attive': '0', 'frequenza_post': '4', 'quantita': '4',
    'prezzo_massimo': '75', 'sconto_minimo': '10',
    'qualita': 'standard', 'indice_tema': '0', 'ultimo_tentativo': '',
}
INTEGER_FIELDS = {'frequenza_post', 'quantita', 'prezzo_massimo', 'sconto_minimo', 'indice_tema'}

def _registered(db, chat_id):
    row = db.execute('SELECT enabled FROM bp_channels WHERE chat_id=?', (str(chat_id),)).fetchone()
    if row is None or not row[0]:
        raise ValueError('Canale non registrato o disattivato')

def _prefix(chat_id):
    return 'channel:' + str(chat_id) + ':raccolte_'

def read_config(db_path, chat_id):
    with sqlite3.connect(db_path) as db:
        _registered(db, chat_id)
        rows = db.execute('SELECT chiave, valore FROM configurazione_automatica WHERE chiave LIKE ?',
                          (_prefix(chat_id) + '%',)).fetchall()
    stored = {key[len(_prefix(chat_id)):]: value for key, value in rows}
    result = {**DEFAULTS, **stored}
    for field in INTEGER_FIELDS:
        try:
            result[field] = int(result[field])
        except (ValueError, TypeError):
            result[field] = int(DEFAULTS[field])
    result['attive'] = result['attive'] == '1'
    return result

def save_config(db_path, chat_id, field, value):
    if field not in DEFAULTS:
        raise ValueError('Impostazione raccolta non riconosciuta')
    if field in INTEGER_FIELDS:
        value = int(value)
        if value < 0 or (field in {'frequenza_post', 'quantita'} and value < 1):
            raise ValueError('Valore fuori intervallo')
    elif field == 'attive':
        value = '1' if value in (True, 1, '1') else '0'
    with sqlite3.connect(db_path) as db:
        _registered(db, chat_id)
        db.execute('INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES (?,?)',
                   (_prefix(chat_id) + field, str(value)))

def count_since(db_path, chat_id, since=None, origin=None):
    """Conta soltanto i post del canale, con eventuale data e origine."""
    with sqlite3.connect(db_path) as db:
        _registered(db, chat_id)
        sql = 'SELECT COUNT(*) FROM recap_offerte WHERE telegram_chat_id=?'
        params = [str(chat_id)]
        if since is not None:
            sql += ' AND pubblicata_il>?'
            params.append(since)
        if origin is not None:
            sql += ' AND origine=?'
            params.append(origin)
        return db.execute(sql, params).fetchone()[0]
