import ast
import asyncio
import re
import unittest
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import invio_multiplo
import repost

class ReadingReasonsTests(unittest.IsolatedAsyncioTestCase):
 def reader(self,resolve,fetch):
  tree=ast.parse((Path(__file__).parents[1]/'manual_bot.py').read_text())
  node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='leggi_offerta_con_sei_tentativi')
  ns={'asyncio':SimpleNamespace(to_thread=asyncio.to_thread,sleep=AsyncMock()),'re':re,'risolvi_asin_da_link':resolve,'leggi_prodotto_amazon':fetch}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'reader','exec'),ns)
  return ns['leggi_offerta_con_sei_tentativi']
 async def test_actual_captcha_reason_propagates_after_three_attempts(self):
  def page(url,diagnostica):diagnostica['motivo']='Amazon ha mostrato una verifica anti-bot/CAPTCHA'
  read=self.reader(lambda link:'B012345678',page)
  details={}
  self.assertIsNone(await read('link',diagnostica=details))
  self.assertEqual(details['tentativi'],3)
  self.assertEqual(len(details['motivi']),3)
  self.assertIn('CAPTCHA',details['motivi'][-1])
 async def test_unresolved_link_reports_zero_page_attempts(self):
  fetch=Mock()
  read=self.reader(lambda link:None,fetch)
  details={}
  self.assertIsNone(await read('link',diagnostica=details))
  fetch.assert_not_called()
  self.assertEqual(details['tentativi'],0)
  self.assertIn('ASIN non rilevato',details['motivi'][0])
 async def test_no_offer_is_excluded_not_marked_unread(self):
  details={}
  s=SimpleNamespace(leggi_offerta_con_sei_tentativi=AsyncMock(return_value={'nome':'Prodotto','prezzo':'20','vecchio_prezzo':'20'}),
                    offerta_attuale_rilevata=lambda data:False)
  data,error=await repost.leggi_offerta_repost(s,'link',{},diagnostica=details)
  self.assertIsNone(data)
  self.assertEqual(details['esito'],'escluso')
  self.assertIn('listino',error)
  draft={'tipo':'repost','canale':'casa','richiesti':1,'pronti':[],'scartati':[],'duplicati':0}
  context=SimpleNamespace(user_data={'multiplo':draft})
  async def excluded(*args,diagnostica=None):diagnostica['esito']='escluso';return None,error
  service=SimpleNamespace(asyncio=SimpleNamespace(to_thread=asyncio.to_thread),risolvi_asin_da_link=lambda link:'B012345678',
   _chat_id_per_canale=lambda channel:channel,prodotto_inviato_ultime_24h=lambda *args:False,
   leggi_offerta_repost=excluded,riepilogo_multiplo=AsyncMock(),tastiera_annulla_elaborazione=lambda:None)
  await invio_multiplo.prepara_lotto_multiplo(service,SimpleNamespace(edit_text=AsyncMock()),context,draft,[{'link':'link','nome':'Prodotto'}])
  self.assertEqual(draft['non_letti'],[])
  self.assertEqual(len(draft['scartati']),1)
 async def test_confirmed_lot_still_reports_names_count_and_reason(self):
  draft={'canale':'tech','minuti':30,'pronti':[{}],'scartati':[],'duplicati':0,
   'non_letti':[{'link':'https://www.amazon.it/dp/B012345678','nome':'Nome storico'}],
   'motivi_non_letti':{'https://www.amazon.it/dp/B012345678':{'motivo':'Timeout: Amazon non ha risposto entro 10 secondi','tentativi':3}}}
  context=SimpleNamespace(user_data={'multiplo':draft})
  msg=SimpleNamespace(reply_text=AsyncMock())
  s=SimpleNamespace(MULTIPLO_LOCK=asyncio.Lock(),filtra_duplicati_recenti_multiplo=Mock(),
   piano_multiplo=lambda *args,**kwargs:[(1,datetime.now(timezone.utc))],_chat_id_per_canale=lambda key:key,ROMA_TZ=timezone.utc)
  await invio_multiplo.avvia_lotto_multiplo(s,msg,context,draft)
  text=msg.reply_text.call_args.args[0]
  for fragment in ['Articoli non letti: 1','Nome storico','Timeout','Tentativi di lettura pagina: 3']:
   self.assertIn(fragment,text)
  self.assertNotIn('Nessun link scartato',text)
 def test_no_historical_comparison_and_no_unverified_coupon_only_offer(self):
  s=SimpleNamespace(numero_da_prezzo=lambda price:float(price) if price else None)
  self.assertTrue(repost.offerta_attuale_rilevata(s,{'prezzo':'30','vecchio_prezzo':'50','prezzo_storico':'20'}))
  self.assertFalse(repost.offerta_attuale_rilevata(s,{'prezzo':'30','vecchio_prezzo':'30'}))
  self.assertFalse(repost.offerta_attuale_rilevata(s,{'prezzo':'30','coupon':'10%'}))
