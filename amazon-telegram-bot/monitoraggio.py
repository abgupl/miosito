"""Interruttore persistente del monitoraggio, condiviso da tutti i canali."""
import sqlite3
from functools import wraps


def attivo(path):
    with sqlite3.connect(path, timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS monitoraggio_globale (id INTEGER PRIMARY KEY CHECK(id=1), attivo INTEGER NOT NULL)')
        row = db.execute('SELECT attivo FROM monitoraggio_globale WHERE id=1').fetchone()
    return bool(row and row[0])


def imposta(path, enabled):
    attivo(path)
    with sqlite3.connect(path, timeout=30) as db:
        db.execute('INSERT OR REPLACE INTO monitoraggio_globale VALUES (1,?)', (int(bool(enabled)),))


def solo_se_attivo(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        import sys
        if not attivo(sys.modules[function.__module__].DB_PATH):
            return
        return await function(*args, **kwargs)
    return wrapped
