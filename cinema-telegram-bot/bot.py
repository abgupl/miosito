"""Bot richieste e app, avvio: python bot.py (Python 3.10+)."""
import logging
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from config import Config
from menus import Screen, home
from storage import Store, PLATFORMS, STATUSES, validate_app

LOG = logging.getLogger(__name__)
PAGE = 6
REPORT_REASONS = {"link": "Link di download non funzionante", "missing": "App non disponibile", "start": "L’app non si avvia", "other": "Altro problema"}
APP_FIELDS = ['name','platforms','url','code','notes','photo']
APP_LABELS = {'name':'Nome app','platforms':'Piattaforme compatibili','url':'Link di download','code':'Codice Downloader','notes':'Note e istruzioni','photo':'Foto o logo'}


def is_member(member):
    return member.status in {"creator", "administrator", "member"} or (member.status == "restricted" and member.is_member)


class CinemaBot:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self._screens = {}

    async def discard(self, message):
        if message is None:
            return
        try:
            await message.delete()
        except TelegramError:
            # Telegram può rifiutare la cancellazione dei messaggi più vecchi.
            pass

    async def show(self, update, screen):
        """Mantiene soltanto la schermata attiva e acquisisce gli input senza lasciarli in chat."""
        chat_id = getattr(update.effective_chat, 'id', update.effective_user.id)
        previous = self._screens.get(chat_id, [])
        query = update.callback_query
        origin = getattr(query, 'message', None) if query else None
        current = []
        if query and not screen.photo and not getattr(origin, 'photo', None):
            try:
                await query.edit_message_text(screen.text, reply_markup=screen.markup(), disable_web_page_preview=True)
                current = [origin] if origin is not None else []
            except BadRequest as error:
                if "message is not modified" in str(error).lower():
                    current = [origin] if origin is not None else []
                else:
                    query = None
        else:
            query = None
        if query is None:
            if screen.photo:
                caption = screen.text if len(screen.text) <= 1024 else None
                markup = screen.markup() if caption else None
                if screen.photo == 'assets/stream_house.jpeg':
                    with (Path(__file__).parent / screen.photo).open('rb') as asset:
                        current.append(await update.effective_message.reply_photo(asset, caption=caption, reply_markup=markup))
                else:
                    current.append(await update.effective_message.reply_photo(screen.photo, caption=caption, reply_markup=markup))
            if not screen.photo or len(screen.text) > 1024:
                current.append(await update.effective_message.reply_text(screen.text, reply_markup=screen.markup(), disable_web_page_preview=True))
        # Pubblica prima la nuova schermata, poi rimuove le precedenti.
        keep = {getattr(m, 'message_id', None) for m in current if m is not None}
        removed = set()
        for message in previous + ([origin] if origin is not None else []):
            mid = getattr(message, 'message_id', None)
            if message is not None and mid not in keep and mid not in removed:
                await self.discard(message)
                removed.add(mid)
        self._screens[chat_id] = current
        if not update.callback_query:
            await self.discard(update.effective_message)

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
        if not update.callback_query and not (update.effective_message.text or "").startswith("/"):
            await self.input(update, context, admin)
            return
        # Ogni salto di menu annulla l'attesa di input, conservando la bozza per Indietro.
        context.user_data.pop("input", None)
        if route.startswith(("admin", "all:", "manage:", "status:", "appsadmin", "editapp:", "deleteapp:", "removeapp:", "addapp", "wizard:", "stats", "reports:", "reportview:", "reportresolve:")) and not admin:
            await self.show(update, Screen("Questa funzione è riservata all’amministratore.", []))
            return
        try:
            # Ricava l’etichetta prima di modificare il messaggio contenente il pulsante.
            if route == 'reportsend':
                context.user_data['report_user'] = update.effective_user
            label = self.click_label(update.callback_query, route) if update.callback_query else None
            screen = self.route(route, context, user, admin)
            if update.callback_query:
                key = self.click_key(route, label)
                self.store.record_click(update.effective_user, key, self.analytics_label(route,key,label), getattr(update.callback_query, 'id', None))
                if route.startswith('stats'):
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
            return Screen("Amministrazione", [[("📥 Gestisci richieste", "all:0")], [("📲 Gestisci app", "appsadmin:0")], [("🛠 Segnalazioni app", "reports:0")], [("📊 Statistiche", "stats")]])
        if route.startswith('stats'):
            return self.stats_screen(route)
        if route.startswith('reportapps:'):
            page = max(0, int(route.split(':')[1]))
            apps = db.apps()
            page = min(page, max(0,(len(apps)-1)//PAGE))
            buttons = [[(a['name'], f"reportapp:{a['id']}:{page}")] for a in apps[page*PAGE:(page+1)*PAGE]]
            buttons += self.pagination('reportapps', page, len(apps))
            buttons.append([("Altra app / App non in elenco", f"reportapp:0:{page}")])
            return Screen('Quale app presenta il problema?', buttons)
        if route.startswith('reportapp:'):
            parts = route.split(':')
            _, aid, page = parts[:3]
            source = parts[3] if len(parts)>3 else None
            app = db.app(int(aid)) if int(aid) else {'name':'Altra app / App non in elenco'}
            if app is None or (source is not None and source not in app.get('platforms', [])):
                raise ValueError()
            state['report'] = {'app':app['name'], 'aid':int(aid), 'page':int(page), 'source':source}
            parent = f'app:{aid}:{source}' if source else 'reportapps:'+page
            return Screen(f"App: {app['name']}\n\nQual è il problema?", [[(label,'reportreason:'+key)] for key,label in REPORT_REASONS.items()], parent)
        if route.startswith('reportreason:'):
            reason = route.split(':')[1]
            if reason not in REPORT_REASONS:
                raise ValueError()
            draft = state['report']
            draft['reason'] = reason
            state['input'] = 'reportnote'
            parent = f"reportapp:{draft['aid']}:{draft['page']}"+((':'+draft['source']) if draft.get('source') else '')
            return Screen('Descrivi il problema (massimo 500 caratteri). Se hai scelto «Altra app», indica anche il nome.\nPuoi anche saltare questo passaggio.', [[('Salta','reportskip')]], parent)
        if route in {'reportskip','reportconfirm'}:
            draft = state['report']
            if route == 'reportskip':
                draft['note'] = ''
            return Screen(f"Confermi la segnalazione?\n\nApp: {draft['app']}\nProblema: {REPORT_REASONS[draft['reason']]}\nNote: {draft.get('note') or 'Nessuna'}", [[('✅ Invia segnalazione','reportsend')]], 'reportreason:'+draft['reason'])
        if route == 'reportsend':
            draft = state.pop('report')
            rid = db.report(state.pop('report_user'), draft['app'], REPORT_REASONS[draft['reason']], draft.get('note',''))
            return Screen(f'✅ Segnalazione #{rid} inviata al gestore.', [])
        if route.startswith('reports:'):
            page = max(0,int(route.split(':')[1]))
            reports = db.reports()
            page = min(page,max(0,(len(reports)-1)//PAGE))
            buttons = [[(f"#{r['id']} · {r['app_name'][:35]} · {'Aperta' if r['status']=='open' else 'Risolta'}",f"reportview:{r['id']}:{page}")] for r in reports[page*PAGE:(page+1)*PAGE]]
            buttons += self.pagination('reports',page,len(reports))
            return Screen('Segnalazioni app\n'+('Seleziona una segnalazione.' if reports else 'Nessuna segnalazione.'),buttons,'admin')
        if route.startswith(('reportview:','reportresolve:')):
            action,rid,page = route.split(':')
            if action == 'reportresolve':
                db.resolve_report(int(rid))
            report = db.db.execute('SELECT * FROM app_reports WHERE id=?',(int(rid),)).fetchone()
            if report is None:
                raise ValueError()
            identity = self.identity(dict(id=report['user_id'],name=report['name'],username=report['username']))
            text = f"Segnalazione #{rid}\nDa: {identity}\nApp: {report['app_name']}\nProblema: {report['reason']}\nNote: {report['note'] or 'Nessuna'}\nStato: {'Aperta' if report['status']=='open' else 'Risolta'}\nData: {self.local_time(report['created'])}"
            buttons = [[('✅ Segna risolta',f'reportresolve:{rid}:{page}')]] if report['status']=='open' else []
            return Screen(text,buttons,'reports:'+page)
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
            return Screen(self.app_text(app), ([[ ("⬇️ Scarica", f"download:{aid}:{platform}")] ] if app["url"] else [])+ [[("🛠 Segnala un problema", f"reportapp:{aid}:0:{platform}")]], "platform:"+platform, app.get("photo", ""))
        if route.startswith('download:'):
            _, aid, platform = route.split(':')
            app = db.app(int(aid))
            if app is None or platform not in app['platforms'] or not app['url']:
                raise ValueError()
            return Screen(f"Download di {app['name']}\nApri il collegamento:", [[('⬇️ Apri download','url:'+app['url'])]],f'app:{aid}:{platform}')
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
            app = db.app(aid) if aid is not None else dict(name="",url="",platforms=[],code="",notes="")
            if app is None:
                raise ValueError()
            app = {k:v for k,v in app.items() if k != "id"}
            app.setdefault('photo','')
            state['appdraft'] = {'id':aid,'page':page,'values':app,'step':'name'}
            return self.app_wizard('wizard:step:name',context)
        if route.startswith('wizard:'):
            return self.app_wizard(route,context)
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

    def app_wizard(self, route, context):
        state = context.user_data
        draft = state['appdraft']
        values = draft['values']
        parts = route.split(':')
        action = parts[1]
        field = parts[2] if len(parts)>2 else draft['step']
        if action == 'platform':
            if draft['step'] != 'platforms' or field not in PLATFORMS:
                raise ValueError()
            selected = values['platforms']
            if field in selected:
                selected.remove(field)
            else:
                selected.append(field)
            field = 'platforms'
        elif action == 'clear':
            if field not in {'url','code','notes','photo'} or field != draft['step']:
                raise ValueError()
            values[field] = ''
        elif action == 'next':
            if field not in APP_FIELDS or draft['step'] != field:
                raise ValueError()
            try:
                self.validate_field(field,values[field])
            except ValueError as error:
                return self.app_wizard_screen(draft,state,field,str(error))
            pos = APP_FIELDS.index(field)
            field = APP_FIELDS[pos+1] if pos+1<len(APP_FIELDS) else 'review'
        elif action == 'save':
            if draft['step'] != 'review':
                raise ValueError()
            if draft['id'] is not None and self.store.app(draft['id']) is None:
                raise ValueError('App rimossa')
            self.store.save_app(values,draft['id'])
            page = draft['page']
            state.pop('appdraft')
            state.pop('input',None)
            return Screen('✅ App salvata.',[],f'appsadmin:{page}')
        elif action != 'step':
            raise ValueError()
        return self.app_wizard_screen(draft,state,field)

    @staticmethod
    def validate_field(field,value):
        sample = dict(name='App',platforms=['android'],url='https://example.com',code='',notes='')
        sample[field] = value
        validate_app(sample)

    def app_wizard_screen(self,draft,state,field,error=None):
        if field not in APP_FIELDS+['review']:
            raise ValueError()
        draft['step'] = field
        state.pop('input',None)
        values = draft['values']
        if field == 'review':
            text = 'Riepilogo app\n\n'+'\n\n'.join(APP_LABELS[k]+': '+(', '.join(PLATFORMS[p] for p in values[k]) if k=='platforms' else ('Immagine presente' if values[k] else 'Nessuna') if k=='photo' else values[k] or 'Nessuno') for k in APP_FIELDS)
            return Screen(text,[[('✅ Conferma e salva','wizard:save')]],'wizard:step:photo')
        index = APP_FIELDS.index(field)
        parent = 'wizard:step:'+APP_FIELDS[index-1] if index else f"appsadmin:{draft['page']}"
        text = f"Passaggio {index+1}/{len(APP_FIELDS)} · {APP_LABELS[field]}\n\n"
        rows = []
        if error:
            text += error+'\n\n'
        if field == 'platforms':
            text += 'Seleziona una o più piattaforme, poi conferma.'
            rows = [[(('✅ ' if k in values[field] else '⬜️ ')+v,'wizard:platform:'+k)] for k,v in PLATFORMS.items()]
        else:
            state['input'] = 'appfield:'+field
            text += {'name':'Scrivi il nome dell’app (massimo 80 caratteri).',
                     'url':'Invia il link completo, oppure conferma senza link.',
                     'photo':'Invia una foto o un logo come foto Telegram, oppure conferma senza foto.',
                     'code':'Invia il codice numerico Downloader, oppure conferma senza codice.',
                     'notes':'Scrivi le note o le istruzioni (massimo 1500 caratteri), oppure conferma senza note.'}[field]
            text += '\n\nValore: '+(('Immagine presente' if values[field] else 'Nessuna') if field=='photo' else values[field] or ('Nessuno' if field in {'url','code','notes','photo'} else 'Da inserire'))
        # Il valore viene confermato esplicitamente prima di passare allo step seguente.
        if values[field] or field in {'url','code','notes','photo'}:
            rows.append([('✅ Conferma','wizard:next:'+field)])
        if field in {'url','code','notes','photo'} and values[field]:
            rows.append([('Rimuovi valore','wizard:clear:'+field)])
        if draft['id'] is not None and field=='name':
            rows.append([('🗑 Rimuovi app',f"deleteapp:{draft['id']}:{draft['page']}")])
        return Screen(text,rows,parent)

    @staticmethod
    def click_label(query, route):
        message = getattr(query, 'message', None)
        markup = getattr(message, 'reply_markup', None)
        if markup:
            for row in markup.inline_keyboard:
                for button in row:
                    if button.callback_data == route:
                        return button.text[:100]
        labels = {'home':'Indietro', 'new:film':'Richiedi un film', 'new:serie':'Richiedi una serie',
                  'guide':'Guida all’installazione','platforms':'Scarica le app','admin':'Amministrazione',
                  'submit':'Conferma richiesta','stats':'Statistiche','reportsend':'Invia segnalazione'}
        return labels.get(route, route.split(':')[0])

    @staticmethod
    def click_key(route, label):
        if 'Indietro' in label:
            return 'navigation:back'
        if 'Modifica titolo' in label:
            return 'edit_title:'+route.split(':')[-1]
        parts = route.split(':')
        prefix = parts[0]
        if prefix == 'wizard':
            return route
        if 'Precedente' in label or 'Successiva' in label:
            return 'page:'+prefix+(':previous' if 'Precedente' in label else ':next')
        if prefix in {'new','platform','app','download','editapp','reportapp','reportreason'}:
            return ':'.join(parts[:2])
        if prefix == 'status':
            return 'status:'+parts[-1]
        return prefix

    def analytics_label(self, route, key, label):
        if key.startswith('navigation:'):
            return 'Indietro'
        if key.startswith('page:'):
            return ('Pagina precedente' if key.endswith(':previous') else 'Pagina successiva')+' · '+route.split(':')[0]
        canonical = {'request':'Apri richiesta','manage':'Gestisci una richiesta','mine':'Le mie richieste','all':'Gestisci richieste',
                     'statsuser':'Statistiche di un utente','statsbutton':'Statistiche di un pulsante',
                     'reportview':'Apri segnalazione','reportresolve':'Segna segnalazione risolta',
                     'appsadmin':'Gestisci app','reportapps':'Segnala un problema app'}
        if key in canonical:
            return canonical[key]
        if route.startswith(('download:','app:','reportapp:','editapp:')):
            app = self.store.app(int(route.split(':')[1]))
            if app:
                action = {'download':'Scarica','app':'Apri scheda app','reportapp':'Segnala problema app','editapp':'Modifica app'}[route.split(':')[0]]
                return action+' · '+app['name']
        return label

    @staticmethod
    def identity(row):
        return f"{row['name'][:80]}"+(f" (@{row['username']})" if row['username'] else '')+f" · ID {row['id']}"

    @staticmethod
    def local_time(value):
        if not value:
            return '—'
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Rome')).strftime('%d/%m/%Y %H:%M')

    def stats_screen(self, route):
        db = self.store
        if route == 'stats':
            totals = db.stats_summary()
            return Screen(f"📊 Statistiche pulsanti\n\nPressioni totali: {totals['total']}\nUtenti distinti: {totals['users']}\nPulsanti utilizzati: {totals['buttons']}\nPrima pressione: {self.local_time(totals['since'])}\n\nConteggi dall’attivazione della funzione, inclusi gli amministratori. Sono registrate le pressioni accettate dal bot; comandi e messaggi di testo sono esclusi.\nPer i download viene contato «Scarica», non l’apertura del link esterno o il completamento del download.", [[('👥 Per utente','statsusers:0')],[('🔘 Per pulsante','statsbuttons:0')]], 'admin')
        parts = route.split(':')
        prefix = parts[0]
        if prefix in {'statsusers','statsbuttons'}:
            page = max(0,int(parts[1]))
            rows = db.stats_users() if prefix == 'statsusers' else db.stats_buttons()
            page = min(page,max(0,(len(rows)-1)//PAGE))
            buttons = []
            for row in rows[page*PAGE:(page+1)*PAGE]:
                label = (row['name'][:45] if prefix=='statsusers' else row['label'][:45])+f" · {row['total']} pressioni"
                target = 'statsuser' if prefix=='statsusers' else 'statsbutton'
                buttons.append([(label,f"{target}:{row['id']}:0:{page}")])
            buttons += self.pagination(prefix,page,len(rows))
            return Screen(('Statistiche per utente' if prefix=='statsusers' else 'Statistiche per pulsante')+f" · Pagina {page+1}\n"+('Seleziona una voce.' if rows else 'Nessuna pressione registrata.'),buttons,'stats')
        if prefix not in {'statsuser','statsbutton'}:
            raise ValueError()
        ident,page,origin = (int(x) for x in parts[1:])
        page,origin = max(0,page),max(0,origin)
        if prefix == 'statsuser':
            subject = db.db.execute('SELECT * FROM analytics_users WHERE id=?',(ident,)).fetchone()
            if subject is None:
                raise ValueError()
            rows = db.stats_buttons(ident)
            title = '👤 '+self.identity(subject)
            parent = f'statsusers:{origin}'
        else:
            subject = db.db.execute('SELECT * FROM analytics_buttons WHERE id=?',(ident,)).fetchone()
            if subject is None:
                raise ValueError()
            rows = db.stats_button_users(ident)
            title = '🔘 '+subject['label']
            parent = f'statsbuttons:{origin}'
        page = min(page,max(0,(len(rows)-1)//PAGE))
        lines = [title, f"Pressioni totali: {sum(r['total'] for r in rows)}", f'Pagina {page+1}', '']
        for row in rows[page*PAGE:(page+1)*PAGE]:
            label = row['label'] if prefix=='statsuser' else self.identity(row)
            lines.append(f"{label}: {row['total']}\nUltima pressione: {self.local_time(row['last_at'])}\n")
        buttons = []
        if page:
            buttons.append([('◀️ Precedente',f'{prefix}:{ident}:{page-1}:{origin}')])
        if (page+1)*PAGE < len(rows):
            buttons.append([('Successiva ▶️',f'{prefix}:{ident}:{page+1}:{origin}')])
        return Screen('\n'.join(lines),buttons,parent)

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
        if mode == 'reportnote':
            draft = state['report']
            if len(text) > 500:
                screen = Screen('Descrizione troppo lunga: massimo 500 caratteri.', [], 'reportreason:'+draft['reason'])
            else:
                draft['note'] = text.strip()
                state.pop('input',None)
                screen = self.route('reportconfirm',context,update.effective_user.id,admin)
        elif mode == "title":
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
        elif mode and mode.startswith('appfield:') and admin:
            field = mode.split(':')[1]
            draft = state['appdraft']
            try:
                photos = getattr(update.effective_message,'photo',None)
                if field == 'photo':
                    if not photos:
                        raise ValueError('Invia la foto come immagine Telegram.')
                    value = photos[-1].file_id
                else:
                    value = text.strip()
                self.validate_field(field,value)
                draft['values'][field] = value
                screen = self.app_wizard_screen(draft,state,field)
            except ValueError as error:
                screen = self.app_wizard_screen(draft,state,field,str(error))
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
