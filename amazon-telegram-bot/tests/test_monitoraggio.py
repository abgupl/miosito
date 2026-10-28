import tempfile
import unittest
from pathlib import Path
import monitoraggio

class MonitoraggioTests(unittest.TestCase):
 def test_disabled_by_default_and_persistent(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'bot.db'
   self.assertFalse(monitoraggio.attivo(path))
   monitoraggio.imposta(path,True)
   self.assertTrue(monitoraggio.attivo(str(path)))
   monitoraggio.imposta(path,False)
   self.assertFalse(monitoraggio.attivo(str(path)))
 def test_databases_are_independent(self):
  with tempfile.TemporaryDirectory() as tmp:
   a,b=Path(tmp)/'a.db',Path(tmp)/'b.db'
   monitoraggio.imposta(a,True)
   self.assertFalse(monitoraggio.attivo(b))
