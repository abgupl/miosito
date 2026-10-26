"""Cronologia collage per canale: lettura sicura delle tabelle legacy TECH/CASA.

Non migra o modifica dati storici. Per canali aggiunti non esistono ancora
collage pubblicabili: la cronologia restituisce una lista vuota.
"""
import sqlite3


def collection_history(db_path, chat_id, tech_id, casa_id, limit=30):
    if chat_id is None or not str(chat_id).strip():
        raise ValueError('Canale obbligatorio')
    limit = int(limit)
    if not 1 <= limit <= 100:
        raise ValueError('Limite tra 1 e 100')
    chat_id = str(chat_id)
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        channel = db.execute(
            'SELECT enabled FROM bp_channels WHERE chat_id=?', (chat_id,)
        ).fetchone()
        if channel is None or channel['enabled'] != 1:
            raise ValueError('Canale inesistente o disattivato')
        if chat_id == str(tech_id):
            table = 'raccolte_tech'
        elif chat_id == str(casa_id):
            table = 'raccolte_casa'
        else:
            return []
        # Table name is selected only from the two hardcoded, trusted literals.
        rows = db.execute(
            f'''SELECT id, tema, telegram_chat_id, telegram_message_id,
                       telegram_photo_file_id, pubblicata_il, stato
                FROM {table} WHERE telegram_chat_id=?
                ORDER BY pubblicata_il DESC, id DESC LIMIT ?''',
            (chat_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
