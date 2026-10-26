"""Risoluzione sicura delle destinazioni per rubriche condivise.

Non assegna mai una destinazione di ripiego: un canale deve esistere
nel registro ed essere abilitato. Le rubriche legacy usano 'tech'/'casa'.
"""

from bestprice_channels import channels


def resolve_rubric_channel(db_path, identifier):
    if identifier is None or not str(identifier).strip():
        raise ValueError('Destinazione rubrica mancante')
    key = str(identifier).strip()
    matches = [row for row in channels(db_path) if
               str(row['chat_id']) == key or row.get('legacy_key') == key]
    if len(matches) != 1:
        raise ValueError(f'Canale rubrica non registrato, disattivato o ambiguo: {key}')
    return str(matches[0]['chat_id'])
