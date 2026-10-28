"""Regole indipendenti per canale, inizializzate dai filtri legacy senza modificarli."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import json
import sqlite3

_canale = ContextVar('canale_filtri', default='tech')


def corrente():
    return _canale.get()


@contextmanager
def ambito(canale):
    token = _canale.set(canale)
    try:
        yield
    finally:
        _canale.reset(token)


def per_parametro(nome):
    def decorator(function):
        signature = inspect.signature(function)
        @wraps(function)
        async def scoped(*args, **kwargs):
            values = signature.bind(*args, **kwargs)
            values.apply_defaults()
            with ambito(values.arguments[nome]):
                return await function(*args, **kwargs)
        return scoped
    return decorator


def fisso(canale):
    def decorator(function):
        @wraps(function)
        async def scoped(*args, **kwargs):
            with ambito(canale):
                return await function(*args, **kwargs)
        return scoped
    return decorator


class ArchivioFiltri:
    def __init__(self, path):
        self.path = str(path)

    def _carica(self, db, canale):
        db.execute('''CREATE TABLE IF NOT EXISTS filtri_indipendenti_v2 (
            canale TEXT PRIMARY KEY, dati TEXT NOT NULL)''')
        row = db.execute('SELECT dati FROM filtri_indipendenti_v2 WHERE canale=?', (canale,)).fetchone()
        if row:
            return json.loads(row[0])
        brands = {}
        for category, brand in db.execute('SELECT categoria,marchio FROM marchi_qualita'):
            brands.setdefault(category, []).append(brand)
        priorities = [list(r) for r in db.execute('SELECT id,categoria,parola,marchio,bonus FROM prodotti_prioritari')]
        data = {'marchi': brands,
                'parole': [r[0] for r in db.execute('SELECT parola FROM parole_indesiderate_qualita')],
                'priorita': priorities,
                'accessori': [r[0] for r in db.execute('SELECT parola FROM parole_accessori_priorita')],
                'next_id': max((r[0] for r in priorities), default=0) + 1}
        db.execute('INSERT INTO filtri_indipendenti_v2 VALUES (?,?)', (canale, json.dumps(data, ensure_ascii=False)))
        return data

    def leggi(self, canale=None):
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute('BEGIN IMMEDIATE')
            return self._carica(db, canale or corrente())

    def modifica(self, function, canale=None):
        canale = canale or corrente()
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute('BEGIN IMMEDIATE')
            data = self._carica(db, canale)
            result = function(data)
            db.execute('UPDATE filtri_indipendenti_v2 SET dati=? WHERE canale=?', (json.dumps(data, ensure_ascii=False), canale))
            return result

    def marchio(self, categoria, valore, aggiungi):
        def edit(data):
            values = data['marchi'].setdefault(categoria, [])
            found = next((v for v in values if v.casefold() == valore.casefold()), None)
            if aggiungi and found is None:
                values.append(valore)
            elif not aggiungi and found is not None:
                values.remove(found)
            return found is not None
        return self.modifica(edit)

    def parola(self, campo, valore, aggiungi):
        if campo not in {'parole', 'accessori'}:
            raise ValueError('Filtro non valido')
        def edit(data):
            values = data[campo]
            found = next((v for v in values if v.casefold() == valore.casefold()), None)
            if aggiungi and found is None:
                values.append(valore)
            elif not aggiungi and found is not None:
                values.remove(found)
            return found is not None
        return self.modifica(edit)

    def priorita(self, categoria, parola, marchio, bonus):
        def edit(data):
            for row in data['priorita']:
                if row[1] == categoria and row[2].casefold() == parola.casefold() and row[3].casefold() == marchio.casefold():
                    row[2:] = [parola, marchio, bonus]
                    return row[0]
            number = data['next_id']
            data['next_id'] += 1
            data['priorita'].append([number, categoria, parola, marchio, bonus])
            return number
        return self.modifica(edit)

    def rimuovi_priorita(self, numero, categoria):
        def edit(data):
            old = len(data['priorita'])
            data['priorita'] = [r for r in data['priorita'] if not (r[0] == numero and r[1] == categoria)]
            return old != len(data['priorita'])
        return self.modifica(edit)

    def ripristina_filtri(self, marchi, parole):
        def edit(data):
            data['marchi'] = {k: list(v) for k, v in marchi.items()}
            data['parole'] = list(parole)
        self.modifica(edit)

    def ripristina_priorita(self, regole, accessori):
        def edit(data):
            data['priorita'] = []
            for category, rows in regole.items():
                for word, brand, bonus in rows:
                    data['priorita'].append([data['next_id'], category, word, brand, bonus])
                    data['next_id'] += 1
            data['accessori'] = list(accessori)
        self.modifica(edit)
