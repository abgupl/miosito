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
