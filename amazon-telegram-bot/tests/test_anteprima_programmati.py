import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import unittest
from pulsanti import InlineKeyboardButton,InlineKeyboardMarkup

class PreviewTests(unittest.IsolatedAsyncioTestCase):
 def setup_preview(self,photo='foto',status='attesa',body='testo salvato'):
  source=ast.parse((Path(__file__).parents[1]/'manual_bot.py').read_text())
  node=next(n for n in source.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='invia_scheda_programmato')
  post={'id':177,'telegram_chat_id':'TECH','invio_previsto':'2026-10-31T20:05:00+01:00',
        'stato':status,'messaggio':body,'link':'https://www.amazon.it/dp/B012345678','foto_file_id':photo}
  render=Mock(return_value='<b>Testo formattato</b>')
  ns={'leggi_programmato':lambda pid:post,'data_programmata_locale':lambda value:None,
      'CANALI':{'tech':SimpleNamespace(nome='Tech',chiave='tech',chat_id='TECH')},
      'crea_caption_con_link':render,'InlineKeyboardButton':InlineKeyboardButton,'InlineKeyboardMarkup':InlineKeyboardMarkup,
      'tastiera_offerta_automatica':lambda link:InlineKeyboardMarkup([[InlineKeyboardButton('Apri',url=link)]])}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'preview','exec'),ns)
  return ns['invia_scheda_programmato'],render
 async def test_photo_caption_matches_renderer_and_metadata_is_separate(self):
  function,render=self.setup_preview()
  message=SimpleNamespace(reply_text=AsyncMock(),reply_photo=AsyncMock())
  await function(message,177)
  self.assertIn('#177',message.reply_text.call_args.args[0])
  self.assertEqual(message.reply_photo.call_args.kwargs['caption'],'<b>Testo formattato</b>')
  self.assertEqual(message.reply_photo.call_args.kwargs['photo'],'foto')
  self.assertEqual(message.reply_photo.call_args.kwargs['parse_mode'],'HTML')
 async def test_no_photo_uses_text_and_preserves_html_source(self):
  function,render=self.setup_preview(photo=None,body='__RICERCA_HTML__<b>Originale</b>')
  message=SimpleNamespace(reply_text=AsyncMock(),reply_photo=AsyncMock())
  await function(message,177)
  render.assert_called_once_with('<b>Originale</b>','https://www.amazon.it/dp/B012345678',messaggio_gia_html=True)
  message.reply_photo.assert_not_awaited()
  self.assertEqual(message.reply_text.call_args.args[0],'<b>Testo formattato</b>')
 async def test_uncertain_post_has_no_mutation_buttons(self):
  function,render=self.setup_preview(status='da_verificare')
  message=SimpleNamespace(reply_text=AsyncMock(),reply_photo=AsyncMock())
  await function(message,177)
  callbacks=[b.callback_data for row in message.reply_photo.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
  self.assertNotIn('prog_modifica',callbacks)
  self.assertNotIn('prog_elimina',callbacks)
  self.assertIn('v2c:tech:queue:0',callbacks)
