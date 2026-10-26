"""Routing protetto delle raccolte: mantiene i renderer legacy TECH/CASA.

I nuovi canali non sono ancora supportati dal renderer/persistenza collage.
"""
import sqlite3


def resolve_legacy_collection(db_path, chat_id, tech_id, casa_id):
    if chat_id is None or not str(chat_id).strip():
        raise ValueError('Destinazione raccolta obbligatoria')
    requested = str(chat_id)
    with sqlite3.connect(db_path) as db:
        row = db.execute('SELECT enabled FROM bp_channels WHERE chat_id=?', (requested,)).fetchone()
    if row is None or row[0] != 1:
        raise ValueError('Canale raccolta inesistente o disattivato')
    if requested == str(tech_id):
        return 'tech'
    if requested == str(casa_id):
        return 'casa'
    raise ValueError('Collage del nuovo canale non ancora integrato: invio bloccato')
