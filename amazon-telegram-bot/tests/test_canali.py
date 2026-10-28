import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import canali
import menu_canali
import invio_singolo
import invio_multiplo
from database import ArchivioCanali


class RegistryTests(unittest.TestCase):
    def test_extra_category_and_explicit_permissions(self):
        registry = canali.carica_canali({'TELEGRAM_CHAT_ID': 'TECH', 'BOT_CHANNELS_JSON': json.dumps([
            {'chiave': 'sport', 'nome': 'SPORT', 'chat_id': 'SPORT', 'admin_ids': [42]}])})
        self.assertEqual(canali.chat_per_chiave(registry, 'sport'), 'SPORT')
        self.assertTrue(registry['sport'].accessibile(42))
        self.assertFalse(registry['sport'].accessibile(43))
        with self.assertRaises(KeyError):
            canali.chat_per_chiave(registry, 'missing')

    def test_duplicate_destination_fails_instead_of_merging_histories(self):
        with self.assertRaises(ValueError):
            canali.carica_canali({'TELEGRAM_CHAT_ID': 'SAME', 'TELEGRAM_CHAT_ID_CASA': 'SAME'})

    def test_switch_cancels_unsaved_lot_without_affecting_other_admin(self):
        draft = {'timer_token': object()}
        first = SimpleNamespace(user_data={'canale_attivo': 'tech', 'multiplo': draft})
        second = SimpleNamespace(user_data={'canale_attivo': 'casa'})
        canali.reset_flusso(first)
        self.assertTrue(draft['annullato'])
        self.assertNotIn('timer_token', draft)
        self.assertEqual(first.user_data, {'canale_attivo': 'tech'})
        self.assertEqual(second.user_data, {'canale_attivo': 'casa'})


class ChannelStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'test.db')
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE recap_offerte (id INTEGER PRIMARY KEY, nome TEXT, asin TEXT, telegram_chat_id TEXT);
                CREATE TABLE programmazioni (id INTEGER PRIMARY KEY, nome TEXT, stato TEXT, invio_previsto TEXT, telegram_chat_id TEXT);
                INSERT INTO recap_offerte VALUES (1,'Tech','A','TECH'), (2,'Casa','B','CASA'), (3,'Vecchio','C',NULL);
                INSERT INTO programmazioni VALUES (1,'Tech','attesa','2026-10-30','TECH'),(2,'Casa','attesa','2026-10-30','CASA'),(3,'Vecchio','attesa','2026-10-30',NULL);
            ''')
        self.registry = canali.carica_canali({'TELEGRAM_CHAT_ID': 'TECH', 'TELEGRAM_CHAT_ID_CASA': 'CASA'})
        self.store = ArchivioCanali(self.path)
        self.initialize()

    def initialize(self):
        self.store.inizializza(list(self.registry.values()), {'attiva': True, 'inizio': '08:30', 'fine': '21:30'})

    def test_settings_persist_without_cross_channel_changes_or_reset_on_restart(self):
        self.store.salva('CASA', 'intervallo', 60)
        self.store.salva('CASA', 'repost_giorni', 30)
        self.store.salva('CASA', 'tag', 'casa-21')
        self.initialize()
        self.assertEqual(self.store.impostazioni('CASA')['intervallo'], 60)
        self.assertEqual(self.store.impostazioni('CASA')['tag'], 'casa-21')
        self.assertEqual(self.store.impostazioni('TECH')['intervallo'], 30)
        self.assertEqual(self.store.impostazioni('TECH')['repost_giorni'], 7)
        self.assertEqual(self.store.impostazioni('TECH')['tag'], '')

    def test_scoped_listing_details_and_cancellation(self):
        rows, count, page = self.store.lista('recap_offerte', 'CASA')
        self.assertEqual([r['id'] for r in rows], [2])
        self.assertIsNone(self.store.dettaglio('recap_offerte', 'TECH', 2))
        self.assertFalse(self.store.annulla_programmato('TECH', 2))
        self.assertTrue(self.store.annulla_programmato('CASA', 2))
        self.assertFalse(self.store.annulla_programmato('CASA', 2))
        self.assertEqual(self.store.lista('programmazioni', 'CASA')[1], 0)
        self.assertEqual(self.store.lista('programmazioni', 'TECH')[1], 2)

    def test_legacy_rows_without_destination_are_preserved_under_main_channel(self):
        self.assertEqual(self.store.dettaglio('recap_offerte', 'TECH', 3)['nome'], 'Vecchio')
        self.assertEqual(self.store.dettaglio('programmazioni', 'TECH', 3)['nome'], 'Vecchio')
        self.assertIsNone(self.store.dettaglio('programmazioni', 'CASA', 3))

    def test_table_names_are_not_arbitrary_sql(self):
        with self.assertRaises(ValueError):
            self.store.lista('recap_offerte; DROP TABLE programmazioni', 'CASA')

    def test_added_channels_are_persistent_and_duplicates_are_rejected(self):
        channel = canali.nuovo_canale(self.registry, 'sport', 'SPORT', '-100303')
        self.store.salva_canale(channel)
        self.assertEqual(ArchivioCanali(self.path).canali_salvati(), [('sport', 'SPORT', '-100303', [])])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.salva_canale(channel)


class MenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = canali.carica_canali({'TELEGRAM_CHAT_ID': 'TECH', 'TELEGRAM_CHAT_ID_CASA': 'CASA'})
        self.message = SimpleNamespace(reply_text=AsyncMock())
        self.query = SimpleNamespace(data='v2_home', answer=AsyncMock())
        self.update = SimpleNamespace(callback_query=self.query, effective_message=self.message,
                                      effective_user=SimpleNamespace(id=42))
        self.context = SimpleNamespace(user_data={})
        self.s = SimpleNamespace(CANALI=self.registry,
                                 controlla_autorizzazione=AsyncMock(return_value=True),
                                 ConversationHandler=SimpleNamespace(END=-1),
                                 InlineKeyboardButton=lambda text, callback_data: (text, callback_data),
                                 InlineKeyboardMarkup=lambda rows: rows,
                                 ARCHIVIO=SimpleNamespace(impostazioni=lambda chat: {'intervallo': 30, 'repost_giorni': 7}, salva=Mock()))

    async def test_home_contains_global_settings_and_channel_selection(self):
        await menu_canali.gestisci(self.s, self.update, self.context)
        buttons = self.message.reply_text.call_args.kwargs['reply_markup']
        self.assertEqual(buttons[-2], [('➕ Aggiungi canale', 'v2_add_channel')])
        self.assertEqual(buttons[-1], [('☕ Rubrica', 'v2_rubrica'), ('⚙️ Impostazioni', 'v2_settings')])
        self.assertIn([('💻 TECH', 'v2_select_tech')], buttons)
        self.assertNotIn('canale_attivo', self.context.user_data)

    async def test_selection_is_per_user_and_has_scoped_menu_callbacks(self):
        self.query.data = 'v2_select_casa'
        await menu_canali.gestisci(self.s, self.update, self.context)
        self.assertEqual(self.context.user_data['canale_attivo'], 'casa')
        buttons = self.message.reply_text.call_args.kwargs['reply_markup']
        self.assertIn([('📚 Cronologia', 'v2c:casa:history:0')], buttons)

    async def test_old_channel_settings_button_cannot_modify_current_channel(self):
        self.context.user_data['canale_attivo'] = 'casa'
        self.query.data = 'v2c:tech:days:90'
        await menu_canali.gestisci(self.s, self.update, self.context)
        self.s.ARCHIVIO.salva.assert_not_called()

    async def test_pending_setting_cannot_follow_user_to_another_channel(self):
        self.context.user_data = {'canale_attivo': 'casa', 'v2_input': ('tech', 'intervallo')}
        self.update.message = SimpleNamespace(text='60')
        await menu_canali.ricevi_impostazione(self.s, self.update, self.context)
        self.s.ARCHIVIO.salva.assert_not_called()

    async def test_invalid_setting_is_rejected_without_writing(self):
        self.context.user_data = {'canale_attivo': 'casa', 'v2_input': ('casa', 'fascia')}
        self.update.message = SimpleNamespace(text='23:00-08:00', reply_text=AsyncMock())
        result = await menu_canali.ricevi_impostazione(self.s, self.update, self.context)
        self.assertEqual(result, menu_canali.INPUT)
        self.s.ARCHIVIO.salva.assert_not_called()

    async def test_single_captures_destination_before_input(self):
        self.context.user_data = {'canale_attivo': 'casa'}
        self.update.message = self.message
        self.s.richiedi_canale = AsyncMock(return_value=True)
        self.s.canale_corrente = lambda ctx: canali.selezionato(ctx, self.registry)
        self.s.reset_flusso = canali.reset_flusso
        self.s.LINK = 7
        await invio_singolo.nuova_da_comando(self.s, self.update, self.context)
        self.assertEqual(self.context.user_data['telegram_chat_id'], 'CASA')
        self.assertEqual(self.context.user_data['canale_attivo'], 'casa')

    async def test_single_confirm_queues_to_captured_destination_once(self):
        self.query.data = 'pubblica'
        self.query.message = self.message
        self.message.message_id = 88
        self.context.user_data = {'canale_attivo': 'casa', 'telegram_chat_id': 'CASA',
                                  'nome': 'Prodotto', 'messaggio': 'Post', 'link': 'Link', 'prezzo': '10', 'anteprima_id': 88}
        self.s.canale_corrente = lambda ctx: canali.selezionato(ctx, self.registry)
        self.s.datetime, self.s.ROMA_TZ = datetime, timezone.utc
        self.s.CONFERMA = 9
        self.s.salva_programmazione = Mock(return_value=(12, datetime.now(timezone.utc)))
        self.s.salva_foto_programmazione = Mock()
        self.s.reset_flusso = canali.reset_flusso
        self.s.menu_dopo_pubblicazione = lambda: []
        await invio_singolo.conferma(self.s, self.update, self.context)
        await invio_singolo.conferma(self.s, self.update, self.context)
        self.assertEqual(self.s.salva_programmazione.call_count, 1)
        self.assertEqual(self.s.salva_programmazione.call_args.args[-1], 'CASA')

    async def test_repost_interval_is_per_channel_instead_of_per_admin(self):
        store = SimpleNamespace(impostazioni=Mock(return_value={'intervallo': 60}), salva=Mock())
        s = SimpleNamespace(ARCHIVIO=store, _chat_id_per_canale=lambda key: key.upper())
        self.assertEqual(invio_multiplo.intervallo_multiplo(s, 42, 60, 'casa'), 60)
        store.salva.assert_called_once_with('CASA', 'intervallo', 60)

    async def test_lists_request_typed_number_for_all_channels_and_both_archives(self):
        self.registry['sport'] = canali.Canale('sport', 'SPORT', 'SPORT')
        self.s._data_archivio = lambda value: 'oggi'
        self.s.ARCHIVIO.lista = Mock(return_value=([{'id': 123, 'nome': 'Prodotto', 'stato': 'attesa'}], 1, 0))
        for key in ('tech', 'casa', 'sport'):
            for kind in ('history', 'queue'):
                self.context.user_data = {'canale_attivo': key}
                self.query.data = f'v2c:{key}:{kind}:0'
                result = await menu_canali.gestisci(self.s, self.update, self.context)
                self.assertEqual(result, menu_canali.INPUT)
                self.assertEqual(self.context.user_data['v2_input'], (key, 'apri_' + kind))
                call = self.message.reply_text.call_args
                self.assertIn('Quale # vuoi aprire?', call.args[0])
                self.assertFalse(any('view:' in data for row in call.kwargs['reply_markup'] for _, data in row))

    async def test_number_from_other_channel_is_rejected_and_waits_for_retry(self):
        self.context.user_data = {'canale_attivo': 'casa', 'v2_input': ('casa', 'apri_history')}
        self.update.message = SimpleNamespace(text='#123', reply_text=AsyncMock())
        self.s.ARCHIVIO.dettaglio = Mock(return_value=None)
        result = await menu_canali.ricevi_impostazione(self.s, self.update, self.context)
        self.assertEqual(result, menu_canali.INPUT)
        self.s.ARCHIVIO.dettaglio.assert_called_once_with('recap_offerte', 'CASA', 123)


if __name__ == '__main__':
    unittest.main()
