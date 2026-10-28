"""Regressioni dei moduli di invio, senza rete né credenziali Telegram."""
import ast
import asyncio
import random
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import invio_multiplo
import invio_singolo
import repost


def asin(link):
    return link.rsplit('/', 1)[-1]


class RepostHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'test.db')
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE recap_offerte (
                    id INTEGER PRIMARY KEY, asin TEXT, link TEXT,
                    pubblicata_il TEXT, nome TEXT, foto_file_id TEXT,
                    categoria TEXT, telegram_chat_id TEXT, origine TEXT);
                CREATE TABLE programmazioni (
                    link TEXT, stato TEXT, telegram_chat_id TEXT);
            ''')
        self.s = SimpleNamespace(
            sqlite3=sqlite3, DB_PATH=self.path, CHANNEL_ID='TECH',
            datetime=datetime, timezone=timezone, timedelta=timedelta,
            random=random.Random(17),
            _chat_id_per_canale=lambda channel: {'tech': 'TECH', 'casa': 'CASA'}[channel],
            _data_sqlite=lambda value: datetime.fromisoformat(value) if value else None,
            risolvi_asin_da_link=asin,
            prodotto_inviato_ultime_24h=self.recent,
        )
        self.s.asin_in_programmati = lambda dest: repost.asin_in_programmati(self.s, dest)

    def recent(self, product, destination):
        with sqlite3.connect(self.path) as db:
            dates = db.execute('SELECT pubblicata_il FROM recap_offerte WHERE asin=? AND telegram_chat_id=?',
                               (product, destination)).fetchall()
        return any(datetime.fromisoformat(d) >= datetime.now(timezone.utc) - timedelta(hours=24)
                   for d, in dates if d)

    def add(self, product, channel='TECH', days=2, origin='manuale', name='Nome', photo='Foto'):
        date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO recap_offerte VALUES (NULL,?,?,?,?,?,?,?,?)',
                       (product, 'https://www.amazon.it/dp/' + product, date, name, photo, 'tech', channel, origin))

    def queue(self, product, channel='TECH', state='attesa'):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO programmazioni VALUES (?,?,?)',
                       ('https://www.amazon.it/dp/' + product, state, channel))

    def products(self, channel):
        return [asin(p['link']) for p in repost.candidati_repost(self.s, channel, 5)]

    def test_histories_and_pending_queues_are_scoped_by_destination(self):
        self.add('TECH_ONLY')
        self.add('CASA_ONLY', 'CASA')
        self.add('BOTH')
        self.add('BOTH', 'CASA')
        self.queue('BOTH', 'CASA')
        self.assertCountEqual(self.products('tech'), ['TECH_ONLY', 'BOTH'])
        self.assertEqual(self.products('casa'), ['CASA_ONLY'])

    def test_date_duplicates_collections_and_queued_exclusions(self):
        self.add('VALID')
        self.add('VALID', days=3)
        self.add('OLD', days=8)
        self.add('RECENT', days=0.2)
        self.add('FUTURE', days=-1)
        self.add('COLLECTION', origin='raccolta')
        self.add('QUEUED')
        self.queue('QUEUED')
        self.assertEqual(self.products('tech'), ['VALID'])

    def test_recent_post_in_other_channel_does_not_exclude_product(self):
        self.add('SHARED', days=2)
        self.add('SHARED', channel='CASA', days=0.1)
        self.assertEqual(self.products('tech'), ['SHARED'])
        self.assertEqual(self.products('casa'), [])

    def test_complete_metadata_gets_priority_and_empty_history_is_empty(self):
        self.assertEqual(self.products('casa'), [])
        self.add('INCOMPLETE', name=None, photo=None)
        self.add('COMPLETE')
        self.assertEqual(self.products('tech'), ['COMPLETE', 'INCOMPLETE'])


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_repost_uses_current_price_and_historical_metadata_only(self):
        s = SimpleNamespace(
            leggi_offerta_con_sei_tentativi=AsyncMock(return_value={'prezzo': '10', 'vecchio_prezzo': '20'}),
            offerta_attuale_rilevata=lambda data: True)
        data, error = await repost.leggi_offerta_repost(s, 'link', {
            'nome': 'Storico', 'foto_file_id': 'foto', 'categoria': 'casa', 'prezzo': '99'})
        self.assertIsNone(error)
        self.assertEqual(data['prezzo'], '10')
        self.assertEqual(data['nome'], 'Storico')
        self.assertEqual(data['_foto_storica_repost'], 'foto')
        s.leggi_offerta_con_sei_tentativi.assert_awaited_once_with('link', richiedi_immagine=False, callback=None)

    async def test_no_current_discount_rejects_repost(self):
        s = SimpleNamespace(leggi_offerta_con_sei_tentativi=AsyncMock(return_value={'prezzo': '10'}),
                            offerta_attuale_rilevata=lambda data: False)
        data, error = await repost.leggi_offerta_repost(s, 'link', {'nome': 'Storico', 'foto_file_id': 'foto'})
        self.assertIsNone(data)
        self.assertIn('sconto', error)

    async def test_lot_persists_original_destination_and_is_not_saved_twice(self):
        draft = {'tipo': 'repost', 'canale': 'casa', 'minuti': 30, 'pronti': [{}],
                 'scartati': [], 'duplicati': 0}
        context = SimpleNamespace(user_data={'multiplo': draft, 'canale_attivo': 'tech'})
        message = SimpleNamespace(reply_text=AsyncMock())
        s = SimpleNamespace(MULTIPLO_LOCK=asyncio.Lock(),
                            filtra_duplicati_recenti_multiplo=Mock(),
                            piano_multiplo=Mock(return_value=[(1, datetime.now(timezone.utc))]),
                            _chat_id_per_canale=lambda channel: channel.upper(), ROMA_TZ=timezone.utc)
        self.assertTrue(await invio_multiplo.avvia_lotto_multiplo(s, message, context, draft))
        self.assertFalse(await invio_multiplo.avvia_lotto_multiplo(s, message, context, draft))
        s.piano_multiplo.assert_called_once_with(draft['pronti'], 30, 'CASA', salva=True, origine='repost')

    async def test_single_rejects_invalid_link_without_reading_amazon(self):
        update = SimpleNamespace(message=SimpleNamespace(text='invalid', reply_text=AsyncMock()))
        s = SimpleNamespace(controlla_autorizzazione=AsyncMock(return_value=True),
                            link_amazon_valido=lambda link: False, LINK=7,
                            leggi_offerta_con_sei_tentativi=AsyncMock())
        result = await invio_singolo.ricevi_link(s, update, SimpleNamespace(user_data={}))
        self.assertEqual(result, 7)
        s.leggi_offerta_con_sei_tentativi.assert_not_awaited()

    async def test_unauthorized_entry_does_not_clear_user_state(self):
        context = SimpleNamespace(user_data={'preserve': True})
        s = SimpleNamespace(controlla_autorizzazione=AsyncMock(return_value=False),
                            ConversationHandler=SimpleNamespace(END=-1))
        for function in (invio_singolo.nuova_da_comando, invio_multiplo.rapido_da_comando, repost.repost_da_pulsante):
            self.assertEqual(await function(s, object(), context), -1)
            self.assertEqual(context.user_data, {'preserve': True})

    async def test_registered_callback_delegates_to_module_with_live_services(self):
        path = Path(__file__).resolve().parents[1] / 'manual_bot.py'
        tree = ast.parse(path.read_text())
        callbacks = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and (ast.get_docstring(n) or '').startswith('Callback compatibile;')]
        self.assertEqual(len(callbacks), 34)
        coordinator = ModuleType('test_coordinator')
        coordinator.__dict__.update(invio_singolo=invio_singolo, invio_multiplo=invio_multiplo, repost=repost)
        coordinator._servizi_invii = coordinator
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        module = ast.fix_missing_locations(ast.Module(body=[future] + callbacks, type_ignores=[]))
        exec(compile(module, str(path), 'exec'), coordinator.__dict__)
        coordinator.controlla_autorizzazione = AsyncMock(return_value=False)
        coordinator.ConversationHandler = SimpleNamespace(END=-1)
        result = await coordinator.nuova_da_comando(object(), object())
        self.assertEqual(result, -1)
        coordinator.controlla_autorizzazione.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
