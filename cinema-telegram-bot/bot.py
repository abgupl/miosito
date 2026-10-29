"""Bot richieste e app, avvio: python bot.py (Python 3.10+)."""
import json
import logging

from telegram import Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from config import Config
from menus import Screen, home
from storage import Store, PLATFORMS, STATUSES

LOG = logging.getLogger(__name__)
PAGE = 6


def is_member(member):
    return member.status in {"creator", "administrator", "member"} or (member.status == "restricted" and member.is_member)


class CinemaBot:
    def __init__(self, config, store):
        self.config, self.store = config, store

    async def show(self, update, screen):
        """Riutilizza il messaggio-menu; i comandi/testi aprono una nuova schermata."""
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(screen.text, reply_markup=screen.markup(), disable_web_page_preview=True)
                return
            except BadRequest as error:
                if "message is not modified" in str(error).lower():
                    return
                # Un vecchio messaggio non modificabile non deve bloccare la navigazione.
        await update.effective_message.reply_text(screen.text, reply_markup=screen.markup(), disable_web_page_preview=True)

    async def guard(self, update, context):
        if not update.effective_user or not update.effective_chat or update.effective_chat.type != "private":
            return False
        if update.callback_query:
            await update.callback_query.answer()
        try:
            member = await context.bot.get_chat_member(self.config.channel, update.effective_user.id)
            if is_member(member):
                return True
            text = "🔒 Accesso riservato agli iscritti al canale privato. L’ingresso è consentito solo su invito del gestore."
        except TelegramError:
            text = "Non riesco a verificare l’iscrizione. Riprova tra poco; se il problema continua contatta il gestore."
        context.user_data.clear()
        await self.show(update, Screen(text, [[("🔄 Verifica accesso", "home")]], None))
        return False

    async def handle(self, update, context):
        if not await self.guard(update, context):
            return
        user = update.effective_user.id
        admin = user in self.config.admins
        route = update.callback_query.data if update.callback_query else "home"
        if not isinstance(route, str):
            route = "home"
        if not update.callback_query and update.effective_message.text and not update.effective_message.text.startswith("/"):
            await self.input(update, context, admin)
            return
        # Ogni salto di menu annulla l'attesa di input, conservando la bozza per Indietro.
        context.user_data.pop("input", None)
        if route.startswith(("admin", "all:", "manage:", "status:", "appsadmin", "editapp:", "deleteapp:", "removeapp:", "addapp")) and not admin:
            await self.show(update, Screen("Questa funzione è riservata all’amministratore.", []))
            return
        try:
            screen = self.route(route, context, user, admin)
            await self.show(update, screen)
        except (ValueError, KeyError, IndexError, TypeError):
            await self.show(update, Screen("Questa schermata non è più disponibile. Torna al menu principale.", []))

    def route(self, route, context, user, admin):
        cfg, db, state = self.config, self.store, context.user_data
        if route == "home":
            state.clear()
            return home(cfg.channel_url, admin)
        if route == "admin":
            return Screen("Amministrazione", [[("📥 Gestisci richieste", "all:0")], [("📲 Gestisci app", "appsadmin:0")]])
        if route == "guide":
            return Screen(f"📖 Guida all’installazione\n\n1. Apri «Scarica le app» e scegli il dispositivo.\n2. Seleziona un’app e segui le indicazioni della sua scheda.\n3. Dove richiesto, inserisci l’indirizzo server: {cfg.server}\n4. Usa le credenziali personali ricevute dal gestore, se richieste.\n\nFire TV Stick: se l’app prevede Downloader, inserisci il codice riportato nella scheda.\niPhone/iPad: apri il link App Store (la disponibilità può dipendere dalla regione).\nWindows e Mac: usa il file relativo al tuo sistema; il collegamento Mac fornito è per Intel.\n\nPer dubbi sulla configurazione specifica contatta il gestore.", [])
        if route.startswith("new:"):
            kind = route.split(":")[1]
            if kind not in {"film", "serie"}:
                raise ValueError()
            if state.get("draft", {}).get("kind") != kind:
                state["draft"] = {"kind":kind}
            state["input"] = "title"
            return Screen("Scrivi il titolo del film:" if kind == "film" else "Scrivi il titolo della serie:", [])
        if route == "details":
            draft = state["draft"]
            state["input"] = "details"
            prompt = "Scrivi l’anno e le eventuali note, oppure premi «Salta»." if draft['kind'] == "film" else "Scrivi stagione ed eventuali episodi mancanti, oppure premi «Salta»."
            return Screen(f"Titolo: {draft['title']}\n\n{prompt}", [[("Salta", "skip")]], "new:"+draft['kind'])
        if route == "skip":
            state['draft']['details'] = ""
            route = "confirm"
        if route == "confirm":
            draft = state['draft']
            return Screen(f"Confermi la richiesta?\n\nTipo: {draft['kind']}\nTitolo: {draft['title']}\nDettagli: {draft.get('details') or 'Nessuno'}", [[("✅ Conferma", "submit")], [("✏️ Modifica titolo", "new:"+draft['kind'])]], "details")
        if route == "submit":
            draft = state.pop('draft')
            rid, new = db.request(draft['kind'], draft['title'], draft.get('details', ''), user)
            return Screen(("✅ Richiesta registrata." if new else "Questa richiesta esiste già: ora la trovi nelle tue richieste.")+"\nSe il titolo viene segnato disponibile, riceverai un avviso.", [[("📋 Apri richiesta", f"request:{rid}:0")]])
        if route.startswith(("mine:", "all:")):
            prefix, page = route.split(":")
            page = max(0, int(page))
            rows = db.requests(None if prefix == "all" else user)
            page = min(page, max(0, (len(rows)-1)//PAGE))
            target = "manage" if prefix == "all" else "request"
            buttons = [[(f"#{r['id']} · {r['title'][:40]} · {STATUSES[r['status']]}", f"{target}:{r['id']}:{page}")] for r in rows[page*PAGE:(page+1)*PAGE]]
            buttons += self.pagination(prefix, page, len(rows))
            return Screen(("Richieste ricevute" if prefix == "all" else "Le mie richieste")+f" · Pagina {page+1}\n"+("Seleziona un titolo." if rows else "Nessuna richiesta presente."), buttons, "admin" if prefix == "all" else "home")
        if route.startswith(("request:", "manage:", "status:")):
            parts = route.split(":")
            action, rid = parts[0], int(parts[1])
            page = max(0, int(parts[2]))
            management = action in {"manage", "status"}
            row = db.get_request(rid, None if management else user)
            if row is None:
                raise ValueError()
            if action == "status":
                db.status(rid, parts[3])
                row = db.get_request(rid)
            text = f"#{rid} · {row['title']}\nTipo: {row['kind']}\nDettagli: {row['details'] or 'Nessuno'}\nStato: {STATUSES[row['status']]}\nData: {row['created']} UTC"
            buttons = []
            if management:
                text += f"\nPersone in attesa: {row['followers']}"
                buttons = [[(label, f"status:{rid}:{page}:{key}")] for key,label in STATUSES.items()]
            return Screen(text, buttons, f"{'all' if management else 'mine'}:{page}")
        if route == "platforms":
            return Screen("Scegli il dispositivo:", [[(label, "platform:"+key)] for key,label in PLATFORMS.items()])
        if route.startswith("platform:"):
            platform = route.split(":")[1]
            apps = db.apps(platform)
            return Screen(PLATFORMS[platform]+(" · Scegli un’app:" if apps else " · Nessuna app disponibile."), [[(a['name'], f"app:{a['id']}:{platform}")] for a in apps], "platforms")
        if route.startswith("app:"):
            _, aid, platform = route.split(":")
            app = db.app(int(aid))
            if app is None or platform not in app['platforms']:
                raise ValueError()
            return Screen(self.app_text(app), [[("⬇️ Scarica", "url:"+app['url'])]], "platform:"+platform)
        if route.startswith("appsadmin:"):
            page = max(0, int(route.split(":")[1]))
            apps = db.apps()
            page = min(page, max(0, (len(apps)-1)//PAGE))
            buttons = [[(a['name'], f"editapp:{a['id']}:{page}")] for a in apps[page*PAGE:(page+1)*PAGE]]
            buttons += self.pagination("appsadmin", page, len(apps))
            buttons.append([("➕ Aggiungi app", f"addapp:{page}")])
            return Screen(f"Gestisci app · Pagina {page+1}", buttons, "admin")
        if route.startswith(("editapp:", "addapp:")):
            parts = route.split(":")
            aid = int(parts[1]) if parts[0] == "editapp" else None
            page = int(parts[-1])
            app = db.app(aid) if aid is not None else dict(name="Nome app",url="https://example.com/app",platforms=["android"],code="",notes="")
            if app is None:
                raise ValueError()
            app = {k:v for k,v in app.items() if k != "id"}
            state['input'] = "app"
            state['app_edit'] = (aid, page)
            rows = [[("🗑 Rimuovi app", f"deleteapp:{aid}:{page}")]] if aid is not None else []
            return Screen("Invia la scheda completa in formato JSON per salvarla.\nPiattaforme: android, fire, ios, windows, mac.\n\n"+json.dumps(app, ensure_ascii=False, indent=2), rows, f"appsadmin:{page}")
        if route.startswith(("deleteapp:", "removeapp:")):
            action, aid, page = route.split(":")
            aid, page = int(aid), int(page)
            if action == "deleteapp":
                app = db.app(aid)
                if app is None:
                    raise ValueError()
                return Screen(f"Rimuovere {app['name']}?", [[("🗑 Conferma rimozione", f"removeapp:{aid}:{page}")]], f"editapp:{aid}:{page}")
            db.delete_app(aid)
            return Screen("App rimossa.", [], f"appsadmin:{page}")
        raise ValueError("Route sconosciuta")

    @staticmethod
    def pagination(prefix, page, count):
        row = []
        if page > 0:
            row.append(("◀️ Precedente", f"{prefix}:{page-1}"))
        if (page+1)*PAGE < count:
            row.append(("Successiva ▶️", f"{prefix}:{page+1}"))
        return [row] if row else []

    def app_text(self, app):
        return f"{app['name']}\n\n"+(f"Codice Downloader: {app['code']}\n" if app['code'] else "")+f"Indirizzo server: {self.config.server}\n\n{app['notes']}"

    async def input(self, update, context, admin):
        state = context.user_data
        mode = state.get('input')
        text = update.effective_message.text or ""
        if mode == "title":
            if not 1 <= len(text.strip()) <= 150:
                screen = Screen("Inserisci un titolo da 1 a 150 caratteri.", [], "new:"+state['draft']['kind'])
            else:
                state['draft']['title'] = text.strip()
                screen = self.route("details", context, update.effective_user.id, admin)
        elif mode == "details":
            if len(text) > 500:
                screen = Screen("Dettagli troppo lunghi: massimo 500 caratteri.", [], "details")
            else:
                state['draft']['details'] = text.strip()
                state.pop('input', None)
                screen = self.route("confirm", context, update.effective_user.id, admin)
        elif mode == "app" and admin:
            aid, page = state['app_edit']
            try:
                if len(text) > 4000:
                    raise ValueError("Scheda troppo lunga.")
                value = json.loads(text)
                if aid is not None and self.store.app(aid) is None:
                    raise ValueError("App rimossa: torna all'elenco.")
                self.store.save_app(value, aid)
                state.pop('input', None)
                screen = Screen("✅ App salvata.", [], f"appsadmin:{page}")
            except (ValueError, TypeError) as error:
                screen = Screen(f"Scheda non valida: {error}\nCorreggi il JSON e invialo nuovamente.", [], f"appsadmin:{page}")
        else:
            screen = home(self.config.channel_url, admin)
        await self.show(update, screen)

    async def notifications(self, context):
        rows = self.store.db.execute("SELECT n.*, r.title FROM notifications n JOIN requests r ON r.id=n.request_id WHERE r.status='available' LIMIT 30").fetchall()
        for row in rows:
            try:
                member = await context.bot.get_chat_member(self.config.channel, row['user_id'])
                if is_member(member):
                    await context.bot.send_message(row['user_id'], f"🎬 Il titolo che hai richiesto è disponibile: {row['title']}")
                # Chi ha lasciato il canale non riceve avvisi; il suo stato resta consultabile al rientro.
            except Forbidden:
                pass
            except TelegramError:
                continue  # Avviso persistente: nuovo tentativo al prossimo giro.
            with self.store.db:
                self.store.db.execute("DELETE FROM notifications WHERE request_id=? AND user_id=?", (row['request_id'], row['user_id']))

    async def startup(self, application):
        me = await application.bot.get_me()
        member = await application.bot.get_chat_member(self.config.channel, me.id)
        if member.status not in {"administrator", "creator"}:
            raise RuntimeError("Il bot deve essere amministratore del canale prima dell’avvio.")
        # Nessun elenco pubblico di comandi: i menu restano nei messaggi.
        # /start, /menu e /cancel continuano a funzionare se digitati.
        await application.bot.delete_my_commands()
        application.job_queue.run_repeating(self.notifications, interval=30, first=5)

    async def error(self, update, context):
        # Evita URL Telegram e token nei log.
        LOG.error("Errore bot: %s", type(context.error).__name__)
        if isinstance(update, Update) and update.effective_chat and update.effective_chat.type == "private":
            try:
                await self.show(update, Screen("Operazione non completata. Torna indietro e riprova.", []))
            except TelegramError:
                pass

    def application(self):
        app = Application.builder().token(self.config.token).post_init(self.startup).build()
        app.add_handler(CommandHandler(["start", "menu", "cancel"], self.handle))
        app.add_handler(CallbackQueryHandler(self.handle))
        app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, self.handle))
        app.add_error_handler(self.error)
        return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    config = Config.load()
    cinema = CinemaBot(config, Store(config.database))
    cinema.application().run_polling(allowed_updates=["message", "callback_query"])
