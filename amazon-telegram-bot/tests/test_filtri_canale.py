import asyncio
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from filtri_canale import ArchivioFiltri, ambito, corrente, per_parametro


class FilterIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'test.db')
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE marchi_qualita(categoria TEXT,marchio TEXT);
                CREATE TABLE parole_indesiderate_qualita(parola TEXT);
                CREATE TABLE prodotti_prioritari(id INTEGER,categoria TEXT,parola TEXT,marchio TEXT,bonus INTEGER);
                CREATE TABLE parole_accessori_priorita(parola TEXT);
                INSERT INTO marchi_qualita VALUES('casa','Philips');
                INSERT INTO parole_indesiderate_qualita VALUES('generico');
                INSERT INTO prodotti_prioritari VALUES(1,'casa','aspirapolvere','Philips',3);
                INSERT INTO parole_accessori_priorita VALUES('custodia');
            ''')
        self.store = ArchivioFiltri(self.path)

    def test_initial_values_are_copied_then_changes_are_independent(self):
        self.assertEqual(self.store.leggi('tech'), self.store.leggi('casa'))
        with ambito('casa'):
            self.store.parola('parole', 'solo-casa', True)
            self.store.marchio('casa', 'Dyson', True)
            self.store.parola('accessori', 'ricambio-casa', True)
        for key in ('tech', 'sport'):
            data = self.store.leggi(key)
            self.assertNotIn('solo-casa', data['parole'])
            self.assertNotIn('Dyson', data['marchi']['casa'])
            self.assertNotIn('ricambio-casa', data['accessori'])
        self.assertIn('solo-casa', ArchivioFiltri(self.path).leggi('casa')['parole'])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT parola FROM parole_indesiderate_qualita').fetchall(), [('generico',)])

    def test_priority_ids_and_resets_are_scoped(self):
        self.store.leggi('tech')
        with ambito('casa'):
            self.store.priorita('casa', 'aspirapolvere', 'Philips', 9)
            self.assertEqual(self.store.leggi()['priorita'][0][4], 9)
            self.store.ripristina_filtri({'casa': ['Bosch']}, ['reset-casa'])
            self.assertEqual(self.store.leggi()['priorita'][0][4], 9)
            self.assertTrue(self.store.rimuovi_priorita(1, 'casa'))
        self.assertEqual(self.store.leggi('tech')['priorita'][0][4], 3)
        self.assertEqual(self.store.leggi('tech')['marchi']['casa'], ['Philips'])

    def test_case_insensitive_updates_match_legacy_behavior(self):
        with ambito('casa'):
            self.store.marchio('casa', 'PHILIPS', True)
            self.assertEqual(len(self.store.leggi()['marchi']['casa']), 1)
            self.assertTrue(self.store.marchio('casa', 'philips', False))
            self.assertEqual(self.store.leggi()['marchi']['casa'], [])


class AsyncScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_jobs_keep_their_own_channel_and_restore_context(self):
        barrier = asyncio.Event()
        results = []
        @per_parametro('canale')
        async def job(canale='tech'):
            await barrier.wait()
            await asyncio.sleep(0)
            results.append((canale, corrente()))
        one = asyncio.create_task(job('casa'))
        two = asyncio.create_task(job('sport'))
        barrier.set()
        await asyncio.gather(one, two)
        self.assertCountEqual(results, [('casa', 'casa'), ('sport', 'sport')])
        self.assertEqual(corrente(), 'tech')


if __name__ == '__main__':
    unittest.main()
