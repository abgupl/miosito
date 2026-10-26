"""Collage multicanale: pubblicazione esplicita e cronologia isolata.

I renderer e la ricerca prodotti vengono forniti dal chiamante. Nessun fallback.
"""
import sqlite3
from bestprice_link_validation import valid_amazon_link
from datetime import datetime, timezone


def require_channel(db_path, chat_id):
    if chat_id is None or not str(chat_id).strip():
        raise ValueError('Canale obbligatorio')
    with sqlite3.connect(db_path) as db:
        row = db.execute('SELECT enabled FROM bp_channels WHERE chat_id=?', (str(chat_id),)).fetchone()
    if not row or row[0] != 1:
        raise ValueError('Canale inesistente o disattivato')
    return str(chat_id)


def initialize(db_path):
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS bp_collages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL, tema TEXT NOT NULL,
            telegram_message_id INTEGER NOT NULL,
            telegram_photo_file_id TEXT,
            pubblicata_il TEXT NOT NULL, stato TEXT NOT NULL DEFAULT 'pubblicata'
        )''')
        db.execute('''CREATE INDEX IF NOT EXISTS idx_bp_collages_channel
            ON bp_collages(chat_id, pubblicata_il DESC)''')
        db.execute('''CREATE TABLE IF NOT EXISTS bp_collage_products (
            collage_id INTEGER NOT NULL, posizione INTEGER NOT NULL,
            asin TEXT, nome TEXT NOT NULL, link TEXT NOT NULL,
            prezzo TEXT, vecchio_prezzo TEXT, immagine_url TEXT,
            sconto INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(collage_id, posizione),
            FOREIGN KEY(collage_id) REFERENCES bp_collages(id)
        )''')


def save(db_path, chat_id, tema, message, prodotti):
    chat_id = require_channel(db_path, chat_id)
    if not prodotti:
        raise ValueError('La raccolta non contiene prodotti')
    photo = getattr(message, 'photo', None)
    photo_id = photo[-1].file_id if photo else None
    with sqlite3.connect(db_path) as db:
        cursor = db.execute('''INSERT INTO bp_collages
            (chat_id,tema,telegram_message_id,telegram_photo_file_id,pubblicata_il)
            VALUES (?,?,?,?,?)''',
            (chat_id, tema, message.message_id, photo_id, datetime.now(timezone.utc).isoformat()))
        cid = cursor.lastrowid
        for pos, p in enumerate(prodotti, 1):
            db.execute('''INSERT INTO bp_collage_products
                (collage_id,posizione,asin,nome,link,prezzo,vecchio_prezzo,immagine_url,sconto)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (cid, pos, p.get('asin'), p['nome'], p['link'],
                 str(p.get('prezzo') or ''), str(p.get('vecchio_prezzo') or ''),
                 p.get('immagine'), int(p.get('sconto') or 0)))
    return cid


def history(db_path, chat_id, limit=10):
    chat_id = require_channel(db_path, chat_id)
    limit = int(limit)
    if not 1 <= limit <= 100:
        raise ValueError('Limite non valido')
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute('''SELECT id, tema, chat_id AS telegram_chat_id,
            telegram_message_id, telegram_photo_file_id, pubblicata_il, stato
            FROM bp_collages WHERE chat_id=? ORDER BY pubblicata_il DESC,id DESC LIMIT ?''',
            (chat_id, limit))]


async def publish(bot, db_path, chat_id, prodotti, tema, renderer, caption_builder):
    chat_id = require_channel(db_path, chat_id)
    if not 1 <= len(prodotti) <= 6:
        raise ValueError('Servono da 1 a 6 prodotti')
    # Verifica dati prima di inviare, per non creare post non tracciabili.
    for p in prodotti:
        if not p.get('nome') or not valid_amazon_link(p.get('link')):
            raise ValueError('Prodotto senza nome o con link Amazon non valido')
    import asyncio
    collage = await asyncio.to_thread(renderer, prodotti, tema)
    caption = caption_builder(prodotti, tema)
    message = await bot.send_photo(chat_id=chat_id, photo=collage, caption=caption, parse_mode='HTML')
    try:
        save(db_path, chat_id, tema, message, prodotti)
    except Exception:
        # Non ripetere l'invio: il messaggio potrebbe essere già pubblicato.
        raise RuntimeError('Collage inviato, ma cronologia non salvata: verificare manualmente')
    return message
