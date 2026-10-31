import unittest
from pulsanti import etichetta, InlineKeyboardButton

class PulsantiTests(unittest.TestCase):
 def test_only_first_letter_is_uppercase(self):
  self.assertEqual(etichetta('⚙️ IMPOSTAZIONI GENERALI'),'⚙️ Impostazioni generali')
  self.assertEqual(etichetta('☀️ Primo Caffè'),'☀️ Primo caffè')
  self.assertEqual(etichetta('💻 TECH'),'💻 Tech')
  self.assertEqual(etichetta('30%'),'30%')
 def test_callback_and_url_are_unchanged(self):
  button=InlineKeyboardButton('APRI AMAZON',url='https://example.com/ABC')
  self.assertEqual(button.url,'https://example.com/ABC')
  button=InlineKeyboardButton.de_json({'text':'TORNA AL MENU','callback_data':'v2c:tech:menu'},None)
  self.assertEqual(button.text,'Torna al menu')
  self.assertEqual(button.callback_data,'v2c:tech:menu')

class MenuBackTests(unittest.TestCase):
 def test_contextual_back_replaces_home_and_keeps_pagination(self):
  from pulsanti import InlineKeyboardMarkup
  markup=InlineKeyboardMarkup([
   [InlineKeyboardButton('⬅️ Precedenti',callback_data='v2_status_0')],
   [InlineKeyboardButton('⬅️ Rubrica',callback_data='v2r:global:rub_menu')],
   [InlineKeyboardButton('🏠 Menu principale',callback_data='v2_home')]])
  buttons=[b for row in markup.inline_keyboard for b in row]
  self.assertEqual([b.callback_data for b in buttons],['v2_status_0','v2r:global:rub_menu'])
  self.assertEqual(buttons[-1].text,'⬅️ Indietro')
 def test_top_level_keeps_a_single_back_to_home(self):
  from pulsanti import InlineKeyboardMarkup
  markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Menu principale',callback_data='v2_home')]])
  self.assertEqual(markup.inline_keyboard[0][0].text,'⬅️ Indietro')
  self.assertEqual(markup.inline_keyboard[0][0].callback_data,'v2_home')
