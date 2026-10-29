"""SQLite locale: richieste, iscrizioni alle richieste, app e avvisi persistenti."""
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

PLATFORMS = {"android": "Android", "fire": "Fire TV Stick", "ios": "iPhone e iPad", "windows": "Windows", "mac": "Mac Intel"}
STATUSES = {"received": "Ricevuta", "working": "In lavorazione", "available": "Disponibile", "unavailable": "Non reperibile"}


def validate_app(value):
    if not isinstance(value, dict):
        raise ValueError("Inserisci un oggetto JSON.")
    name, url = value.get("name"), value.get("url")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Nome obbligatorio, massimo 80 caratteri.")
    if not isinstance(url, str) or len(url) > 1000 or urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc:
        raise ValueError("Inserisci un link http o https valido.")
    platforms = value.get("platforms")
    if not isinstance(platforms, list) or not platforms or any(not isinstance(p, str) or p not in PLATFORMS for p in platforms):
        raise ValueError("Piattaforme ammesse: android, fire, ios, windows, mac.")
    code, notes = value.get("code", ""), value.get("notes", "")
    if not isinstance(code, str) or (code and not code.isdigit()) or len(code) > 20:
        raise ValueError("Il codice Downloader deve essere una stringa numerica.")
    if not isinstance(notes, str) or len(notes) > 1500:
        raise ValueError("Note: massimo 1500 caratteri.")
    return dict(name=name.strip(), url=url, platforms=list(dict.fromkeys(platforms)), code=code, notes=notes)


class Store:
    def __init__(self, path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS requests (
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
          details TEXT NOT NULL, dedup TEXT UNIQUE NOT NULL, status TEXT NOT NULL DEFAULT 'received',
          created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS followers (
          request_id INTEGER REFERENCES requests(id), user_id INTEGER NOT NULL,
          PRIMARY KEY(request_id,user_id));
        CREATE TABLE IF NOT EXISTS apps (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS notifications (
          request_id INTEGER REFERENCES requests(id), user_id INTEGER NOT NULL,
          PRIMARY KEY(request_id,user_id));
        """)
        if not self.db.execute("SELECT 1 FROM meta WHERE key='seeded'").fetchone():
            names = [("Sky Glass", "829789"), ("Legend 4", "528188"), ("Blue Legend+", "973091"), ("000 Player", "6913771"), ("Next+", "6073149"), ("Castora", "7539534")]
            for name, code in names:
                self.save_app(dict(name=name, url=f"http://aftv.news/{code}", code=code, platforms=["android", "fire"], notes="Link fornito dal gestore. Compatibilità Android/Fire TV Stick da verificare prima dell'installazione."))
            for name, url, platform in [
                ("20 Platform", "https://apps.apple.com/eg/app/20-platform/id6502774600", "ios"),
                ("iPlay Windows", "https://apks.splayer.in/windows/iplay.exe", "windows"),
                ("iPlay Mac Intel", "https://apks.splayer.in/mac/iplay.dmg", "mac")]:
                self.save_app(dict(name=name, url=url, platforms=[platform], code="", notes="Link fornito dal gestore."))
            self.db.execute("INSERT INTO meta VALUES ('seeded')")
        self.db.commit()

    def request(self, kind, title, details, user):
        key = json.dumps([kind, " ".join(title.casefold().split()), " ".join(details.casefold().split())])
        with self.db:
            row = self.db.execute("SELECT id FROM requests WHERE dedup=?", (key,)).fetchone()
            new = row is None
            rid = self.db.execute("INSERT INTO requests(kind,title,details,dedup) VALUES (?,?,?,?)", (kind,title,details,key)).lastrowid if new else row[0]
            self.db.execute("INSERT OR IGNORE INTO followers VALUES (?,?)", (rid,user))
        return rid, new

    def get_request(self, rid, user=None):
        sql = "SELECT r.*, (SELECT count(*) FROM followers f WHERE f.request_id=r.id) AS followers FROM requests r WHERE r.id=?"
        args = [rid]
        if user is not None:
            sql += " AND EXISTS (SELECT 1 FROM followers f WHERE f.request_id=r.id AND f.user_id=?)"
            args.append(user)
        return self.db.execute(sql, args).fetchone()

    def requests(self, user=None):
        if user is None:
            return self.db.execute("SELECT * FROM requests ORDER BY id DESC").fetchall()
        return self.db.execute("SELECT r.* FROM requests r JOIN followers f ON f.request_id=r.id WHERE f.user_id=? ORDER BY r.id DESC", (user,)).fetchall()

    def status(self, rid, status):
        if status not in STATUSES:
            raise ValueError("Stato non valido")
        with self.db:
            row = self.get_request(rid)
            if row is None:
                return False
            if row['status'] == status:
                return False
            self.db.execute("UPDATE requests SET status=? WHERE id=?", (status,rid))
            self.db.execute("DELETE FROM notifications WHERE request_id=?", (rid,))
            if status == "available":
                self.db.execute("INSERT INTO notifications SELECT request_id,user_id FROM followers WHERE request_id=?", (rid,))
        return True

    def apps(self, platform=None):
        rows = [dict(id=r['id'], **json.loads(r['data'])) for r in self.db.execute("SELECT * FROM apps ORDER BY id")]
        return [r for r in rows if platform is None or platform in r['platforms']]

    def app(self, aid):
        return next((a for a in self.apps() if a['id'] == aid), None)

    def save_app(self, value, aid=None):
        data = json.dumps(validate_app(value), ensure_ascii=False)
        with self.db:
            if aid is None:
                return self.db.execute("INSERT INTO apps(data) VALUES (?)", (data,)).lastrowid
            self.db.execute("UPDATE apps SET data=? WHERE id=?", (data,aid))
        return aid

    def delete_app(self, aid):
        with self.db:
            self.db.execute("DELETE FROM apps WHERE id=?", (aid,))
