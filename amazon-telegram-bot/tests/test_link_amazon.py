import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from link_amazon import link_amazon_valido
import invio_multiplo


class LinkTests(unittest.TestCase):
    def test_supported_direct_and_short_domains(self):
        for domain in ('amazon.it', 'www.amazon.it', 'smile.amazon.it', 'amzn.to',
                       'amzn.eu', 'link.amazon', 'link.amazon.it', 'a.co',
                       'amazon.de', 'www.amazon.com', 'amazon.co.uk'):
            with self.subTest(domain=domain):
                self.assertTrue(link_amazon_valido('https://' + domain + '/prodotto'))
        self.assertTrue(link_amazon_valido(' HTTPS://AMZN.EU/AbCd '))

    def test_unrelated_hosts_and_invalid_schemes_are_rejected(self):
        for link in ('https://example.com/item', 'https://amazon.it.example.com/item',
                     'https://fakeamzn.eu/item', 'ftp://amzn.eu/item',
                     'amzn.eu/item', 'https://[invalid', '', None):
            with self.subTest(link=link):
                self.assertFalse(link_amazon_valido(link))


class MultipleLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_uses_shared_filter_including_short_and_foreign_links(self):
        links = ['https://amzn.eu/AbCd', 'HTTPS://AMZN.TO/AbCd',
                 'https://a.co/AbCd', 'https://www.amazon.de/dp/B012345678']
        validate = Mock(wraps=link_amazon_valido)
        prepare = Mock(return_value=object())
        s = SimpleNamespace(controlla_autorizzazione=AsyncMock(return_value=True),
                            re=re, tag_canale=lambda channel: 'tag-21',
                            link_amazon_valido=validate, RAPIDO=7,
                            prepara_lotto_multiplo=prepare)
        draft = {'canale': 'casa', 'pronti': [], 'scartati': [], 'elaborazione': False}
        context = SimpleNamespace(user_data={'multiplo': draft},
                                  application=SimpleNamespace(create_task=Mock()))
        update = SimpleNamespace(message=SimpleNamespace(
            text='\n'.join(links + ['https://example.com/other']), reply_text=AsyncMock()))
        self.assertEqual(await invio_multiplo.ricevi_rapido(s, update, context), 7)
        self.assertEqual(prepare.call_args.args[-1], links)
        self.assertEqual(validate.call_count, 5)
        self.assertEqual(draft['scartati'], ['1 link non Amazon ignorati'])


if __name__ == '__main__':
    unittest.main()
