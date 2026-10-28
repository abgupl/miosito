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
from unittest.mock import patch,AsyncMock,Mock
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
    runtime.requests.get=Mock(side_effect=runtime.requests.ConnectionError('Rete disabilitata nei test'))
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
             patch.object(type(app.bot),'edit_message_text',new=AsyncMock(return_value=sent)) as edit:
            await click('v2_home')
            await click('v2_settings')
            await click('v2_templates')
            assert 'GRAFICA E TEMPLATE' in send.call_args.kwargs['text']
            await click('settings_menu')
            for row in send.call_args.kwargs['reply_markup'].inline_keyboard:
                for button in row:
                    assert button.text == runtime.InlineKeyboardButton(button.text,callback_data=button.callback_data).text
            await click('v2_status')
            assert 'DISABILITATA' in send.call_args.kwargs['text']
            assert 'Versione:' in send.call_args.kwargs['text']
            await click('v2_status_0')
            assert 'Monitoraggio post globale: DISATTIVATO' in send.call_args.kwargs['text']
            await click('v2_monitor')
            assert 'DISATTIVATO' in send.call_args.kwargs['text']
            await click('v2_monitor_on')
            assert runtime.monitoraggio.attivo(runtime.DB_PATH)
            await click('v2_monitor_off')
            assert not runtime.monitoraggio.attivo(runtime.DB_PATH)
            # With the switch off no monitored products are even loaded.
            with patch.object(runtime,'_offerte_da_verificare') as scan, \
                 patch.object(runtime.asyncio,'sleep',new=AsyncMock(side_effect=asyncio.CancelledError)):
                try:
                    await runtime.controlla_offerte_terminate(app)
                except asyncio.CancelledError:
                    pass
                scan.assert_not_called()
            with patch.object(runtime,'_prodotti_raccolta_da_verificare') as casa_scan, \
                 patch.object(runtime,'_prodotti_raccolta_tech_da_verificare') as tech_scan:
                await runtime.controlla_raccolte_casa_terminate(app)
                await runtime.controlla_raccolte_tech_terminate(app)
                casa_scan.assert_not_called()
                tech_scan.assert_not_called()
            await click('v2_home')
            await click('v2_select_casa')
            await click('v2c:casa:posts')
            await click('nuova')
            assert app.user_data[42]['telegram_chat_id']=='-100202'
            assert any(b.callback_data=='v2c:casa:posts' for row in send.call_args.kwargs['reply_markup'].inline_keyboard for b in row)
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
                await text('https://amzn.eu/LinkDiProva')
                runtime.leggi_offerta_con_sei_tentativi.assert_awaited_once()
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
            # Original automation settings and selective filters are reachable through scoped buttons.
            await click('v2_home')
            await click('v2_select_casa')
            await click('v2c:casa:automatic')
            assert 'disabilitata' in edit.call_args.kwargs['text']
            buttons=edit.call_args.kwargs['reply_markup'].inline_keyboard
            assert all(b.callback_data.startswith(('v2a:casa:', 'v2c:casa:', 'v2_home')) for row in buttons for b in row)
            # The actual back button leaves automation; home clears channel selection.
            await click('v2c:casa:menu')
            assert 'GESTIONE' in send.call_args.kwargs['text']
            await click('v2c:casa:automatic')
            await click('v2_home')
            assert 'canale_attivo' not in app.user_data[42]
            for channel in ('tech','casa'):
                await click('v2_select_'+channel)
                await click('v2c:'+channel+':automatic')
                for action in ('auto_categorie','auto_sconto','auto_qualita','auto_duplicates','selective_menu','filter_menu','priority_menu'):
                    await click('v2a:'+channel+':'+action)
                    markup=edit.call_args.kwargs['reply_markup']
                    assert any(b.callback_data=='v2_home' for row in markup.inline_keyboard for b in row)
                    assert any('⬅' in b.text for row in markup.inline_keyboard for b in row)
                    await click('v2a:'+channel+':auto_menu')
                await click('v2c:'+channel+':menu')
                await click('v2_home')
            await click('v2_select_casa')
            await click('v2c:casa:automatic')
            await click('v2a:casa:auto_intervallo')
            await text('75')
            assert runtime.leggi_config_automatica('casa')['intervallo_minuti']==75
            assert runtime.leggi_config_automatica('tech')['intervallo_minuti']==120
            await click('v2a:casa:auto_disc_30')
            assert runtime.leggi_config_automatica('casa')['sconto_minimo']==30
            await click('v2a:casa:selective_menu')
            await click('v2a:casa:selective_score_7')
            assert runtime.leggi_config_automatica('casa')['punteggio_minimo']==7
            assert runtime.leggi_config_automatica('tech')['punteggio_minimo']==4
            await click('v2a:casa:filter_word_add')
            await text('paroladiprova')
            assert 'paroladiprova' in runtime.FILTRI.leggi('casa')['parole']
            assert 'paroladiprova' not in runtime.FILTRI.leggi('tech')['parole']
            snapshot=runtime.carica_snapshot_filtri(configurazione=runtime.leggi_config_automatica('casa'))
            assert 'paroladiprova' in snapshot['indesiderate']
            assert 'paroladiprova' not in runtime.carica_snapshot_filtri(configurazione=runtime.leggi_config_automatica('tech'))['indesiderate']
            runtime.salva_config_automatica('attiva',1,'tech')
            await click('v2a:casa:filter_word_add')
            await text('secondaparolacasa')
            assert runtime.leggi_config_automatica('tech')['attiva']
            assert not runtime.leggi_config_automatica('casa')['attiva']
            runtime.salva_config_automatica('attiva',0,'tech')
            with sqlite3.connect(runtime.DB_PATH) as db:
                assert not db.execute("SELECT 1 FROM parole_indesiderate_qualita WHERE parola='paroladiprova'").fetchone()
            await click('v2a:casa:auto_toggle')
            assert not runtime.leggi_config_automatica('casa')['attiva']
            assert 'disabilitata' in send.call_args.kwargs['text']
            await click('v2_home')
            await click('v2_select_tech')
            await click('v2a:casa:auto_disc_50')
            assert answer.call_args.kwargs.get('show_alert')
            assert runtime.leggi_config_automatica('casa')['sconto_minimo']==30
            # Legacy horoscope/quiz management, including multiline text import.
            await click('v2_home')
            await click('v2_rubrica')
            assert 'canale_attivo' not in app.user_data[42]
            assert send.call_args.kwargs['reply_markup'].inline_keyboard[-1][0].callback_data=='v2_home'
            await click('v2r:global:oro_menu')
            await click('v2r:global:oro_ora')
            await text('14:00')
            assert runtime.configurazione_oroscopo()['ora']=='14:00'
            await click('v2r:global:quiz_ora')
            await text('14:30')
            assert runtime.configurazione_quiz()['ora']=='14:30'
            day=(runtime.datetime.now(runtime.ROMA_TZ).date()+runtime.timedelta(days=1)).isoformat()
            horoscope='DATA: '+day+'\n'+'\n'.join(symbol+' '+name+': Testo per '+name+'.' for symbol,name in runtime.OROSCOPO_SEGNI)
            await click('v2r:global:oro_carica')
            await text(horoscope)
            await click('v2r:global:oro_verifica')
            await click('v2r:global:oro_salva')
            assert len(runtime.testi_oroscopo(day))==12
            # Add a new category from the UI; verify persistence and reuse of the same modules.
            await click('v2_home')
            await click('v2_add_channel')
            await text('Nome provvisorio')
            await click('v2_add_back')
            await text('SPORT')
            await text('sport')
            await click('v2_add_back')
            await text('sport')
            from types import SimpleNamespace
            with patch.object(type(app.bot),'get_chat',new=AsyncMock(return_value=Chat(-100303,'channel',title='SPORT'))), \
                 patch.object(type(app.bot),'get_chat_member',new=AsyncMock(return_value=SimpleNamespace(status='administrator',can_post_messages=True))):
                await text('-100303')
            await click('v2_add_save')
            assert runtime.CANALI['sport'].chat_id=='-100303'
            assert any(row[0]=='sport' for row in runtime.ArchivioCanali(runtime.DB_PATH).canali_salvati())
            await click('v2_select_sport')
            assert all('rubrica' not in (b.callback_data or '') for row in send.call_args.kwargs['reply_markup'].inline_keyboard for b in row)
            await click('v2c:sport:automatic')
            assert 'SPORT' in edit.call_args.kwargs['text']
            await click('v2a:sport:auto_intervallo')
            await text('90')
            assert runtime.leggi_config_automatica('sport')['intervallo_minuti']==90
            assert runtime.leggi_config_automatica('casa')['intervallo_minuti']==75
            await click('v2a:sport:selective_menu')
            await click('v2a:sport:filter_brandcat_casa')
            await click('v2a:sport:filter_brand_add')
            await text('MarchioSportTest')
            assert 'MarchioSportTest' in runtime.FILTRI.leggi('sport')['marchi']['casa']
            assert 'MarchioSportTest' not in runtime.FILTRI.leggi('casa')['marchi']['casa']
            await click('v2a:sport:priority_cat_casa')
            await click('v2a:sport:priority_add')
            await text('ProdottoSport | MarcaSport | 6')
            assert any(row[2]=='ProdottoSport' and row[4]==6 for row in runtime.FILTRI.leggi('sport')['priorita'])
            assert not any(row[2]=='ProdottoSport' for row in runtime.FILTRI.leggi('tech')['priorita'])
            await click('v2a:sport:filter_reset_yes')
            assert 'paroladiprova' in runtime.FILTRI.leggi('casa')['parole']
            await click('v2_home')
            await click('v2_rubrica')
            await click('v2r:global:oro_canali:sport')
            assert set(runtime.configurazione_oroscopo()['canali'])=={'tech','casa','sport'}
            runtime.imposta_oroscopo('foto','test-file-id')
            runtime.imposta_oroscopo('attivo',True)
            with patch.object(type(app.bot),'send_photo',new=AsyncMock(return_value=sent)) as photo:
                await runtime.pubblica_oroscopo_giornaliero(app,runtime.datetime.fromisoformat(day+'T20:00:00').replace(tzinfo=runtime.ROMA_TZ))
                assert photo.await_count==3
                assert {call.kwargs['chat_id'] for call in photo.call_args_list}=={'-100101','-100202','-100303'}
                await runtime.pubblica_oroscopo_giornaliero(app,runtime.datetime.fromisoformat(day+'T20:00:00').replace(tzinfo=runtime.ROMA_TZ))
                assert photo.await_count==3
            runtime.imposta_oroscopo('attivo',False)
            # The same quiz reaches every channel once, including a newly registered category.
            item={'data':day,'domanda':'Domanda comune di prova?', 'risposte':['A','B','C','D'],
                  'corretta':0,'approfondimento':'Spiegazione condivisa del quiz di prova.'}
            with sqlite3.connect(runtime.DB_PATH) as db:
                db.execute('INSERT INTO quiz_giorni VALUES (?,?)',(day,runtime.json.dumps(item)))
            runtime.imposta_quiz('foto','quiz-file-id')
            runtime.imposta_quiz('attivo',True)
            at=runtime.datetime.fromisoformat(day+'T20:00:00').replace(tzinfo=runtime.ROMA_TZ)
            with patch.object(type(app.bot),'send_photo',new=AsyncMock(return_value=sent)) as photo:
                await runtime.pubblica_quiz(app,at)
                await runtime.pubblica_quiz(app,at)
                assert photo.await_count==3
                assert {call.kwargs['chat_id'] for call in photo.call_args_list}=={'-100101','-100202','-100303'}
            vote=SimpleNamespace(data='quiz_r:'+day+':0',from_user=SimpleNamespace(id=77,username='votante'),
                                 message=SimpleNamespace(message_id=900,chat_id=-100202,chat=Chat(-100202,'channel')),answer=AsyncMock())
            await runtime.risposta_quiz(vote)
            with sqlite3.connect(runtime.DB_PATH) as db:
                assert db.execute('SELECT count(*) FROM quiz_voti WHERE giorno=?',(day,)).fetchone()[0]==1
                assert db.execute('SELECT count(*) FROM quiz_uscite_canali WHERE giorno=? AND stato=?',(day,'inviato')).fetchone()[0]==3
            runtime.imposta_quiz('attivo',False)
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
