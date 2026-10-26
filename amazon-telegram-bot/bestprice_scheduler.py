"""Pure, fail-closed helpers for BestPrice24h multi-channel scheduling.

No Telegram API calls or implicit TECH fallback. Caller owns persistence and delivery.
"""
from datetime import datetime, timedelta


def channel_key(record):
    if not record or not record.get('enabled'):
        raise ValueError('Canale non registrato o disattivato')
    key = record.get('legacy_key') or str(record.get('chat_id') or '').strip()
    if not key:
        raise ValueError('Identificativo canale mancante')
    return key


def slot_key(record, at):
    if not isinstance(at, datetime):
        raise TypeError('Data slot non valida')
    return f'{channel_key(record)}:{at:%H:%M}'


def eligible(record, config, *, allow_dynamic=False):
    """Dynamic channels require explicit rollout and a configured category list."""
    key = channel_key(record)
    if key not in ('tech', 'casa') and not allow_dynamic:
        return False
    return bool(config.get('attiva') and config.get('categorie'))


def destination_id(record):
    channel_key(record)
    chat_id = str(record['chat_id']).strip()
    if not chat_id:
        raise ValueError('ID destinazione mancante')
    return chat_id
