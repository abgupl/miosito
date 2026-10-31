import ast
from datetime import datetime
from pathlib import Path
import unittest

class OroscopoFotoTests(unittest.TestCase):
 def setUp(self):
  tree=ast.parse((Path(__file__).parents[1]/'manual_bot.py').read_text())
  constants={'OROSCOPO_DIDASCALIA_SOLE','OROSCOPO_DIDASCALIA_LUNA','OROSCOPO_DIDASCALIA'}
  nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in {'foto_oroscopo','crea_didascalia_oroscopo'}) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets))]
  self.s={'datetime':datetime}
  exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'oroscopo','exec'),self.s)
 def test_date_and_approved_captions(self):
  sole=self.s['crea_didascalia_oroscopo']('2026-10-31',1)
  luna=self.s['crea_didascalia_oroscopo']('2026-10-31',2)
  self.assertIn('Sabato 31 ottobre',sole)
  self.assertIn('Sabato 31 ottobre',luna)
  self.assertIn('ritagliati un momento tutto tuo',sole)
  self.assertIn('La tua pausa della sera',luna)
  self.assertNotIn('tramonto',luna)
  self.assertNotIn('{data}',sole+luna)
 def test_distinct_photos_and_legacy_fallback(self):
  photo=self.s['foto_oroscopo']
  self.assertEqual(photo({'foto':'old'},1),'old')
  self.assertEqual(photo({'foto':'old'},2),'old')
  self.assertEqual(photo({'foto':'old','foto_sole':'sun','foto_luna':'moon'},1),'sun')
  self.assertEqual(photo({'foto':'old','foto_sole':'sun','foto_luna':'moon'},2),'moon')
  self.assertFalse(photo({'foto_sole':'sun'},2))
