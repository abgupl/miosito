import asyncio
import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import invio_multiplo
from link_amazon import link_amazon_valido

class UnifiedSendTests(unittest.IsolatedAsyncioTestCase):
 async def test_one_or_many_links_use_same_flow_for_every_channel(self):
  for channel in ('tech','casa','sport'):
   for links in [['https://www.amazon.it/dp/B012345678?tag=test-21'],['https://amzn.eu/primo','https://link.amazon/secondo']]:
    draft={'canale':channel,'pronti':[],'scartati':[],'duplicati':0,'elaborazione':False}
    tasks=[]
    def schedule(coro,**kw):
     task=asyncio.create_task(coro);tasks.append(task);return task
    context=SimpleNamespace(user_data={'multiplo':draft},application=SimpleNamespace(create_task=schedule))
    msg=SimpleNamespace(text='\n'.join(links),reply_text=AsyncMock())
    s=SimpleNamespace(controlla_autorizzazione=AsyncMock(return_value=True),tag_canale=lambda key:'test-21',
      re=re,link_amazon_valido=link_amazon_valido,prepara_lotto_multiplo=AsyncMock(),RAPIDO=1)
    await invio_multiplo.ricevi_rapido(s,SimpleNamespace(message=msg),context)
    await asyncio.gather(*tasks)
    s.prepara_lotto_multiplo.assert_awaited_once_with(msg.reply_text.return_value,context,draft,links)
    self.assertEqual(draft['canale'],channel)
    self.assertTrue(draft['elaborazione'])
 async def test_invalid_input_never_starts_reader(self):
  draft={'canale':'tech','pronti':[],'elaborazione':False}
  context=SimpleNamespace(user_data={'multiplo':draft})
  s=SimpleNamespace(controlla_autorizzazione=AsyncMock(return_value=True),tag_canale=lambda key:'tag',re=re,
    link_amazon_valido=link_amazon_valido,prepara_lotto_multiplo=AsyncMock(),RAPIDO=1)
  msg=SimpleNamespace(text='https://example.com/prodotto',reply_text=AsyncMock())
  self.assertEqual(await invio_multiplo.ricevi_rapido(s,SimpleNamespace(message=msg),context),1)
  s.prepara_lotto_multiplo.assert_not_awaited()
