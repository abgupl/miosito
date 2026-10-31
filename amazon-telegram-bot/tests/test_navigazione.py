"""Verifica dei collegamenti generati dagli adattatori di navigazione."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from interfaccia_legacy import tastiera_scoped, UpdateScoped
try:
 from telegram import InlineKeyboardButton, InlineKeyboardMarkup
except ImportError:
 InlineKeyboardButton = InlineKeyboardMarkup = None

@unittest.skipUnless(InlineKeyboardButton, 'Richiede python-telegram-bot')
class NavigationTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.s=SimpleNamespace(InlineKeyboardButton=InlineKeyboardButton,InlineKeyboardMarkup=InlineKeyboardMarkup)
 def callbacks(self,markup):
  return [b.callback_data for row in markup.inline_keyboard for b in row]
 def test_automatic_return_leaves_automatic_menu_for_every_channel(self):
  for channel in ('tech','casa','sport'):
   markup=InlineKeyboardMarkup([[InlineKeyboardButton('Torna ai canali', callback_data='auto_channels')]])
   values=self.callbacks(tastiera_scoped(self.s,markup,'v2a',channel))
   self.assertIn('v2c:'+channel+':menu',values)
   self.assertNotIn('v2_home',values)
   self.assertNotIn('v2c:'+channel+':automatic',values)
 def test_empty_input_screen_has_scoped_back_and_home(self):
  for namespace,channel,target in [('v2a','tech','v2a:tech:auto_menu'),('v2r','global','v2r:global:rub_menu'),('v2m','casa','v2c:casa:posts')]:
   values=self.callbacks(tastiera_scoped(self.s,None,namespace,channel))
   self.assertIn(target,values)
   self.assertNotIn('v2_home',values)
 def test_manual_actions_and_public_callbacks_remain_compatible(self):
  actions=['dati_ok','foto_salta','prog_giorno_1','quiz_r:2026-10-28:0','oro_segno:1:ariete']
  markup=InlineKeyboardMarkup([[InlineKeyboardButton(x,callback_data=x)] for x in actions])
  values=self.callbacks(tastiera_scoped(self.s,markup,'v2m','casa'))
  self.assertTrue(set(actions)<=set(values))
 def test_existing_home_not_duplicated(self):
  markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Menu principale',callback_data='menu_admin')]])
  values=self.callbacks(tastiera_scoped(self.s,markup,'v2r','global'))
  self.assertEqual(values,['v2_home'])
 async def test_prompt_without_keyboard_receives_navigation(self):
  msg=SimpleNamespace(reply_text=AsyncMock(return_value=None))
  update=SimpleNamespace(effective_message=msg)
  await UpdateScoped(update,self.s,'v2a','casa').effective_message.reply_text('Inserisci un valore')
  self.assertIn('v2a:casa:auto_menu',self.callbacks(msg.reply_text.call_args.kwargs['reply_markup']))
