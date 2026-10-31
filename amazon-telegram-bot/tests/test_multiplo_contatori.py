import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import invio_multiplo

class CounterTests(unittest.IsolatedAsyncioTestCase):
 async def test_retry_keeps_total_and_remembers_prepared_asins(self):
  draft={'tipo':'multiplo','canale':'tech','pronti':[], 'scartati':[], 'duplicati':0,'elaborazione':True}
  context=SimpleNamespace(user_data={'multiplo':draft})
  message=SimpleNamespace(edit_text=AsyncMock(),reply_photo=AsyncMock(return_value=SimpleNamespace(photo=[SimpleNamespace(file_id='photo')])) ,reply_text=AsyncMock())
  calls={}
  async def read(link,**kwargs):
   calls[link]=calls.get(link,0)+1
   if link in ('b','c') and calls[link]==1:return None
   return {'asin':'A' if link=='b' else link.upper(),'nome':link,'prezzo':'10','immagine':'img'}
  s=SimpleNamespace(asyncio=SimpleNamespace(to_thread=asyncio.to_thread,sleep=AsyncMock()),
   risolvi_asin_da_link=lambda link:link.upper(),prodotto_inviato_ultime_24h=lambda *a:False,
   _chat_id_per_canale=lambda key:key,tastiera_annulla_elaborazione=lambda:None,
   leggi_offerta_con_sei_tentativi=read,tipo_o_fallback=lambda *a:'nuovo',
   link_affiliato_multiplo=lambda link,*args:link,prepara_foto_automatica=AsyncMock(return_value='img'),
   pulisci_prezzo=str,riepilogo_multiplo=AsyncMock())
  async def prepare(*args,**kwargs):return await invio_multiplo.prepara_lotto_multiplo(s,*args,**kwargs)
  s.prepara_lotto_multiplo=prepare
  await prepare(message,context,draft,['a','b','c'])
  self.assertEqual(calls,{'a':1,'b':1,'c':1})
  self.assertEqual(draft['non_letti'],['b','c'])
  s.asyncio.sleep.assert_not_awaited()
  self.assertEqual([p['asin'] for p in draft['pronti']],['A'])
  self.assertTrue(draft['conferma_manuale'])
  pending=list(draft['non_letti'])
  draft['elaborazione']=True
  await prepare(message,context,draft,pending,seconda_passata=True)
  self.assertEqual([p['asin'] for p in draft['pronti']],['A','C'])
  self.assertEqual(draft['duplicati'],1)
  captions=[c.kwargs['caption'] for c in message.reply_photo.call_args_list]
  self.assertTrue(captions[0].startswith('📦 Preparato 1/3'))
  self.assertTrue(captions[1].startswith('📦 Preparato 2/3'))
  self.assertTrue(any('Recupero link non letti: link 1/2' in c.args[0] for c in message.edit_text.call_args_list))
  self.assertEqual(s.riepilogo_multiplo.await_count,2)
  self.assertEqual(draft['non_letti'],[])
  self.assertEqual(calls,{'a':1,'b':2,'c':2})
  self.assertFalse(draft['elaborazione'])
