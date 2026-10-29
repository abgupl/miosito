import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from telegram.error import NetworkError, Forbidden

from bot import CinemaBot, is_member
from config import Config
from storage import Store, validate_app


def context(member="member"):
    return NS(user_data={}, bot=NS(get_chat_member=AsyncMock(return_value=NS(status=member)), send_message=AsyncMock()))


def update(route=None, text=None, user=1):
    message = NS(text=text, reply_text=AsyncMock())
    query = NS(data=route, answer=AsyncMock(), edit_message_text=AsyncMock()) if route else None
    return NS(effective_chat=NS(type="private"), effective_user=NS(id=user), effective_message=message, callback_query=query)


class Base(unittest.TestCase):
    def setUp(self):
        self.db = Store(":memory:")
        self.bot = CinemaBot(Config("test", -100123, "https://t.me/test", frozenset({1}), Path("unused")), self.db)

    def tearDown(self):
        self.db.db.close()


class StorageTests(Base):
    def test_duplicate_and_ownership(self):
        rid, new = self.db.request("film", " Un  film ", "2020", 1)
        rid2, new2 = self.db.request("film", "un film", "2020", 2)
        self.assertTrue(new)
        self.assertFalse(new2)
        self.assertEqual(rid, rid2)
        self.assertIsNone(self.db.get_request(rid, 3))
        self.assertEqual(self.db.get_request(rid)['followers'], 2)

    def test_status_notifications(self):
        rid, _ = self.db.request("serie", "Serie", "Stagione 1", 1)
        self.db.request("serie", "Serie", "Stagione 1", 2)
        self.assertTrue(self.db.status(rid, "available"))
        self.assertEqual(self.db.db.execute("SELECT count(*) FROM notifications").fetchone()[0], 2)
        self.assertFalse(self.db.status(rid, "available"))
        self.db.status(rid, "working")
        self.assertEqual(self.db.db.execute("SELECT count(*) FROM notifications").fetchone()[0], 0)

    def test_app_validation_and_persistence(self):
        with self.assertRaises(ValueError):
            validate_app(dict(name="App", url="javascript:alert(1)", platforms=["ios"]))
        with self.assertRaises(ValueError):
            validate_app(dict(name="App", url="https://example.com", platforms=["unknown"]))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"test.sqlite3"
            first = Store(path)
            self.assertEqual(len(first.apps()), 9)
            first.delete_app(1)
            rid, _ = first.request("film", "Test", "", 9)
            first.status(rid, "available")
            first.db.close()
            second = Store(path)
            self.assertEqual(len(second.apps()), 8)
            self.assertEqual(second.get_request(rid,9)['status'], "available")
            self.assertEqual(second.db.execute("SELECT count(*) FROM notifications").fetchone()[0], 1)
            second.db.close()


class NavigationTests(Base):
    def check_screen(self, route, ctx, parent):
        screen = self.bot.route(route, ctx, 1, True)
        self.assertEqual(screen.parent, parent, route)
        buttons = [b for row in screen.markup().inline_keyboard for b in row]
        self.assertTrue(any(b.text == "⬅️ Indietro" and b.callback_data == parent for b in buttons), route)
        self.assertFalse(any('Menu principale' in b.text for b in buttons), route)
        self.assertTrue(all(len(row)==1 for row in screen.markup().inline_keyboard), route)
        # Verifica che il genitore sia una destinazione funzionante.
        self.bot.route(parent, ctx, 1, True)
        return screen

    def test_all_submenus_and_back_destinations(self):
        ctx = context()
        rid, _ = self.db.request("film", "Test", "2020", 1)
        for route, parent in [
            ("admin", "home"), ("guide", "home"), ("platforms", "home"),
            ("mine:0", "home"), ("all:0", "admin"),
            (f"request:{rid}:0", "mine:0"), (f"manage:{rid}:0", "all:0"),
            (f"status:{rid}:0:working", "all:0"), ("appsadmin:0", "admin"),
            ("editapp:1:0", "appsadmin:0"), ("addapp:0", "appsadmin:0"),
            ("deleteapp:1:0", "editapp:1:0"), ("removeapp:1:0", "appsadmin:0"),
            ("stats", "admin"), ("statsusers:0", "stats"), ("statsbuttons:0", "stats"),
            ("reportapps:0", "home"), ("reports:0", "admin"),
        ]:
            self.check_screen(route, ctx, parent)
        for platform in ["android", "fire", "ios", "windows", "mac"]:
            self.check_screen("platform:"+platform, ctx, "platforms")
            app = self.db.apps(platform)[0]
            self.check_screen(f"app:{app['id']}:{platform}", ctx, "platform:"+platform)

    def test_wizard_back_and_pagination(self):
        for kind in ["film", "serie"]:
            ctx = context()
            self.bot.route("new:"+kind, ctx, 1, True)
            ctx.user_data['draft']['title'] = "Titolo"
            self.check_screen("details", ctx, "new:"+kind)
            ctx.user_data['draft']['details'] = "2026"
            self.check_screen("confirm", ctx, "details")
            self.assertEqual(ctx.user_data['draft']['title'], "Titolo")
            screen = self.bot.route("submit", ctx, 1, True)
            self.assertEqual(screen.parent, "home")
            self.assertNotIn('draft', ctx.user_data)
        for i in range(15):
            self.db.request("film", f"Film {i}", "", 1)
        for page in range(3):
            self.check_screen(f"mine:{page}", context(), "home")
        self.assertTrue(self.bot.pagination("mine", 1, 17))


class AccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = Store(":memory:")
        self.bot = CinemaBot(Config("test", -100123, "https://t.me/test", frozenset({1}), Path("unused")), self.db)

    def tearDown(self):
        self.db.db.close()

    async def test_member_and_later_leave_blocks_old_button(self):
        ctx = context()
        first = update("new:film")
        await self.bot.handle(first, ctx)
        self.assertEqual(ctx.user_data['input'], "title")
        ctx.bot.get_chat_member.return_value = NS(status="left")
        old = update("submit")
        await self.bot.handle(old, ctx)
        self.assertEqual(ctx.user_data, {})
        self.assertEqual(len(self.db.requests()), 0)
        self.assertIn("Accesso riservato", old.callback_query.edit_message_text.call_args.args[0])
        self.assertEqual(ctx.bot.get_chat_member.await_count, 2)

    async def test_errors_fail_closed_and_no_admin_bypass(self):
        ctx = context()
        ctx.bot.get_chat_member.side_effect = NetworkError("temporary")
        u = update("appsadmin:0")
        await self.bot.handle(u, ctx)
        self.assertIn("Non riesco a verificare", u.callback_query.edit_message_text.call_args.args[0])
        ctx = context()
        u = update("removeapp:1:0", user=2)
        await self.bot.handle(u, ctx)
        self.assertIsNotNone(self.db.app(1))
        self.assertIn("riservata", u.callback_query.edit_message_text.call_args.args[0])

    async def test_user_cannot_read_another_request(self):
        rid,_ = self.db.request("film", "Privato", "", 1)
        u = update(f"request:{rid}:0", user=2)
        await self.bot.handle(u, context())
        self.assertNotIn("Privato", u.callback_query.edit_message_text.call_args.args[0])

    async def test_full_request_flow_and_back_cancels_input(self):
        ctx = context()
        for u in [update("new:serie"), update(text="Serie esempio"), update("details"), update(text="Stagione 2"), update("submit")]:
            await self.bot.handle(u, ctx)
        self.assertEqual(len(self.db.requests(1)), 1)
        self.assertEqual(self.db.requests(1)[0]['details'], "Stagione 2")
        await self.bot.handle(update("new:film"), ctx)
        await self.bot.handle(update("home"), ctx)
        await self.bot.handle(update(text="Non deve creare richieste"), ctx)
        self.assertEqual(len(self.db.requests()), 1)

    async def test_app_edit_wizard_has_back_and_saves_after_confirmation(self):
        ctx = context()
        await self.bot.handle(update("editapp:1:0"), ctx)
        invalid = update(text="x"*81)
        await self.bot.handle(invalid, ctx)
        markup = invalid.effective_message.reply_text.call_args.kwargs['reply_markup']
        self.assertTrue(any(b.text == "⬅️ Indietro" for row in markup.inline_keyboard for b in row))
        await self.bot.handle(update(text='Nuovo nome'), ctx)
        self.assertEqual(self.db.app(1)['name'], 'Sky Glass')
        for field in ['name','platforms','url','code','notes']:
            await self.bot.handle(update('wizard:next:'+field),ctx)
        await self.bot.handle(update('wizard:save'),ctx)
        self.assertEqual(self.db.app(1)['name'], "Nuovo nome")

    async def test_notifications_membership_retry_and_blocked_bot(self):
        rid,_ = self.db.request("film", "Avviso", "", 1)
        self.db.status(rid, "available")
        ctx = context()
        ctx.bot.send_message.side_effect = NetworkError("temporary")
        await self.bot.notifications(ctx)
        self.assertEqual(self.db.db.execute("SELECT count(*) FROM notifications").fetchone()[0], 1)
        ctx.bot.send_message.side_effect = None
        await self.bot.notifications(ctx)
        self.assertEqual(self.db.db.execute("SELECT count(*) FROM notifications").fetchone()[0], 0)
        self.db.status(rid, "working")
        self.db.status(rid, "available")
        ctx.bot.send_message.reset_mock()
        ctx.bot.get_chat_member.return_value = NS(status="left")
        await self.bot.notifications(ctx)
        ctx.bot.send_message.assert_not_awaited()

    async def test_private_only_and_restricted_membership(self):
        u = update("home")
        u.effective_chat.type = "supergroup"
        ctx = context()
        await self.bot.handle(u, ctx)
        ctx.bot.get_chat_member.assert_not_awaited()
        self.assertTrue(is_member(NS(status="restricted", is_member=True)))
        self.assertFalse(is_member(NS(status="restricted", is_member=False)))


if __name__ == "__main__":
    unittest.main()
