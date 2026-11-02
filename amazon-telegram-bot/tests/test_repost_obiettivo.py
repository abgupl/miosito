import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import invio_multiplo

class RepostTargetTests(unittest.IsolatedAsyncioTestCase):
 async def test_retry_at_target_does_not_erase_unchecked_links(self):
  ready=[{'asin':str(i)} for i in range(10)]
  links=['a','b','c','d']
  draft={'tipo':'repost','canale':'tech','richiesti':10,'pronti':ready,'non_letti':list(links),'elaborazione':True}
  context=SimpleNamespace(user_data={'multiplo':draft})
  s=SimpleNamespace(riepilogo_multiplo=AsyncMock(),leggi_offerta_repost=AsyncMock())
  await invio_multiplo.prepara_lotto_multiplo(s,object(),context,draft,links,seconda_passata=True)
  self.assertEqual(draft['non_letti'],links)
  self.assertEqual(len(draft['pronti']),10)
  s.leggi_offerta_repost.assert_not_awaited()
  s.riepilogo_multiplo.assert_awaited_once()
 def test_retry_button_hidden_when_target_reached(self):
  s=SimpleNamespace(InlineKeyboardButton=lambda text,callback_data:(text,callback_data),InlineKeyboardMarkup=lambda rows:rows)
  draft={'tipo':'repost','minuti':30,'richiesti':2,'pronti':[{},{}],'non_letti':['a']}
  rows=invio_multiplo.tastiera_multiplo(s,draft)
  self.assertNotIn('multi_retry',[b[1] for row in rows for b in row])
 async def test_summary_does_not_claim_reserves_were_recovered(self):
  draft={'tipo':'repost','canale':'tech','minuti':30,'richiesti':1,'pronti':[{'nome':'Prodotto','prezzo':'10'}],
         'non_letti':['a','b'],'scartati':[],'duplicati':0,'conferma_manuale':True}
  from datetime import datetime,timezone
  s=SimpleNamespace(filtra_duplicati_recenti_multiplo=Mock(),piano_multiplo=lambda *a:[(None,datetime.now(timezone.utc))],
    _chat_id_per_canale=lambda key:key,ROMA_TZ=timezone.utc,descrizione_pause_programmate=lambda *a:[],tastiera_multiplo=lambda d:None)
  msg=SimpleNamespace(reply_text=AsyncMock())
  await invio_multiplo.riepilogo_multiplo(s,msg,draft)
  text=msg.reply_text.call_args.args[0]
  self.assertIn('Obiettivo raggiunto',text)
  self.assertIn('non sono state recuperate',text)
  self.assertNotIn('Recupero terminato',text)
