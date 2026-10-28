"""Impostazioni e consultazione V2: ogni operazione richiede una destinazione."""
import sqlite3


class ArchivioCanali:
    def __init__(self, path):
        self.path = str(path)

    def inizializza(self, canali, fascia_iniziale):
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS impostazioni_canali_v2 (
                chat_id TEXT NOT NULL, chiave TEXT NOT NULL, valore TEXT NOT NULL,
                PRIMARY KEY(chat_id,chiave))''')
            for channel in canali:
                defaults = {'intervallo': '30', 'repost_giorni': '7',
                            'attiva': '1' if fascia_iniziale['attiva'] else '0',
                            'inizio': fascia_iniziale['inizio'], 'fine': fascia_iniziale['fine']}
                db.executemany('INSERT OR IGNORE INTO impostazioni_canali_v2 VALUES (?,?,?)',
                               [(channel.chat_id, key, value) for key, value in defaults.items()])
            # I vecchi programmati senza destinazione appartenevano al canale principale.
            db.execute('UPDATE programmazioni SET telegram_chat_id=? WHERE telegram_chat_id IS NULL',
                       (canali[0].chat_id,))
            db.execute('UPDATE recap_offerte SET telegram_chat_id=? WHERE telegram_chat_id IS NULL',
                       (canali[0].chat_id,))
            db.execute('CREATE INDEX IF NOT EXISTS idx_recap_canale_v2 ON recap_offerte(telegram_chat_id,id)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_programmi_canale_v2 ON programmazioni(telegram_chat_id,stato)')

    def impostazioni(self, chat):
        with sqlite3.connect(self.path, timeout=30) as db:
            values = dict(db.execute('SELECT chiave,valore FROM impostazioni_canali_v2 WHERE chat_id=?', (str(chat),)))
        return {'intervallo': int(values.get('intervallo', '30')),
                'repost_giorni': int(values.get('repost_giorni', '7')),
                'attiva': values.get('attiva', '1') == '1',
                'inizio': values.get('inizio', '08:30'), 'fine': values.get('fine', '21:30'),
                'tag': values.get('tag', '')}

    def salva(self, chat, chiave, valore):
        if not str(chat) or chiave not in {'intervallo', 'repost_giorni', 'attiva', 'inizio', 'fine', 'tag'}:
            raise ValueError('Impostazione canale non valida')
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute('INSERT OR REPLACE INTO impostazioni_canali_v2 VALUES (?,?,?)', (str(chat), chiave, str(valore)))

    def lista(self, tabella, chat, pagina=0, ricerca=''):
        if tabella not in {'recap_offerte', 'programmazioni'}:
            raise ValueError('Archivio non valido')
        clause = "CAST(telegram_chat_id AS TEXT)=?"
        args = [str(chat)]
        if tabella == 'programmazioni':
            clause += " AND stato IN ('attesa','in_invio','da_verificare')"
        if ricerca:
            clause += " AND (instr(lower(COALESCE(nome,'')),lower(?))>0 OR instr(lower(COALESCE(asin,'')),lower(?))>0)" if tabella == 'recap_offerte' else " AND instr(lower(COALESCE(nome,'')),lower(?))>0"
            args.extend([ricerca, ricerca] if tabella == 'recap_offerte' else [ricerca])
        with sqlite3.connect(self.path, timeout=30) as db:
            db.row_factory = sqlite3.Row
            count = db.execute(f'SELECT count(*) FROM {tabella} WHERE {clause}', args).fetchone()[0]
            page = min(max(0, pagina), max(0, (count - 1) // 8))
            order = 'invio_previsto ASC,id ASC' if tabella == 'programmazioni' else 'id DESC'
            rows = db.execute(f'SELECT * FROM {tabella} WHERE {clause} ORDER BY {order} LIMIT 8 OFFSET ?', args + [page * 8]).fetchall()
        return [dict(r) for r in rows], count, page

    def dettaglio(self, tabella, chat, record_id):
        if tabella not in {'recap_offerte', 'programmazioni'}:
            raise ValueError('Archivio non valido')
        with sqlite3.connect(self.path, timeout=30) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(f'SELECT * FROM {tabella} WHERE id=? AND CAST(telegram_chat_id AS TEXT)=?',
                             (record_id, str(chat))).fetchone()
        return dict(row) if row else None

    def annulla_programmato(self, chat, record_id):
        with sqlite3.connect(self.path, timeout=30) as db:
            return db.execute("UPDATE programmazioni SET stato='annullata' WHERE id=? AND CAST(telegram_chat_id AS TEXT)=? AND stato='attesa'",
                              (record_id, str(chat))).rowcount == 1
