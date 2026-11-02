import ast
import asyncio
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit, urlencode

import affiliazione
import canali
import importa_messaggio
import invio_multiplo
import menu_canali
from pulsanti import InlineKeyboardButton, InlineKeyboardMarkup


def entity(text, label, url=None):
    start = text.index(label)
    return NS(type='text_link' if url else 'url', url=url,
              offset=len(text[:start].encode('utf-16-le')) // 2,
              length=len(label.encode('utf-16-le')) // 2)


class ExtractionTests(unittest.TestCase):
    def test_semicolons_newlines_punctuation_and_unrelated_urls(self):
        msg = NS(text='Offerta https://amzn.eu/Uno;https://link.amazon/Due\n(https://www.amazon.it/dp/B012345678). https://example.org/x; https://amzn.eu/Uno')
        links, ignored = importa_messaggio.estrai_link(msg)
        self.assertEqual(links, ['https://amzn.eu/Uno', 'https://link.amazon/Due', 'https://www.amazon.it/dp/B012345678'])
        self.assertEqual(ignored, 1)

    def test_hidden_link_after_emoji_and_caption_and_available_buttons(self):
        text = '🔥😀 Offerta clicca qui'
        caption = '☕ Apri il prodotto'
        msg = NS(text=text, entities=[entity(text, 'clicca qui', 'https://amzn.eu/Uno')],
                 caption=caption, caption_entities=[entity(caption, 'Apri il prodotto', 'https://link.amazon/Due')],
                 reply_markup=NS(inline_keyboard=[[NS(url='https://amzn.eu/Uno'), NS(url='https://amazon.it/dp/B012345678'), NS(url=None)]]))
        self.assertEqual(importa_messaggio.estrai_link(msg), (['https://amzn.eu/Uno', 'https://link.amazon/Due', 'https://amazon.it/dp/B012345678'], 0))

    def test_visible_url_entity_does_not_duplicate_regex_result(self):
        text = '🔥 Guarda https://amzn.eu/Uno'
        self.assertEqual(importa_messaggio.estrai_link(NS(text=text, entities=[entity(text, 'https://amzn.eu/Uno')])), (['https://amzn.eu/Uno'], 0))


class ImportFlowTests(unittest.IsolatedAsyncioTestCase):
    def services(self, tag='mio-21'):
        return NS(controlla_autorizzazione=AsyncMock(return_value=True), tag_canale=lambda key:tag,
                  RAPIDO=1, re=re, urlencode=urlencode, prepara_lotto_multiplo=AsyncMock(), ConversationHandler=NS(END=-1))

    async def test_every_channel_prepares_one_batch_from_caption_with_global_affiliation(self):
        for key in ('tech', 'casa', 'sport'):
            s = self.services()
            draft = dict(canale=key, importa_messaggio=True, pronti=[], scartati=[], elaborazione=False)
            tasks = []
            def schedule(coro, **kwargs):
                task = asyncio.create_task(coro); tasks.append(task); return task
            ctx = NS(user_data={'multiplo':draft}, application=NS(create_task=schedule))
            msg = NS(text=None, caption='Offerta https://amzn.eu/Uno; https://link.amazon/Due', reply_text=AsyncMock())
            self.assertEqual(await invio_multiplo.ricevi_rapido(s, NS(message=msg), ctx), 1)
            await asyncio.gather(*tasks)
            self.assertEqual(s.prepara_lotto_multiplo.call_args.args[-1], ['https://amzn.eu/Uno', 'https://link.amazon/Due'])
            self.assertEqual(draft['canale'], key)
            self.assertTrue(draft['importa_messaggio'])
            url = invio_multiplo.link_affiliato_multiplo(s, 'https://amazon.it/dp/B012345678?tag=altro-21', 'B012345678', key)
            self.assertEqual(parse_qs(urlsplit(url).query), {'tag':['mio-21']})

    async def test_missing_tag_or_over_limit_does_not_start_reader(self):
        for tag, text in [('', 'https://amzn.eu/Uno'), ('mio-21', ';'.join('https://amzn.eu/'+str(i) for i in range(51))), ('mio-21', 'nessun collegamento')]:
            s = self.services(tag)
            ctx = NS(user_data={'multiplo':dict(canale='tech', importa_messaggio=True, pronti=[], elaborazione=False)})
            msg = NS(text=text, reply_text=AsyncMock())
            await invio_multiplo.ricevi_rapido(s, NS(message=msg), ctx)
            s.prepara_lotto_multiplo.assert_not_awaited()
            self.assertFalse(ctx.user_data['multiplo']['elaborazione'])

    def test_menu_places_separate_import_button_below_send(self):
        s = NS(InlineKeyboardButton=InlineKeyboardButton, InlineKeyboardMarkup=InlineKeyboardMarkup)
        for key in ('tech','casa','sport'):
            rows = menu_canali.menu_canale(s, canali.Canale(key, key, key)).inline_keyboard
            self.assertEqual(rows[0][0].callback_data, 'rapido')
            self.assertEqual(rows[1][0].callback_data, 'importa_messaggio')


class GlobalTagTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'db.sqlite')

    def test_persistent_global_setting_overrides_environment_and_old_channel_settings(self):
        env = {'AMAZON_PARTNER_TAG':'ambiente-21'}
        self.assertEqual(affiliazione.leggi(self.path, env), 'ambiente-21')
        affiliazione.salva(self.path, 'mio-21')
        self.assertEqual(affiliazione.leggi(self.path, env), 'mio-21')
        source = ast.parse((Path(__file__).parents[1]/'manual_bot.py').read_text())
        node = next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='tag_canale')
        ns = dict(affiliazione=affiliazione, DB_PATH=self.path, os=NS(environ=env))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])), 'tag','exec'),ns)
        for key in ('tech','casa','nuovo',None):
            self.assertEqual(ns['tag_canale'](key), 'mio-21')
        for invalid in ('', 'https://amazon.it/?tag=mio-21', 'a b'):
            with self.assertRaises(ValueError): affiliazione.salva(self.path, invalid)
        self.assertEqual(affiliazione.leggi(self.path, {}), 'mio-21')

    def test_replaces_all_other_tags_and_preserves_offer_parameters(self):
        result=affiliazione.applica('https://www.amazon.it/dp/B012345678?tag=altro-21&TAG=altro2-21&m=venditore&aod=1', 'mio-21')
        self.assertEqual(parse_qs(urlsplit(result).query), {'tag':['mio-21'],'m':['venditore'],'aod':['1']})
        with self.assertRaises(ValueError): affiliazione.applica(result, '')

    async def test_global_tag_edit_requires_access_to_all_channels(self):
        s=NS(DB_PATH=self.path, controlla_autorizzazione=AsyncMock(return_value=True), ConversationHandler=NS(END=-1),
             CANALI={'tech':canali.Canale('tech','Tech','TECH'), 'casa':canali.Canale('casa','Casa','CASA',('99',))},
             InlineKeyboardButton=InlineKeyboardButton, InlineKeyboardMarkup=InlineKeyboardMarkup)
        msg=NS(text='abusivo-21', reply_text=AsyncMock())
        update=NS(message=msg,effective_message=msg,effective_user=NS(id=42),callback_query=NS(data='v2_tag',answer=AsyncMock()))
        ctx=NS(user_data={})
        await menu_canali.gestisci(s,update,ctx)
        self.assertNotIn('v2_input',ctx.user_data)
        ctx.user_data['v2_input']=('globale','tag')
        await menu_canali.ricevi_impostazione(s,update,ctx)
        self.assertEqual(affiliazione.leggi(self.path,{}), '')
