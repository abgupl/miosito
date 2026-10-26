"""BestPrice24h: persistent channel registry and administrator selection.

Foundation module; it does NOT change the running Telegram bot until integrated.
The caller must verify Telegram bot administrator permissions before register_channel.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


@contextmanager
def _db(db_path):
    db = sqlite3.connect(db_path, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA busy_timeout=20000')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(db_path, legacy_tech_id=None, legacy_casa_id=None):
    with _db(db_path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS bp_channels (
            chat_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            legacy_key TEXT UNIQUE,
            created_at TEXT NOT NULL
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS bp_active_channel (
            admin_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL,
            FOREIGN KEY(chat_id) REFERENCES bp_channels(chat_id)
        )''')
        db.execute('''CREATE TABLE IF NOT EXISTS bp_channel_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL, created_at TEXT NOT NULL,
            level TEXT NOT NULL, message TEXT NOT NULL
        )''')
        for key, chat_id, name in (
            ('tech', legacy_tech_id, 'BestPrice24h Tech'),
            ('casa', legacy_casa_id, 'BestPrice24h Casa'),
        ):
            if chat_id:
                db.execute('''INSERT OR IGNORE INTO bp_channels
                    (chat_id,display_name,legacy_key,created_at)
                    VALUES (?,?,?,?)''',
                    (str(chat_id), name, key, datetime.now(timezone.utc).isoformat()))


def register_channel(db_path, chat_id, display_name):
    if not str(chat_id).strip() or not display_name.strip():
        raise ValueError('ID e nome canale obbligatori')
    with _db(db_path) as db:
        db.execute('''INSERT INTO bp_channels(chat_id,display_name,created_at)
            VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET
            display_name=excluded.display_name, enabled=1''',
            (str(chat_id), display_name.strip(), datetime.now(timezone.utc).isoformat()))


def channels(db_path, include_disabled=False):
    with _db(db_path) as db:
        return [dict(r) for r in db.execute(
            'SELECT * FROM bp_channels' + ('' if include_disabled else ' WHERE enabled=1') +
            ' ORDER BY created_at, display_name')]


def select_channel(db_path, admin_id, chat_id):
    with _db(db_path) as db:
        found = db.execute('SELECT 1 FROM bp_channels WHERE chat_id=? AND enabled=1',
                           (str(chat_id),)).fetchone()
        if not found:
            raise ValueError('Canale inesistente o disattivato')
        db.execute('''INSERT INTO bp_active_channel(admin_id,chat_id) VALUES(?,?)
            ON CONFLICT(admin_id) DO UPDATE SET chat_id=excluded.chat_id''',
            (str(admin_id), str(chat_id)))


def active_channel(db_path, admin_id):
    with _db(db_path) as db:
        row = db.execute('''SELECT c.* FROM bp_active_channel a
            JOIN bp_channels c ON c.chat_id=a.chat_id
            WHERE a.admin_id=? AND c.enabled=1''', (str(admin_id),)).fetchone()
        return dict(row) if row else None


def record_event(db_path, chat_id, level, message):
    with _db(db_path) as db:
        db.execute('INSERT INTO bp_channel_events(chat_id,created_at,level,message) VALUES(?,?,?,?)',
                   (str(chat_id), datetime.now(timezone.utc).isoformat(), str(level), str(message)))


def channel_events(db_path, chat_id, limit=100):
    limit = max(1, min(int(limit), 3000))
    with _db(db_path) as db:
        return [dict(r) for r in db.execute('''SELECT * FROM bp_channel_events
            WHERE chat_id=? ORDER BY id DESC LIMIT ?''', (str(chat_id), limit))]
