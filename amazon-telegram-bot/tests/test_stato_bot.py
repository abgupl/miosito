import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from canali import Canale
import stato_bot

class StatoTests(unittest.TestCase):
 def test_channel_queues_permissions_and_pagination(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'test.db'
   with sqlite3.connect(path) as db:
    db.executescript("CREATE TABLE programmazioni(id INTEGER,nome TEXT,invio_previsto TEXT,stato TEXT,telegram_chat_id TEXT); INSERT INTO programmazioni VALUES (1,'Casa','2030-01-01T10:00:00','attesa','CASA'),(2,'Tech','2030-01-01T09:00:00','da_verificare','TECH');")
   channels={'tech':Canale('tech','TECH','TECH'),'casa':Canale('casa','CASA','CASA')}
   channels.update({str(i):Canale('x'+str(i),'X'+str(i),'X'+str(i)) for i in range(4)})
   channels['private']=Canale('private','PRIVATE','PRIVATE',(99,))
   s=SimpleNamespace(DB_PATH=path,CANALI=channels,ROMA_TZ=timezone.utc,_LOG_STARTED=datetime.now(timezone.utc),SORGENTE_RICERCA_ATTIVA=False,
      leggi_config_automatica=lambda key:{'attiva':False},configurazione_quiz=lambda:{'attivo':False,'ora':'17:00'},
      configurazione_oroscopo=lambda:{'attivo':False},orari_oroscopo=lambda cfg:[(1,'08:00')],
      _diagnostic_entries=lambda kind:[],_redact_log_line=lambda line:line)
   text,page,pages=stato_bot.riepilogo(s,42)
   self.assertEqual((page,pages),(0,2))
   self.assertIn('1 da verificare',text)
   self.assertIn('#1 · Casa',text)
   self.assertNotIn('PRIVATE',text)
   self.assertNotIn('X3',text)
   self.assertLess(len(text),4096)
   text,page,pages=stato_bot.riepilogo(s,42,999)
   self.assertEqual(page,1)
   self.assertIn('X3',text)
   with sqlite3.connect(path) as db:
    db.execute('CREATE TABLE quiz_giorni(giorno TEXT)')
   s.configurazione_quiz=lambda:{'attivo':True,'ora':'17:00','foto':''}
   text,_,_=stato_bot.riepilogo(s,42)
   self.assertIn('testi MANCANTI',text)
   self.assertIn('foto MANCANTE',text)
 def test_dates_convert_to_local_timezone(self):
  from zoneinfo import ZoneInfo
  s=SimpleNamespace(ROMA_TZ=ZoneInfo('Europe/Rome'))
  self.assertEqual(stato_bot.data_locale(s,'2026-10-28T10:00:00+00:00'),'28/10 11:00')
