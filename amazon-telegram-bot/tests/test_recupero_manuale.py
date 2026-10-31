import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import invio_multiplo

class RetryTests(unittest.IsolatedAsyncioTestCase):
 async def test_manual_retry_only_pending_and_cancels_timer_for_all_channels(self):
  for channel in ['tech','casa','sport']:
   ready={'asin':'A'}
   draft={'canale':channel,'pronti':[ready],'non_letti':['b'],'timer_token':object(),'minuti':30}
   context=SimpleNamespace(user_data={'multiplo':draft})
   tasks=[]
   def schedule(coro,**kwargs):
    task=asyncio.create_task(coro);tasks.append(task);return task
   context.application=SimpleNamespace(create_task=schedule)
   query=SimpleNamespace(data='multi_retry',answer=AsyncMock(),message=SimpleNamespace(reply_text=AsyncMock()))
   s=SimpleNamespace(controlla_autorizzazione=AsyncMock(return_value=True),RAPIDO=1,
     prepara_lotto_multiplo=AsyncMock())
   await invio_multiplo.gestisci_multiplo(s,SimpleNamespace(callback_query=query),context)
   await asyncio.gather(*tasks)
   s.prepara_lotto_multiplo.assert_awaited_once_with(query.message,context,draft,['b'],seconda_passata=True)
   self.assertNotIn('timer_token',draft)
   self.assertTrue(draft['conferma_manuale'])
   self.assertTrue(draft['elaborazione'])
   self.assertEqual(draft['pronti'],[ready])
   self.assertEqual(draft['canale'],channel)
 async def test_timer_cannot_send_during_or_after_manual_recovery(self):
  for busy in [False,True]:
   token=object()
   draft={'timer_token':token,'elaborazione':busy,'conferma_manuale':True}
   context=SimpleNamespace(user_data={'multiplo':draft})
   s=SimpleNamespace(asyncio=SimpleNamespace(sleep=AsyncMock()),avvia_lotto_multiplo=AsyncMock())
   await invio_multiplo.avvio_multiplo_differito(s,object(),context,draft,token)
   s.avvia_lotto_multiplo.assert_not_awaited()
 def test_timer_is_not_armed_when_articles_are_unread(self):
  draft={'non_letti':['link'],'timer_token':object()}
  context=SimpleNamespace(application=SimpleNamespace(create_task=Mock()))
  invio_multiplo.arma_avvio_multiplo(object(),object(),context,draft)
  self.assertNotIn('timer_token',draft)
  context.application.create_task.assert_not_called()
