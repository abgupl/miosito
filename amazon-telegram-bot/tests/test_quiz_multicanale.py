import asyncio
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from canali import Canale
import quiz_multicanale


class QuizTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'quiz.db')
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE quiz_uscite(giorno TEXT PRIMARY KEY,stato TEXT,message_id INTEGER,pubblicato_il TEXT,errore TEXT);
                CREATE TABLE quiz_giorni(giorno TEXT PRIMARY KEY,contenuto TEXT);
                INSERT INTO quiz_uscite VALUES('2026-10-27','inviato',7,'2026-10-27T14:00:00+00:00',NULL);
                INSERT INTO quiz_giorni VALUES('2026-10-28','{}');
            ''')
        self.s = SimpleNamespace(sqlite3=sqlite3, DB_PATH=self.path, CHANNEL_ID='TECH',
            datetime=datetime, ROMA_TZ=timezone.utc, QUIZ_LOCK=asyncio.Lock(), ADMIN_ID=None,
            CANALI={'tech': Canale('tech', 'TECH', 'TECH'), 'casa': Canale('casa', 'CASA', 'CASA')},
            configurazione_quiz=lambda: {'attivo': True, 'ora': '09:00', 'esaurimento': ''},
            invia_quiz=AsyncMock(return_value=SimpleNamespace(message_id=31)), imposta_quiz=Mock())
        self.app = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        self.now = datetime(2026,10,28,15,tzinfo=timezone.utc)
        quiz_multicanale.inizializza(self.s)

    def test_migration_preserves_legacy_delivery_once(self):
        quiz_multicanale.inizializza(self.s)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT giorno,canale,message_id FROM quiz_uscite_canali').fetchall(), [('2026-10-27','TECH',7)])
            self.assertEqual(db.execute('SELECT message_id FROM quiz_uscite').fetchall(), [(7,)])

    async def test_all_channels_and_future_channel_receive_one_copy(self):
        await quiz_multicanale.pubblica(self.s,self.app,self.now)
        await quiz_multicanale.pubblica(self.s,self.app,self.now)
        self.assertEqual(self.s.invia_quiz.await_count,2)
        self.s.CANALI['sport']=Canale('sport','SPORT','SPORT')
        await quiz_multicanale.pubblica(self.s,self.app,self.now)
        self.assertEqual(self.s.invia_quiz.await_count,3)
        self.assertEqual({call.args[1] for call in self.s.invia_quiz.call_args_list},{'TECH','CASA','SPORT'})

    async def test_uncertain_delivery_does_not_repeat_or_block_other_channel(self):
        self.s.invia_quiz.side_effect=[RuntimeError('esito incerto'),SimpleNamespace(message_id=32)]
        await quiz_multicanale.pubblica(self.s,self.app,self.now)
        await quiz_multicanale.pubblica(self.s,self.app,self.now)
        self.assertEqual(self.s.invia_quiz.await_count,2)
        with sqlite3.connect(self.path) as db:
            states=dict(db.execute("SELECT canale,stato FROM quiz_uscite_canali WHERE giorno='2026-10-28'"))
        self.assertEqual(states,{'TECH':'da_verificare','CASA':'inviato'})


if __name__=='__main__':
    unittest.main()
