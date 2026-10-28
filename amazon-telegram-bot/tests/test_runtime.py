"""Costruzione e navigazione con gli handler Telegram reali, senza rete."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(importlib.util.find_spec('telegram') and importlib.util.find_spec('bs4'),
                     'Richiede le dipendenze di requirements.txt')
class RuntimeTests(unittest.TestCase):
    def test_real_handler_navigation_settings_and_publication(self):
        script = r'''
import asyncio,os,tempfile,warnings,sqlite3
from pathlib import Path
from unittest.mock import patch,AsyncMock
from telegram import Update,User,Message,Chat
from telegram.warnings import PTBUserWarning
warnings.simplefilter('ignore', PTBUserWarning)
for key in list(os.environ):
    if key.lower().endswith('_proxy'): os.environ.pop(key)
os.environ.update(TELEGRAM_BOT_TOKEN='123456:test-token', TELEGRAM_CHAT_ID='-100101',
                  TELEGRAM_CHAT_ID_CASA='-100202', ADMIN_TELEGRAM_ID='42', AMAZON_PARTNER_TAG='test-21')
os.environ.pop('BOT_CHANNELS_JSON',None)
os.environ.pop('PORT',None)
with tempfile.TemporaryDirectory() as tmp:
    os.environ['CLUB_DB_PATH']=str(Path(tmp)/'test.db')
    import manual_bot as runtime
    with patch.object(runtime.Application,'run_polling',autospec=True) as polling:
        runtime.main()
        app=polling.call_args.args[0]
    app._initialized=True
    app.bot._initialized=True
    app.bot._bot_user=User(123456,'Test',True,username='test_bot')
    errors=[]
    async def on_error(update,context): errors.append(context.error)
    app.add_error_handler(on_error)
    async def run():
        counter=0
        async def click(data):
            nonlocal counter
            counter+=1
            raw={'update_id':counter,'callback_query':{'id':str(counter),'chat_instance':'test',
                'from':{'id':42,'is_bot':False,'first_name':'Admin'},'data':data,
                'message':{'message_id':900,'date':1700000000,'text':'Menu',
                           'chat':{'id':42,'type':'private'}}}}
            await app.process_update(Update.de_json(raw,app.bot))
        async def text(value):
            nonlocal counter
            counter+=1
            raw={'update_id':counter,'message':{'message_id':counter,'date':1700000000,'text':value,
                'from':{'id':42,'is_bot':False,'first_name':'Admin'},'chat':{'id':42,'type':'private'}}}
            await app.process_update(Update.de_json(raw,app.bot))
        sent=Message(900,runtime.datetime.now(runtime.timezone.utc),Chat(42,'private'))
        sent.set_bot(app.bot)
        with patch.object(type(app.bot),'send_message',new=AsyncMock(return_value=sent)) as send, \
             patch.object(type(app.bot),'answer_callback_query',new=AsyncMock()) as answer, \
             patch.object(type(app.bot),'edit_message_text',new=AsyncMock(return_value=sent)):
            await click('v2_home')
            await click('v2_select_casa')
            await click('v2c:casa:posts')
            await click('nuova')
            assert app.user_data[42]['telegram_chat_id']=='-100202'
            await click('v2_home')
            await click('v2_select_tech')
            await click('v2c:casa:days:90')
            assert answer.call_args.kwargs.get('show_alert')
            assert runtime.ARCHIVIO.impostazioni('-100101')['repost_giorni']==7
            await click('v2c:tech:settings')
            await click('v2c:tech:edit:intervallo')
            await text('45')
            assert runtime.ARCHIVIO.impostazioni('-100101')['intervallo']==45
            assert runtime.ARCHIVIO.impostazioni('-100202')['intervallo']==30
            await click('v2_home')
            await click('v2_select_casa')
            await click('rapido')
            assert app.user_data[42]['multiplo']['canale']=='casa'
            await click('multi_timing')
            await click('multi_min_60')
            assert runtime.ARCHIVIO.impostazioni('-100202')['intervallo']==60
            assert runtime.ARCHIVIO.impostazioni('-100101')['intervallo']==45
            await click('repost')
            draft=app.user_data[42]['multiplo']
            assert draft['tipo']=='repost' and draft['canale']=='casa'
            await click('v2_home')
            assert draft['annullato']
            await click('v2_select_casa')
            await click('nuova')
            with patch.object(runtime,'leggi_offerta_con_sei_tentativi',new=AsyncMock(return_value={
                'asin':'B087654321','nome':'Offerta di prova','prezzo':'10','vecchio_prezzo':'20',
                'categoria':'casa','condizione':'Nuovo','disponibile':True})):
                await text('https://www.amazon.it/dp/B087654321')
            await click('dati_ok')
            await click('foto_salta')
            assert not errors,errors
            assert app.user_data[42]['anteprima_id']==900
            await click('programma')
            await click('prog_giorno_1')
            await text('12:00')
            assert runtime.ARCHIVIO.lista('programmazioni','-100202')[1]==1
            assert runtime.ARCHIVIO.lista('programmazioni','-100101')[1]==0
            scheduled=runtime.ARCHIVIO.lista('programmazioni','-100202')[0][0]['id']
            await click('v2c:casa:queue:0')
            await text('#'+str(scheduled))
            assert 'Offerta di prova' in send.call_args.kwargs['text']
            await click(f'v2c:casa:editqueue:{scheduled}')
            await click('prog_modifica')
            await click('prog_edit_nome')
            await text('Nome aggiornato CASA')
            assert runtime.ARCHIVIO.dettaglio('programmazioni','-100202',scheduled)['nome']=='Nome aggiornato CASA'
            await click('v2_home')
            await click('v2_select_tech')
            await click(f'v2c:tech:editqueue:{scheduled}')
            assert 'prog_id' not in app.user_data[42]
            await click('prog_modifica')
            assert answer.call_args.kwargs.get('show_alert')
            assert not errors,errors
            # Persisted jobs retain the destination independently of the open UI.
            runtime.ARCHIVIO.salva('-100202','attiva','0')
            pid,_=runtime.salva_programmazione('Prodotto','Test','https://www.amazon.it/dp/B012345678?tag=test-21','10',runtime.datetime.now(runtime.ROMA_TZ),'-100202')
            with sqlite3.connect(runtime.DB_PATH) as db:
                row=db.execute('SELECT id,nome,messaggio,link,prezzo,foto_file_id,telegram_chat_id FROM programmazioni WHERE id=?',(pid,)).fetchone()
            send.reset_mock()
            with patch.object(runtime,'attendi_finestra_offerte',new=AsyncMock()), \
                 patch.object(runtime,'aggiorna_pulsanti_offerta',new=AsyncMock()), \
                 patch.object(runtime,'controlla_raccolta_dopo_post_casa',new=AsyncMock()):
                await runtime.invia_offerta_programmata(app.bot,row)
                await runtime.invia_offerta_programmata(app.bot,row)
            send.assert_awaited_once()
            assert send.call_args.kwargs['chat_id']=='-100202'
            assert runtime.ARCHIVIO.lista('recap_offerte','-100202')[1]==1
            assert runtime.ARCHIVIO.lista('recap_offerte','-100101')[1]==0
            runtime.ARCHIVIO.salva('-100101','attiva','0')
            now=runtime.datetime.now(runtime.ROMA_TZ)
            _,casa_time=runtime.salva_programmazione('Nuovo CASA','Test','https://www.amazon.it/dp/B000000001','10',now,'-100202')
            _,tech_time=runtime.salva_programmazione('Nuovo TECH','Test','https://www.amazon.it/dp/B000000002','10',now,'-100101')
            assert (casa_time-now).total_seconds()>=28*60
            assert (tech_time-now).total_seconds()<60
            with sqlite3.connect(runtime.DB_PATH) as db:
                assert db.execute('SELECT stato FROM programmazioni WHERE id=?',(pid,)).fetchone()[0]=='inviata'
    asyncio.run(run())
print('RUNTIME_OK')
'''
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join([str(Path(__file__).resolve().parents[1])] + sys.path)
        result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RUNTIME_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
