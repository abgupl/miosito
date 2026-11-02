import asyncio
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import requests
import canali
import importa_messaggio
import invio_multiplo
import redirect_amazon


def response(status, location=None):
    r=MagicMock(status_code=status, headers={'Location':location} if location else {})
    r.__enter__.return_value=r
    return r


class RedirectTests(unittest.TestCase):
    def test_only_supported_shortener_is_collected(self):
        self.assertEqual(importa_messaggio.estrai_link(NS(text='https://ofclub.click/uno; https://ofclub.click.evil/uno')), (['https://ofclub.click/uno'],1))

    def test_amazon_destination_extracts_asin_without_loading_product_page(self):
        with patch('redirect_amazon.requests.get', return_value=response(301,'https://www.amazon.it/Sony/dp/B012345678?tag=altro-21')) as get:
            self.assertEqual(redirect_amazon.risolvi('https://ofclub.click/uno'), ('https://www.amazon.it/dp/B012345678',None))
            get.assert_called_once()
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_non_amazon_destination_is_not_followed(self):
        for destination in ('https://s.click.aliexpress.com/e/abc','http://127.0.0.1/dp/B012345678','https://amazon.it.evil/dp/B012345678'):
            with patch('redirect_amazon.requests.get', return_value=response(302,destination)) as get:
                link,reason=redirect_amazon.risolvi('https://ofclub.click/uno')
                self.assertIsNone(link)
                self.assertIn('Destinazione non Amazon',reason)
                get.assert_called_once()

    def test_relative_redirect_and_amazon_short_link(self):
        with patch('redirect_amazon.requests.get',side_effect=[response(302,'/secondo'),response(302,'https://amzn.eu/abc'),response(302,'https://www.amazon.it/dp/B012345678')]) as get:
            self.assertEqual(redirect_amazon.risolvi('https://ofclub.click/primo')[0], 'https://www.amazon.it/dp/B012345678')
            self.assertEqual(get.call_count,3)

    def test_timeout_http_error_loop_and_missing_redirect_have_explanations(self):
        cases=[([requests.Timeout()], 'Timeout'),([response(404)],'HTTP 404'),
               ([response(302,'/uno')],'Ciclo'),([response(200)],'non fornisce'),([response(302)],'privo')]
        for replies, expected in cases:
            with patch('redirect_amazon.requests.get',side_effect=replies):
                link,reason=redirect_amazon.risolvi('https://ofclub.click/uno')
                self.assertIsNone(link)
                self.assertIn(expected,reason)


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_separate_messages_collect_then_start_only_once_for_every_channel(self):
        for key in ('tech','casa','futuro'):
            draft=dict(canale=key, importa_messaggio=True, raccolta_aperta=True, duplicati=0, scartati=[], elaborazione=False, pronti=[])
            tasks=[]
            def schedule(coro, **kw):
                task=asyncio.create_task(coro);tasks.append(task);return task
            ctx=NS(user_data={'multiplo':draft},application=NS(create_task=schedule))
            s=NS(RAPIDO=1,controlla_autorizzazione=AsyncMock(return_value=True),tag_canale=lambda key:'mio-21',
                 tastiera_multiplo=lambda draft:None,prepara_lotto_multiplo=AsyncMock())
            links=[]
            for i in range(4):
                link=f'https://amzn.eu/{i}';links.append(link)
                msg=NS(text=link,message_id=i,chat_id=42,reply_text=AsyncMock())
                await invio_multiplo.ricevi_rapido(s,NS(message=msg),ctx)
            self.assertEqual(draft['messaggi_ricevuti'],4)
            self.assertEqual(draft['link_raccolti'],links)
            self.assertFalse(draft['elaborazione'])
            s.prepara_lotto_multiplo.assert_not_awaited()
            query=NS(data='multi_elabora',message=msg,answer=AsyncMock())
            await invio_multiplo.gestisci_multiplo(s,NS(callback_query=query),ctx)
            await asyncio.gather(*tasks)
            await invio_multiplo.gestisci_multiplo(s,NS(callback_query=query),ctx)
            s.prepara_lotto_multiplo.assert_awaited_once()
            self.assertEqual(s.prepara_lotto_multiplo.call_args.args[-1],links)
            self.assertFalse(draft['raccolta_aperta'])

    async def test_duplicate_delivery_and_limit_preserve_existing_collection(self):
        links=[f'https://amzn.eu/{i}' for i in range(50)]
        draft=dict(duplicati=0,scartati=[],link_raccolti=links.copy())
        ctx=NS(user_data={'multiplo':draft})
        s=NS(RAPIDO=1,tastiera_multiplo=lambda draft:None)
        msg=NS(message_id=1,chat_id=42,reply_text=AsyncMock())
        await importa_messaggio.raccogli(s,NS(message=msg),ctx,draft,[links[0]],0)
        await importa_messaggio.raccogli(s,NS(message=msg),ctx,draft,[links[0]],0)
        self.assertEqual(draft['messaggi_ricevuti'],1)
        self.assertEqual(draft['duplicati'],1)
        await importa_messaggio.raccogli(s,NS(message=NS(message_id=2,chat_id=42,reply_text=AsyncMock())),ctx,draft,['https://amzn.eu/extra'],0)
        self.assertEqual(draft['link_raccolti'],links)
        self.assertEqual(draft['messaggi_ricevuti'],1)
        canali.reset_flusso(ctx)
        self.assertNotIn('multiplo',ctx.user_data)
        self.assertTrue(draft['annullato'])

    async def test_pipeline_reads_resolved_amazon_and_reports_redirect_failures(self):
        canonical='https://www.amazon.it/dp/B012345678'
        draft=dict(canale='casa',importa_messaggio=True,pronti=[],scartati=[],duplicati=0,elaborazione=True)
        ctx=NS(user_data={'multiplo':draft})
        msg=NS(edit_text=AsyncMock(),reply_text=AsyncMock(),reply_photo=AsyncMock(return_value=NS(photo=[NS(file_id='foto')])) )
        s=NS(asyncio=asyncio,risolvi_asin_da_link=lambda link:'B012345678',prodotto_inviato_ultime_24h=lambda *a:False,
             _chat_id_per_canale=lambda key:key,tastiera_annulla_elaborazione=lambda:None,
             leggi_offerta_con_sei_tentativi=AsyncMock(return_value=dict(asin='B012345678',nome='Prodotto',prezzo='10',immagine='img')),
             tipo_o_fallback=lambda *a:'nuovo',link_affiliato_multiplo=lambda *a:canonical+'?tag=mio-21',
             prepara_foto_automatica=AsyncMock(return_value='foto'),pulisci_prezzo=str,riepilogo_multiplo=AsyncMock())
        links=['https://ofclub.click/amazon','https://ofclub.click/aliexpress','https://ofclub.click/lento']
        with patch('redirect_amazon.risolvi',side_effect=[(canonical,None),(None,'Destinazione non Amazon: s.click.aliexpress.com'),(None,'Timeout durante la risoluzione del link breve')]):
            await invio_multiplo.prepara_lotto_multiplo(s,msg,ctx,draft,links)
        s.leggi_offerta_con_sei_tentativi.assert_awaited_once()
        self.assertEqual(s.leggi_offerta_con_sei_tentativi.call_args.args[0],canonical)
        self.assertEqual(draft['pronti'][0]['link_originale'],links[0])
        self.assertIn('tag=mio-21',draft['pronti'][0]['link'])
        self.assertEqual(draft['non_letti'],[links[2]])
        self.assertIn('aliexpress',draft['scartati'][0])
        self.assertIn('Timeout',draft['motivi_non_letti'][links[2]]['motivo'])
        self.assertEqual(draft['motivi_non_letti'][links[2]]['tentativi'],0)
