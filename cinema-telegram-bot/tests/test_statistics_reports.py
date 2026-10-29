import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from bot import CinemaBot
from config import Config
from storage import Store
from test_bot import context, update


class StatisticsReports(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = Store(':memory:')
        self.bot = CinemaBot(Config('test',-100123,'',frozenset({1}),Path('unused')),self.db)

    def tearDown(self):
        self.db.db.close()

    async def click(self, route, ctx, user=2, callback_id=None):
        u = update(route,user=user)
        u.effective_user = NS(id=user,username='utente'+str(user),full_name='Nome '+str(user))
        u.callback_query.id = callback_id
        await self.bot.handle(u,ctx)
        return u

    async def test_counts_identification_and_no_text_tracking(self):
        ctx=context()
        await self.click('guide',ctx,callback_id='a')
        await self.click('guide',ctx,callback_id='b')
        await self.click('guide',ctx,callback_id='b')
        await self.click('platforms',ctx,callback_id='c')
        await self.bot.handle(update(text='Ciao',user=2),ctx)
        summary=self.db.stats_summary()
        self.assertEqual(summary['total'],3)
        self.assertEqual(summary['users'],1)
        user=self.db.stats_users()[0]
        self.assertEqual(user['username'],'utente2')
        self.assertEqual(user['id'],2)
        self.assertEqual(self.db.stats_buttons(2)[0]['total'],2)

    async def test_membership_and_admin_access_are_enforced(self):
        ctx=context('left')
        await self.click('guide',ctx)
        self.assertEqual(self.db.stats_summary()['total'],0)
        ctx=context()
        for route in ['stats','statsusers:0','statsbuttons:0','statsuser:1:0:0','statsbutton:1:0:0','reports:0','reportview:1:0','reportresolve:1:0','wizard:save','addapp:0']:
            u=await self.click(route,ctx)
            self.assertIn('riservata',u.callback_query.edit_message_text.call_args.args[0])
        self.assertEqual(self.db.stats_summary()['total'],0)

    async def test_add_app_step_confirmations_validation_and_save(self):
        ctx=context()
        await self.click('addapp:0',ctx,user=1)
        await self.bot.handle(update(text='App prova'),ctx)
        self.assertEqual(len(self.db.apps()),10)
        self.assertEqual(ctx.user_data['appdraft']['step'],'name')
        await self.click('wizard:next:name',ctx,user=1)
        self.assertEqual(ctx.user_data['appdraft']['step'],'platforms')
        await self.click('wizard:next:platforms',ctx,user=1)
        self.assertEqual(ctx.user_data['appdraft']['step'],'platforms')
        await self.click('wizard:platform:android',ctx,user=1)
        await self.click('wizard:platform:fire',ctx,user=1)
        await self.click('wizard:next:platforms',ctx,user=1)
        await self.bot.handle(update(text='non-un-link'),ctx)
        self.assertEqual(ctx.user_data['appdraft']['values']['url'],'')
        await self.bot.handle(update(text='https://example.com/app'),ctx)
        self.assertEqual(ctx.user_data['appdraft']['step'],'url')
        await self.click('wizard:next:url',ctx,user=1)
        await self.bot.handle(update(text='abc'),ctx)
        self.assertEqual(ctx.user_data['appdraft']['values']['code'],'')
        await self.bot.handle(update(text='12345'),ctx)
        await self.click('wizard:next:code',ctx,user=1)
        await self.click('wizard:next:notes',ctx,user=1)
        await self.click('wizard:next:photo',ctx,user=1)
        self.assertEqual(ctx.user_data['appdraft']['step'],'review')
        self.assertEqual(len(self.db.apps()),10)
        await self.click('wizard:save',ctx,user=1)
        self.assertEqual(len(self.db.apps()),11)
        app=self.db.apps()[-1]
        self.assertEqual(app['name'],'App prova')
        self.assertEqual(app['platforms'],['android','fire'])
        self.assertEqual(app['code'],'12345')

    async def test_app_wizard_back_and_cancel_preserve_existing_app(self):
        ctx=context()
        await self.click('editapp:1:0',ctx,user=1)
        await self.bot.handle(update(text='Bozza'),ctx)
        await self.click('wizard:next:name',ctx,user=1)
        await self.click('wizard:step:name',ctx,user=1)
        self.assertEqual(ctx.user_data['appdraft']['values']['name'],'Bozza')
        await self.click('appsadmin:0',ctx,user=1)
        await self.bot.handle(update(text='Fuori dal flusso'),ctx)
        self.assertEqual(self.db.app(1)['name'],'Sky Glass')

    async def test_download_is_counted_and_link_stays_correct(self):
        ctx=context()
        await self.click('app:1:android',ctx,callback_id='app')
        u=await self.click('download:1:android',ctx,callback_id='download')
        markup=u.callback_query.edit_message_text.call_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[0][0].url,self.db.app(1)['url'])
        rows=self.db.stats_buttons()
        self.assertTrue(any(r['key']=='download:1' and 'Sky Glass' in r['label'] for r in rows))
        self.assertEqual(self.db.stats_summary()['total'],2)

    async def test_report_submit_and_admin_resolve(self):
        ctx=context()
        for route in ['reportapps:0','reportapp:1:0','reportreason:link']:
            await self.click(route,ctx)
        await self.bot.handle(update(text='Il collegamento non si apre',user=2),ctx)
        await self.click('reportsend',ctx)
        report=self.db.reports()[0]
        self.assertEqual(report['user_id'],2)
        self.assertEqual(report['username'],'utente2')
        self.assertEqual(report['app_name'],'Sky Glass')
        self.assertEqual(report['note'],'Il collegamento non si apre')
        self.assertEqual(report['status'],'open')
        await self.click(f"reportresolve:{report['id']}:0",context(),user=1)
        self.assertEqual(self.db.reports()[0]['status'],'resolved')

    async def test_report_back_cancels_input_and_unknown_app_supported(self):
        ctx=context()
        for route in ['reportapp:0:0','reportreason:missing','home']:
            await self.click(route,ctx)
        await self.bot.handle(update(text='Messaggio fuori dal flusso',user=2),ctx)
        self.assertEqual(len(self.db.reports()),0)
        for route in ['reportapp:0:0','reportreason:missing','reportskip','reportsend']:
            await self.click(route,ctx)
        self.assertEqual(len(self.db.reports()),1)

    async def test_stats_drilldown_pagination_back(self):
        for n in range(9):
            self.db.record_click(NS(id=n+10,username=None,full_name=f'Persona {n}'),'guide','Guida',str(n))
        ctx=context()
        for route,parent in [('stats','admin'),('statsusers:1','stats'),('statsbuttons:0','stats'),('statsuser:10:0:1','statsusers:1'),('statsbutton:1:1:0','statsbuttons:0')]:
            screen=self.bot.route(route,ctx,1,True)
            self.assertEqual(screen.parent,parent)
            buttons=[b for row in screen.markup().inline_keyboard for b in row]
            self.assertTrue(any(b.text=='⬅️ Indietro' for b in buttons))
            self.assertFalse(any('Menu principale' in b.text for b in buttons))
            self.assertLess(len(screen.text),4096)

    async def test_migration_and_restart_preserve_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.db'
            db=Store(path)
            rid,_=db.request('film','Film già presente','',2)
            actor=NS(id=2,username=None,full_name='Nome')
            db.record_click(actor,'guide','Guida','id1')
            db.report(actor,'App','Link non valido','Note')
            db.db.close()
            db=Store(path)
            self.assertIsNotNone(db.get_request(rid))
            self.assertEqual(db.stats_summary()['total'],1)
            db.record_click(actor,'guide','Guida','id1')
            self.assertEqual(db.stats_summary()['total'],1)
            self.assertEqual(len(db.reports()),1)
            self.assertEqual(len(db.apps()),10)
            db.db.close()


if __name__=='__main__':
    unittest.main()
