import os
import re
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# =========================================================
# BESTPRICE LEAGUE - V1 PRESEASON / MARKET
# =========================================================

DB_PATH = os.environ.get("CLUB_DB_PATH", "club.db")
ADMIN_ID = os.environ.get("ADMIN_TELEGRAM_ID")
TZ = ZoneInfo("Europe/Rome")
SEASON_CODE = "2026-10"
SEASON_NAME = "OTTOBRE 2026"
SEASON_START = datetime(2026, 10, 1, 0, 0, tzinfo=TZ)
SEASON_END = datetime(2026, 11, 1, 0, 0, tzinfo=TZ)
STARTING_BUDGET = 100
TEAM_SIZE = 5
GOLD_FIRST = 30
GOLD_SECOND = 10
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
TEAM_NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ0-9 _.'-]{3,24}$")

# V1: catalogo provvisorio. Verrà sostituito/agganciato al motore Amazon.
DEFAULT_PRODUCTS = [
    ("iphone17", "iPhone 17", "smartphone", 35),
    ("galaxy_s26", "Samsung Galaxy S26", "smartphone", 30),
    ("pixel11", "Google Pixel 11", "smartphone", 25),
    ("airpods4", "AirPods 4", "audio", 25),
    ("sony_wh", "Sony WH-1000XM6", "audio", 22),
    ("jbl_flip", "JBL Flip", "audio", 15),
    ("firetv4k", "Fire TV Stick 4K", "tv", 15),
    ("firetvplus", "Fire TV Stick 4K Plus", "tv", 20),
    ("echo_show", "Echo Show", "tv", 18),
    ("roborock", "Roborock", "casa", 20),
    ("dreame", "Dreame Robot", "casa", 18),
    ("philips_air", "Philips Air Fryer", "casa", 15),
    ("iniu_pb", "INIU Power Bank", "jolly", 10),
    ("kindle", "Kindle", "jolly", 18),
    ("ring", "Ring Video Doorbell", "jolly", 15),
]
CATEGORY_ORDER = ["smartphone", "audio", "tv", "casa", "jolly"]
CATEGORY_LABEL = {
    "smartphone": "📱 Smartphone",
    "audio": "🎧 Audio",
    "tv": "📺 TV/Streaming",
    "casa": "🏠 Casa",
    "jolly": "⭐ Jolly",
}


def connessione():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def now_dt():
    return datetime.now(TZ)


def ora():
    return now_dt().isoformat(timespec="seconds")


def e_admin(user_id):
    return bool(ADMIN_ID) and str(user_id) == str(ADMIN_ID)


async def verifica_admin(update):
    user = update.effective_user
    if not user or not e_admin(user.id):
        if update.callback_query:
            await update.callback_query.answer("⛔ Non autorizzato.", show_alert=True)
        return False
    return True


def stato_stagione():
    adesso = now_dt()
    if adesso < SEASON_START:
        return "PRESEASON"
    if adesso < SEASON_END:
        return "ACTIVE"
    return "ENDED"


def test_mode_active():
    return league_setting("test_mode", "0") == "1"


def player_state(user_id):
    """L'admin in modalità test vede la League come ACTIVE prima del lancio."""
    if e_admin(user_id) and test_mode_active() and stato_stagione() == "PRESEASON":
        return "ACTIVE"
    return stato_stagione()


def is_test_player(user_id):
    return e_admin(user_id) and test_mode_active() and stato_stagione() == "PRESEASON"


def countdown_text():
    delta = SEASON_START - now_dt()
    if delta.total_seconds() <= 0:
        return "🟢 LA STAGIONE È INIZIATA"
    total_minutes = int(delta.total_seconds() // 60)
    days, rem = divmod(total_minutes, 1440)
    hours, minutes = divmod(rem, 60)
    return f"⏳ {days} giorni • {hours} ore • {minutes} minuti"


def inizializza_database():
    db = connessione()
    cur = db.cursor()

    # Le vecchie tabelle Club non vengono eliminate: restano come backup storico.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_users (
            telegram_id INTEGER PRIMARY KEY,
            telegram_username TEXT,
            nome TEXT,
            league_username TEXT UNIQUE COLLATE NOCASE,
            gold_tokens INTEGER NOT NULL DEFAULT 0,
            data_iscrizione TEXT NOT NULL,
            ultimo_accesso TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_seasons (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            first_gold INTEGER NOT NULL DEFAULT 30,
            second_gold INTEGER NOT NULL DEFAULT 10
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            season_code TEXT NOT NULL,
            team_name TEXT,
            budget_total INTEGER NOT NULL DEFAULT 100,
            score INTEGER NOT NULL DEFAULT 0,
            confirmed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            confirmed_at TEXT,
            UNIQUE(telegram_id, season_code)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_products (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            cost INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_team_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            product_code TEXT NOT NULL,
            category TEXT NOT NULL,
            is_captain INTEGER NOT NULL DEFAULT 0,
            added_at TEXT NOT NULL,
            UNIQUE(team_id, category),
            UNIQUE(team_id, product_code)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_score_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            season_code TEXT NOT NULL,
            telegram_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            product_code TEXT NOT NULL,
            discount REAL,
            base_points INTEGER NOT NULL,
            multiplier INTEGER NOT NULL DEFAULT 1,
            points INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_gold_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            season_code TEXT NOT NULL,
            tokens INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO league_seasons
        (code, name, start_at, end_at, status, first_gold, second_gold)
        VALUES (?, ?, ?, ?, 'scheduled', ?, ?)
    """, (SEASON_CODE, SEASON_NAME, SEASON_START.isoformat(), SEASON_END.isoformat(), GOLD_FIRST, GOLD_SECOND))

    cur.executemany("""
        INSERT OR IGNORE INTO league_products (code, name, category, cost, active)
        VALUES (?, ?, ?, ?, 1)
    """, DEFAULT_PRODUCTS)
    db.commit()
    db.close()


def get_league_user(user_id):
    db = connessione(); cur = db.cursor()
    cur.execute("SELECT * FROM league_users WHERE telegram_id = ?", (user_id,))
    row = cur.fetchone(); db.close(); return row


def registra_o_aggiorna_telegram_user(user):
    existing = get_league_user(user.id)
    if not existing:
        return
    db = connessione(); cur = db.cursor()
    cur.execute("""
        UPDATE league_users SET telegram_username=?, nome=?, ultimo_accesso=?
        WHERE telegram_id=?
    """, (user.username, user.first_name, ora(), user.id))
    db.commit(); db.close()


def crea_league_user(user, league_username):
    if not USERNAME_RE.fullmatch(league_username or ""):
        return False, "Username non valido. Usa 3-20 caratteri: lettere, numeri o _."
    db = connessione(); cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO league_users
            (telegram_id, telegram_username, nome, league_username, gold_tokens, data_iscrizione, ultimo_accesso)
            VALUES (?, ?, ?, ?, 0, ?, ?)
        """, (user.id, user.username, user.first_name, league_username, ora(), ora()))
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        return False, "Questo username è già utilizzato. Scegline un altro."
    db.close()
    return True, None


def get_team(user_id):
    db = connessione(); cur = db.cursor()
    cur.execute("SELECT * FROM league_teams WHERE telegram_id=? AND season_code=?", (user_id, SEASON_CODE))
    row = cur.fetchone(); db.close(); return row


def ensure_team(user_id):
    team = get_team(user_id)
    if team: return team
    db = connessione(); cur = db.cursor()
    cur.execute("""
        INSERT INTO league_teams (telegram_id, season_code, budget_total, score, confirmed, created_at)
        VALUES (?, ?, ?, 0, 0, ?)
    """, (user_id, SEASON_CODE, STARTING_BUDGET, ora()))
    db.commit(); db.close(); return get_team(user_id)


def team_products(team_id):
    db = connessione(); cur = db.cursor()
    cur.execute("""
        SELECT tp.*, p.name, p.cost FROM league_team_products tp
        JOIN league_products p ON p.code=tp.product_code
        WHERE tp.team_id=? ORDER BY tp.id
    """, (team_id,))
    rows = cur.fetchall(); db.close(); return rows


def budget_used(team_id):
    return sum(r["cost"] for r in team_products(team_id))


def set_team_name(user_id, name):
    name = (name or "").strip()
    if not TEAM_NAME_RE.fullmatch(name):
        return False, "Nome squadra non valido: usa 3-24 caratteri."
    team = ensure_team(user_id)
    if team["confirmed"]: return False, "La squadra è già confermata."
    db = connessione(); cur = db.cursor()
    cur.execute("UPDATE league_teams SET team_name=? WHERE id=?", (name, team["id"]))
    db.commit(); db.close(); return True, None


def add_product(user_id, product_code):
    team = ensure_team(user_id)
    if team["confirmed"]: return False, "La squadra è già confermata."
    db = connessione(); cur = db.cursor()
    cur.execute("SELECT * FROM league_products WHERE code=? AND active=1", (product_code,))
    p = cur.fetchone()
    if not p:
        db.close(); return False, "Prodotto non disponibile."
    current = team_products(team["id"])
    if any(x["category"] == p["category"] for x in current):
        db.close(); return False, "Hai già scelto un prodotto per questa categoria."
    if budget_used(team["id"]) + p["cost"] > STARTING_BUDGET:
        db.close(); return False, "Budget insufficiente."
    cur.execute("""
        INSERT INTO league_team_products (team_id, product_code, category, is_captain, added_at)
        VALUES (?, ?, ?, 0, ?)
    """, (team["id"], p["code"], p["category"], ora()))
    db.commit(); db.close(); return True, None


def set_captain(user_id, product_code):
    team = get_team(user_id)
    if not team or team["confirmed"]: return False
    db = connessione(); cur = db.cursor()
    cur.execute("UPDATE league_team_products SET is_captain=0 WHERE team_id=?", (team["id"],))
    cur.execute("UPDATE league_team_products SET is_captain=1 WHERE team_id=? AND product_code=?", (team["id"], product_code))
    ok = cur.rowcount == 1
    db.commit(); db.close(); return ok


def confirm_team(user_id):
    team = get_team(user_id)
    if not team or not team["team_name"]: return False, "Prima scegli il nome della squadra."
    products = team_products(team["id"])
    if len(products) != TEAM_SIZE: return False, f"Devi scegliere {TEAM_SIZE} prodotti."
    if sum(1 for p in products if p["is_captain"]) != 1: return False, "Devi scegliere il Capitano."
    db = connessione(); cur = db.cursor()
    cur.execute("UPDATE league_teams SET confirmed=1, confirmed_at=? WHERE id=?", (ora(), team["id"]))
    db.commit(); db.close(); return True, None


def score_for_discount(discount):
    if discount is None or discount < 10: return 0
    if discount < 20: return 1
    if discount < 30: return 3
    if discount < 40: return 5
    if discount < 50: return 8
    return 12


def classifica(limit=20):
    db = connessione(); cur = db.cursor()
    cur.execute("""
        SELECT t.telegram_id, t.team_name, t.score, u.league_username
        FROM league_teams t JOIN league_users u ON u.telegram_id=t.telegram_id
        WHERE t.season_code=? AND t.confirmed=1
        ORDER BY t.score DESC, t.confirmed_at ASC LIMIT ?
    """, (SEASON_CODE, limit))
    rows = cur.fetchall(); db.close(); return rows


def posizione(user_id):
    db = connessione(); cur = db.cursor()
    cur.execute("SELECT score, confirmed_at FROM league_teams WHERE telegram_id=? AND season_code=? AND confirmed=1", (user_id, SEASON_CODE))
    mine = cur.fetchone()
    if not mine: db.close(); return None
    cur.execute("""
        SELECT COUNT(*)+1 FROM league_teams
        WHERE season_code=? AND confirmed=1 AND (score>? OR (score=? AND confirmed_at<?))
    """, (SEASON_CODE, mine["score"], mine["score"], mine["confirmed_at"]))
    pos = cur.fetchone()[0]; db.close(); return pos


def menu_league():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚽ LA MIA SQUADRA", callback_data="league_team"), InlineKeyboardButton("🏆 CLASSIFICA", callback_data="league_rank")],
        [InlineKeyboardButton("🛒 MERCATO", callback_data="league_market"), InlineKeyboardButton("📊 PROFILO", callback_data="league_profile")],
        [InlineKeyboardButton("🪙 GETTONI D'ORO", callback_data="league_gold"), InlineKeyboardButton("📖 REGOLAMENTO", callback_data="league_rules")],
        [InlineKeyboardButton("⬅️ MENU PRINCIPALE", callback_data="menu_utente")],
    ])


def preseason_menu(registered):
    rows = []
    if not registered:
        rows.append([InlineKeyboardButton("🚀 PRE-ISCRIVITI", callback_data="league_signup")])
    else:
        rows.append([InlineKeyboardButton("👤 IL MIO PROFILO", callback_data="league_profile")])
    rows.append([InlineKeyboardButton("📖 COME FUNZIONA", callback_data="league_rules")])
    rows.append([InlineKeyboardButton("⬅️ MENU PRINCIPALE", callback_data="menu_utente")])
    return InlineKeyboardMarkup(rows)


async def club_home(update, context):
    """Mantiene il vecchio nome funzione per non rompere manual_bot.py."""
    query = update.callback_query
    if query: await query.answer()
    user = update.effective_user
    league_user = get_league_user(user.id)
    if league_user: registra_o_aggiorna_telegram_user(user)
    state = player_state(user.id)
    if state == "PRESEASON":
        text = (
            "🏆 BESTPRICE LEAGUE\n\n"
            "Sta arrivando il Fantacalcio delle Offerte 🔥\n\n"
            f"📅 PRIMA STAGIONE: {SEASON_NAME}\n"
            f"{countdown_text()}\n\n"
            "💰 100 crediti • 🛒 5 prodotti • ©️ 1 Capitano\n\n"
            "🥇 1°: 30 Gettoni d'Oro 🪙\n"
            "🥈 2°: 10 Gettoni d'Oro 🪙\n\n"
            + (f"✅ Pre-iscritto come {league_user['league_username']}" if league_user else "👇 Pre-iscriviti e scegli il tuo username di gioco.")
        )
        await query.message.reply_text(text, reply_markup=preseason_menu(bool(league_user)))
        return
    if not league_user:
        await query.message.reply_text("🏆 BESTPRICE LEAGUE\n\nPrima di giocare devi creare il tuo username.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👤 CREA USERNAME", callback_data="league_signup")]]))
        return
    await query.message.reply_text("🏆 BESTPRICE LEAGUE\n\n🟢 Stagione attiva!\nCrea la tua rosa, scegli il Capitano e scala la classifica.", reply_markup=menu_league())


async def league_signup(update, context):
    q = update.callback_query; await q.answer()
    if get_league_user(update.effective_user.id):
        await q.message.reply_text("✅ Sei già iscritto alla BestPrice League.", reply_markup=preseason_menu(True)); return
    context.user_data["league_waiting"] = "username"
    await q.message.reply_text("👤 CREA IL TUO USERNAME LEAGUE\n\n3-20 caratteri. Puoi usare lettere, numeri e _.\nEsempio: Rino89\n\n✏️ Scrivilo ora in chat:")


async def league_text_input(update, context):
    """Da collegare a MessageHandler(filters.TEXT & ~filters.COMMAND, league_text_input)."""
    waiting = context.user_data.get("league_waiting")
    if not waiting: return False
    text = (update.message.text or "").strip()
    user = update.effective_user
    if waiting == "username":
        ok, err = crea_league_user(user, text)
        if not ok:
            await update.message.reply_text(f"❌ {err}\n\nProva con un altro username:"); return True
        context.user_data.pop("league_waiting", None)
        await update.message.reply_text(f"✅ BENVENUTO {text.upper()}!\n\n🎟 Pre-iscrizione completata.\n{countdown_text()}\n\nIl 1° ottobre si aprirà il mercato.", reply_markup=preseason_menu(True)); return True
    if waiting == "team_name":
        ok, err = set_team_name(user.id, text)
        if not ok:
            await update.message.reply_text(f"❌ {err}\n\nScrivi un altro nome:"); return True
        context.user_data.pop("league_waiting", None)
        await update.message.reply_text(f"✅ {text} creata!\n\n💰 Budget: {STARTING_BUDGET}\nOra vai al mercato.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 VAI AL MERCATO", callback_data="league_market")]])); return True
    return False


async def league_profile(update, context):
    q=update.callback_query; await q.answer(); uid=update.effective_user.id
    u=get_league_user(uid)
    if not u:
        await q.message.reply_text("Prima devi pre-iscriverti."); return
    team=get_team(uid); pos=posizione(uid)
    text=(f"👤 PROFILO LEAGUE\n\nUsername: {u['league_username']}\n🪙 Gettoni d'Oro: {u['gold_tokens']}\n")
    if team:
        text += f"⚽ Squadra: {team['team_name'] or 'da creare'}\n🏆 Punti stagione: {team['score']}\n"
    if pos: text += f"📊 Posizione: #{pos}\n"
    if player_state(uid)=="PRESEASON": text += f"\n{countdown_text()}"
    await q.message.reply_text(text, reply_markup=menu_league() if player_state(uid)!='PRESEASON' else preseason_menu(True))


async def league_team(update, context):
    q=update.callback_query; await q.answer(); uid=update.effective_user.id
    if not get_league_user(uid):
        await q.message.reply_text("Prima devi creare il tuo username League."); return
    if player_state(uid)=="PRESEASON":
        await q.message.reply_text("🔒 Il mercato apre il 1° ottobre."); return
    team=ensure_team(uid)
    if not team["team_name"]:
        context.user_data["league_waiting"]="team_name"
        await q.message.reply_text("🏟 CREA LA TUA SQUADRA\n\nScegli un nome da 3 a 24 caratteri.\n✏️ Scrivilo ora:"); return
    products=team_products(team["id"])
    lines=[f"⚽ {team['team_name'].upper()}", "", f"💰 Budget: {STARTING_BUDGET-budget_used(team['id'])}/{STARTING_BUDGET}", f"🏆 Punti: {team['score']}", ""]
    for p in products: lines.append(f"{'©️ ' if p['is_captain'] else ''}{CATEGORY_LABEL[p['category']]} — {p['name']} ({p['cost']})")
    if not products: lines.append("Rosa ancora vuota.")
    buttons=[[InlineKeyboardButton("🛒 MERCATO", callback_data="league_market")]]
    if len(products)==TEAM_SIZE and not team["confirmed"]: buttons.append([InlineKeyboardButton("©️ SCEGLI CAPITANO", callback_data="league_captain")])
    buttons.append([InlineKeyboardButton("⬅️ LEAGUE", callback_data="club_home")])
    await q.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def league_market(update, context):
    q=update.callback_query; await q.answer(); uid=update.effective_user.id
    if player_state(uid)=="PRESEASON":
        await q.message.reply_text("🔒 Il mercato apre il 1° ottobre."); return
    if not get_league_user(uid): await q.message.reply_text("Prima crea il tuo username League."); return
    team=ensure_team(uid)
    if not team["team_name"]:
        context.user_data["league_waiting"]="team_name"; await q.message.reply_text("🏟 Prima scegli il nome della squadra. Scrivilo ora:"); return
    if team["confirmed"]:
        await q.answer("🔒 Rosa già confermata.", show_alert=True); return
    selected={p['category'] for p in team_products(team['id'])}
    buttons=[]
    for cat in CATEGORY_ORDER:
        mark="✅" if cat in selected else "➡️"
        buttons.append([InlineKeyboardButton(f"{mark} {CATEGORY_LABEL[cat]}", callback_data=f"league_cat_{cat}")])
    buttons.append([InlineKeyboardButton("⬅️ LA MIA SQUADRA", callback_data="league_team")])
    await q.message.reply_text(f"🛒 MERCATO BESTPRICE\n\n💰 Budget disponibile: {STARTING_BUDGET-budget_used(team['id'])}\n⚽ Rosa: {len(selected)}/{TEAM_SIZE}\n\nScegli una categoria:", reply_markup=InlineKeyboardMarkup(buttons))


async def league_category(update, context):
    q=update.callback_query; await q.answer(); uid=update.effective_user.id
    cat=q.data.replace("league_cat_", "")
    team=ensure_team(uid)
    db=connessione(); cur=db.cursor(); cur.execute("SELECT * FROM league_products WHERE category=? AND active=1 ORDER BY cost DESC", (cat,)); rows=cur.fetchall(); db.close()
    buttons=[[InlineKeyboardButton(f"{p['name']} • {p['cost']} 💰", callback_data=f"league_buy_{p['code']}")] for p in rows]
    buttons.append([InlineKeyboardButton("⬅️ MERCATO", callback_data="league_market")])
    await q.message.reply_text(f"{CATEGORY_LABEL.get(cat, cat)}\n\n💰 Budget disponibile: {STARTING_BUDGET-budget_used(team['id'])}\nScegli il prodotto:", reply_markup=InlineKeyboardMarkup(buttons))


async def league_buy(update, context):
    q=update.callback_query; await q.answer(); code=q.data.replace("league_buy_", "")
    ok,err=add_product(update.effective_user.id, code)
    if not ok:
        await q.answer(f"❌ {err}", show_alert=True); return
    team=get_team(update.effective_user.id); products=team_products(team['id'])
    if len(products)==TEAM_SIZE:
        await q.message.reply_text("✅ ROSA COMPLETA!\n\nOra scegli il Capitano: i suoi punti valgono x2.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("©️ SCEGLI CAPITANO", callback_data="league_captain")]]))
    else:
        await q.message.reply_text(f"✅ Prodotto aggiunto!\n⚽ Rosa: {len(products)}/{TEAM_SIZE}\n💰 Budget rimasto: {STARTING_BUDGET-budget_used(team['id'])}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 CONTINUA IL MERCATO", callback_data="league_market")]]))


async def league_captain(update, context):
    q=update.callback_query; await q.answer(); team=get_team(update.effective_user.id)
    if not team: return
    products=team_products(team['id'])
    if len(products)!=TEAM_SIZE:
        await q.answer("Completa prima la rosa.", show_alert=True); return
    buttons=[[InlineKeyboardButton(f"©️ {p['name']}", callback_data=f"league_cap_{p['product_code']}")] for p in products]
    await q.message.reply_text("©️ SCEGLI IL CAPITANO\n\nI suoi punti valgono x2.\nScegli con attenzione:", reply_markup=InlineKeyboardMarkup(buttons))


async def league_set_captain(update, context):
    q=update.callback_query; await q.answer(); code=q.data.replace("league_cap_", "")
    if not set_captain(update.effective_user.id, code):
        await q.answer("Operazione non disponibile.", show_alert=True); return
    team=get_team(update.effective_user.id); products=team_products(team['id']); cap=next(p for p in products if p['is_captain'])
    await q.message.reply_text(f"©️ {cap['name']} è il tuo Capitano!\n\nControlla la rosa e confermala.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ CONFERMA SQUADRA", callback_data="league_confirm")],[InlineKeyboardButton("⬅️ LA MIA SQUADRA", callback_data="league_team")]]))


async def league_confirm(update, context):
    q=update.callback_query; await q.answer(); ok,err=confirm_team(update.effective_user.id)
    if not ok:
        await q.answer(f"❌ {err}", show_alert=True); return
    team=get_team(update.effective_user.id)
    await q.message.reply_text(f"🔒 SQUADRA CONFERMATA!\n\n⚽ {team['team_name']}\n💰 Budget usato: {budget_used(team['id'])}/{STARTING_BUDGET}\n\nDa questo momento la rosa è iscritta alla stagione {SEASON_NAME}. 🔥", reply_markup=menu_league())


async def league_rank(update, context):
    q=update.callback_query; await q.answer(); rows=classifica(); uid=update.effective_user.id
    lines=[f"🏆 CLASSIFICA — {SEASON_NAME}", ""]
    medals=["🥇","🥈","🥉"]
    for i,r in enumerate(rows,1):
        mark=medals[i-1] if i<=3 else f"{i}°"
        you=" ← TU" if r['telegram_id']==uid else ""
        lines.append(f"{mark} {r['league_username']} — {r['score']} pt{you}")
    if not rows: lines.append("Nessuna squadra confermata.")
    pos=posizione(uid)
    if pos and all(r['telegram_id']!=uid for r in rows): lines += ["", f"📍 La tua posizione: #{pos}"]
    await q.message.reply_text("\n".join(lines), reply_markup=menu_league())


async def league_gold(update, context):
    q=update.callback_query; await q.answer(); u=get_league_user(update.effective_user.id)
    tokens=u['gold_tokens'] if u else 0
    await q.message.reply_text(f"🪙 GETTONI D'ORO\n\nIl tuo saldo: {tokens} 🪙\n\nI Gettoni sono trofei virtuali permanenti.\n🥇 1° del mese: +{GOLD_FIRST}\n🥈 2° del mese: +{GOLD_SECOND}\n\nNon hanno valore economico e non sono convertibili in denaro o premi.", reply_markup=menu_league())


async def league_rules(update, context):
    q=update.callback_query; await q.answer()
    text=("📖 COME FUNZIONA\n\n"
          "💰 Hai 100 crediti virtuali.\n"
          "⚽ Crei una rosa di 5 prodotti: Smartphone, Audio, TV/Streaming, Casa e Jolly.\n"
          "©️ Scegli un Capitano: i suoi punti valgono x2.\n\n"
          "📈 PUNTI SCONTO\n"
          "10-19% = +1\n20-29% = +3\n30-39% = +5\n40-49% = +8\n50% o più = +12\n\n"
          "🏆 Vince chi totalizza più punti nella stagione mensile.\n"
          f"🥇 1° = {GOLD_FIRST} Gettoni d'Oro virtuali\n🥈 2° = {GOLD_SECOND} Gettoni d'Oro virtuali\n\n"
          "I Gettoni non hanno valore economico. Le regole potranno essere affinate prima dell'apertura del mercato.")
    await q.message.reply_text(text, reply_markup=preseason_menu(bool(get_league_user(update.effective_user.id))) if stato_stagione()=="PRESEASON" else menu_league())


async def admin_club_menu(update, context):
    """Mantiene il vecchio callback admin_club, ma mostra la nuova League."""
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer()
    db=connessione(); cur=db.cursor()
    cur.execute("SELECT COUNT(*) FROM league_users"); users=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM league_teams WHERE season_code=? AND confirmed=1", (SEASON_CODE,)); teams=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM league_score_events WHERE season_code=?", (SEASON_CODE,)); events=cur.fetchone()[0]
    db.close()
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 GIOCATORI", callback_data="league_admin_users"), InlineKeyboardButton("🏆 CLASSIFICA", callback_data="league_rank")],
        [InlineKeyboardButton("📦 PRODOTTI", callback_data="league_admin_products"), InlineKeyboardButton("📜 EVENTI PUNTI", callback_data="league_admin_events")],
        [InlineKeyboardButton("⬅️ MENU PRINCIPALE", callback_data="menu_admin")],
    ])
    await q.message.reply_text(f"⚙️ GESTIONE BESTPRICE LEAGUE\n\n📅 {SEASON_NAME}\n🟢 Stato: {stato_stagione()}\n👥 Giocatori: {users}\n⚽ Squadre confermate: {teams}\n📜 Eventi punti: {events}\n\n{countdown_text() if stato_stagione()=='PRESEASON' else ''}", reply_markup=kb)


async def league_admin_users(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer(); db=connessione(); cur=db.cursor()
    cur.execute("SELECT league_username, telegram_id, gold_tokens, data_iscrizione FROM league_users ORDER BY data_iscrizione DESC LIMIT 50")
    rows=cur.fetchall(); db.close()
    lines=["👥 GIOCATORI LEAGUE",""]+[f"• {r['league_username']} — ID {r['telegram_id']} — 🪙 {r['gold_tokens']}" for r in rows]
    if not rows: lines.append("Nessun giocatore.")
    await q.message.reply_text("\n".join(lines))


async def league_admin_products(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer(); db=connessione(); cur=db.cursor()
    cur.execute("SELECT * FROM league_products WHERE active=1 ORDER BY category,cost DESC"); rows=cur.fetchall(); db.close()
    lines=["📦 CATALOGO LEAGUE",""]
    for cat in CATEGORY_ORDER:
        lines.append(CATEGORY_LABEL[cat])
        lines += [f"• {r['name']} — {r['cost']} 💰" for r in rows if r['category']==cat]
        lines.append("")
    await q.message.reply_text("\n".join(lines))


async def league_admin_events(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer(); db=connessione(); cur=db.cursor()
    cur.execute("SELECT * FROM league_score_events WHERE season_code=? ORDER BY id DESC LIMIT 30", (SEASON_CODE,)); rows=cur.fetchall(); db.close()
    lines=["📜 ULTIMI EVENTI PUNTI",""]+[f"• {r['product_code']} +{r['points']} — {r['reason']}" for r in rows]
    if not rows: lines.append("Nessun evento: il motore Amazon verrà collegato nella Fase 2.")
    await q.message.reply_text("\n".join(lines))


# Alias compatibilità: se manual_bot importa ancora menu_club, non si rompe.
def menu_club():
    return menu_league()


# Chiamare questa funzione all'avvio del bot.
inizializza_database()

# =========================================================
# ADMIN BILANCIAMENTO LEAGUE V1
# =========================================================

def _ensure_balance_schema():
    db = connessione(); cur = db.cursor()
    cur.execute("PRAGMA table_info(league_products)")
    cols = {r[1] for r in cur.fetchall()}
    if "asin" not in cols:
        cur.execute("ALTER TABLE league_products ADD COLUMN asin TEXT")
    if "coefficient" not in cols:
        cur.execute("ALTER TABLE league_products ADD COLUMN coefficient REAL NOT NULL DEFAULT 1.0")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_league_products_asin ON league_products(asin) WHERE asin IS NOT NULL AND asin<>''")
    cur.execute("CREATE TABLE IF NOT EXISTS league_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    cur.execute("PRAGMA table_info(league_score_events)")
    event_cols = {r[1] for r in cur.fetchall()}
    if "is_test" not in event_cols:
        cur.execute("ALTER TABLE league_score_events ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0")
    for k, v in {"pts_10":"1","pts_20":"3","pts_30":"5","pts_40":"8","pts_50":"12","captain_multiplier":"2","test_mode":"0"}.items():
        cur.execute("INSERT OR IGNORE INTO league_settings(key,value) VALUES(?,?)", (k,v))
    db.commit(); db.close()


def league_setting(key, default="0"):
    with connessione() as db:
        row = db.execute("SELECT value FROM league_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_league_setting(key, value):
    with connessione() as db:
        db.execute("INSERT OR REPLACE INTO league_settings(key,value) VALUES(?,?)", (key, str(value)))


def score_for_discount(discount):
    d = float(discount or 0)
    if d < 10: return 0
    if d < 20: return int(league_setting("pts_10", "1"))
    if d < 30: return int(league_setting("pts_20", "3"))
    if d < 40: return int(league_setting("pts_30", "5"))
    if d < 50: return int(league_setting("pts_40", "8"))
    return int(league_setting("pts_50", "12"))


def product_adjusted_points(product_code, discount, captain=False):
    with connessione() as db:
        row = db.execute("SELECT coefficient FROM league_products WHERE code=?", (product_code,)).fetchone()
    coeff = float(row["coefficient"] if row else 1.0)
    base = score_for_discount(discount)
    pts = int(round(base * coeff))
    if captain:
        pts *= int(league_setting("captain_multiplier", "2"))
    return base, coeff, pts


async def league_admin_scoring(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer()
    vals=[league_setting(f"pts_{x}") for x in (10,20,30,40,50)]
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton(f"10–19% → {vals[0]}", callback_data="league_admin_pts_10"), InlineKeyboardButton(f"20–29% → {vals[1]}", callback_data="league_admin_pts_20")],
        [InlineKeyboardButton(f"30–39% → {vals[2]}", callback_data="league_admin_pts_30"), InlineKeyboardButton(f"40–49% → {vals[3]}", callback_data="league_admin_pts_40")],
        [InlineKeyboardButton(f"≥50% → {vals[4]}", callback_data="league_admin_pts_50")],
        [InlineKeyboardButton(f"©️ Capitano x{league_setting('captain_multiplier','2')}", callback_data="league_admin_captain_mult")],
        [InlineKeyboardButton("⬅️ GESTIONE LEAGUE", callback_data="admin_club")],
    ])
    await q.message.reply_text("⚽ PUNTEGGI GLOBALI\n\nPremi una fascia per modificarne i punti. La modifica vale solo per i nuovi eventi.", reply_markup=kb)


async def league_admin_set_scoring(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer()
    key=q.data.replace("league_admin_pts_", "pts_")
    context.user_data["league_waiting"]="admin_setting"
    context.user_data["league_setting_key"]=key
    await q.message.reply_text(f"✏️ Valore attuale: {league_setting(key)} punti.\nScrivi il nuovo valore intero (0–100):")


async def league_admin_set_captain_mult(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer()
    context.user_data["league_waiting"]="admin_setting"
    context.user_data["league_setting_key"]="captain_multiplier"
    await q.message.reply_text(f"©️ Moltiplicatore attuale: x{league_setting('captain_multiplier','2')}\nScrivi il nuovo valore intero (1–5):")


async def league_admin_products(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer()
    with connessione() as db:
        rows=db.execute("SELECT code,name,category,cost,coefficient,active FROM league_products ORDER BY category,cost DESC,name").fetchall()
    kb=[]
    for r in rows[:40]:
        stato="" if r["active"] else " ⛔"
        kb.append([InlineKeyboardButton(f"{r['name']} · {r['cost']}💰 · {float(r['coefficient']):g}x{stato}", callback_data=f"league_admin_product_{r['code']}")])
    kb.append([InlineKeyboardButton("⚽ PUNTEGGI GLOBALI", callback_data="league_admin_scoring")])
    kb.append([InlineKeyboardButton("⬅️ GESTIONE LEAGUE", callback_data="admin_club")])
    await q.message.reply_text("📦 PRODOTTI LEAGUE\n\nSeleziona un prodotto per quotazione, coefficiente, simulazione o stato.", reply_markup=InlineKeyboardMarkup(kb))


async def league_admin_product(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer(); code=q.data.replace("league_admin_product_", "", 1)
    with connessione() as db:
        p=db.execute("SELECT * FROM league_products WHERE code=?", (code,)).fetchone()
    if not p: return await q.answer("Prodotto non trovato", show_alert=True)
    context.user_data["league_admin_product"]=code
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("➖1 💰", callback_data=f"league_cost_{code}_m1"),InlineKeyboardButton("➕1 💰", callback_data=f"league_cost_{code}_p1"),InlineKeyboardButton("✏️ QUOTAZIONE", callback_data=f"league_cost_{code}_set")],
        [InlineKeyboardButton("0.50x", callback_data=f"league_coeff_{code}_050"),InlineKeyboardButton("0.75x", callback_data=f"league_coeff_{code}_075"),InlineKeyboardButton("1.00x", callback_data=f"league_coeff_{code}_100")],
        [InlineKeyboardButton("1.25x", callback_data=f"league_coeff_{code}_125"),InlineKeyboardButton("1.50x", callback_data=f"league_coeff_{code}_150")],
        [InlineKeyboardButton("🧪 SIMULA", callback_data=f"league_sim_{code}"), InlineKeyboardButton("⛔/✅ ATTIVA", callback_data=f"league_toggle_{code}")],
        [InlineKeyboardButton("⬅️ PRODOTTI", callback_data="league_admin_products")],
    ])
    await q.message.reply_text(f"📦 {p['name']}\n\n📂 {CATEGORY_LABEL.get(p['category'],p['category'])}\n🆔 ASIN: {p['asin'] or 'da collegare'}\n💰 Quotazione: {p['cost']} crediti\n🎚 Coefficiente: {float(p['coefficient']):g}x\nStato: {'🟢 ATTIVO' if p['active'] else '🔴 DISATTIVATO'}", reply_markup=kb)


async def league_admin_cost(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer(); m=re.fullmatch(r"league_cost_(.+)_(m1|p1|set)",q.data)
    if not m: return
    code, action=m.groups()
    if action=="set":
        context.user_data["league_waiting"]="admin_cost"; context.user_data["league_admin_product"]=code
        return await q.message.reply_text("💰 Scrivi la nuova quotazione in crediti (1–100):")
    delta=-1 if action=="m1" else 1
    with connessione() as db:
        db.execute("UPDATE league_products SET cost=MAX(1,cost+?) WHERE code=?",(delta,code))
    await q.message.reply_text("✅ Quotazione aggiornata.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 TORNA AL PRODOTTO", callback_data=f"league_admin_product_{code}")]]))


async def league_admin_coeff(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer(); m=re.fullmatch(r"league_coeff_(.+)_(050|075|100|125|150)",q.data)
    if not m:return
    code,val=m.groups(); coeff={"050":.5,"075":.75,"100":1.0,"125":1.25,"150":1.5}[val]
    with connessione() as db: db.execute("UPDATE league_products SET coefficient=? WHERE code=?",(coeff,code))
    await q.message.reply_text(f"✅ Coefficiente impostato a {coeff:g}x. Vale solo per i nuovi eventi.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 TORNA AL PRODOTTO",callback_data=f"league_admin_product_{code}")]]))


async def league_admin_toggle(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer(); code=q.data.replace("league_toggle_","",1)
    with connessione() as db: db.execute("UPDATE league_products SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE code=?",(code,))
    await q.message.reply_text("✅ Stato prodotto aggiornato.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 TORNA AL PRODOTTO",callback_data=f"league_admin_product_{code}")]]))


async def league_admin_sim(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer(); code=q.data.replace("league_sim_","",1)
    with connessione() as db: p=db.execute("SELECT name FROM league_products WHERE code=?",(code,)).fetchone()
    lines=[f"🧪 SIMULAZIONE — {p['name'] if p else code}",""]
    for d in (10,20,30,40,50,60):
        base,coeff,pts=product_adjusted_points(code,d,False); _,_,cap=product_adjusted_points(code,d,True)
        lines.append(f"-{d}% → base {base} · {coeff:g}x = +{pts} · ©️ +{cap}")
    lines += ["","ℹ️ Nessun punto è stato scritto nel database."]
    await q.message.reply_text("\n".join(lines),reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 TORNA AL PRODOTTO",callback_data=f"league_admin_product_{code}")]]))


# Estende l'input testuale League con i controlli amministratore.
_original_league_text_input = league_text_input
async def league_text_input(update, context):
    waiting=context.user_data.get("league_waiting")
    if waiting in {"admin_setting","admin_cost"}:
        if not e_admin(update.effective_user.id): return False
        value=(update.message.text or "").strip()
        if not value.isdigit():
            await update.message.reply_text("❌ Inserisci un numero intero."); return True
        n=int(value)
        if waiting=="admin_setting":
            key=context.user_data.get("league_setting_key")
            maxv=5 if key=="captain_multiplier" else 100
            minv=1 if key=="captain_multiplier" else 0
            if not minv <= n <= maxv:
                await update.message.reply_text(f"❌ Inserisci un valore tra {minv} e {maxv}."); return True
            set_league_setting(key,n)
            context.user_data.pop("league_setting_key",None)
            context.user_data.pop("league_waiting",None)
            await update.message.reply_text("✅ Punteggio aggiornato. La modifica vale solo per i nuovi eventi."); return True
        code=context.user_data.get("league_admin_product")
        if not 1 <= n <= 100:
            await update.message.reply_text("❌ Inserisci una quotazione tra 1 e 100."); return True
        with connessione() as db: db.execute("UPDATE league_products SET cost=? WHERE code=?",(n,code))
        context.user_data.pop("league_waiting",None)
        await update.message.reply_text(f"✅ Quotazione aggiornata a {n} crediti."); return True
    return await _original_league_text_input(update,context)

_ensure_balance_schema()

# Ridefinizione finale menu admin con controlli di bilanciamento.
async def admin_club_menu(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer()
    with connessione() as db:
        users=db.execute("SELECT COUNT(*) FROM league_users").fetchone()[0]
        teams=db.execute("SELECT COUNT(*) FROM league_teams WHERE season_code=? AND confirmed=1",(SEASON_CODE,)).fetchone()[0]
        events=db.execute("SELECT COUNT(*) FROM league_score_events WHERE season_code=?",(SEASON_CODE,)).fetchone()[0]
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 GIOCATORI",callback_data="league_admin_users"),InlineKeyboardButton("🏆 CLASSIFICA",callback_data="league_rank")],
        [InlineKeyboardButton("📦 PRODOTTI",callback_data="league_admin_products"),InlineKeyboardButton("⚽ PUNTEGGI",callback_data="league_admin_scoring")],
        [InlineKeyboardButton("📜 EVENTI",callback_data="league_admin_events")],
        [InlineKeyboardButton("⬅️ MENU PRINCIPALE",callback_data="menu_admin")],
    ])
    extra=countdown_text() if stato_stagione()=="PRESEASON" else ""
    await q.message.reply_text(f"⚙️ GESTIONE BESTPRICE LEAGUE\n\n📅 {SEASON_NAME}\n🟢 Stato: {stato_stagione()}\n👥 Giocatori: {users}\n⚽ Squadre confermate: {teams}\n📜 Eventi punti: {events}\n\n{extra}",reply_markup=kb)


# =========================================================
# MODALITÀ TEST AMMINISTRATORE
# =========================================================

def reset_admin_test_player(user_id):
    """Azzera solo la squadra/eventi test dell'admin, conservando username e Gettoni."""
    with connessione() as db:
        team = db.execute(
            "SELECT id FROM league_teams WHERE telegram_id=? AND season_code=?",
            (user_id, SEASON_CODE),
        ).fetchone()
        if team:
            team_id = team["id"]
            db.execute("DELETE FROM league_score_events WHERE team_id=? AND is_test=1", (team_id,))
            db.execute("DELETE FROM league_team_products WHERE team_id=?", (team_id,))
            db.execute(
                "UPDATE league_teams SET team_name=NULL, score=0, confirmed=0, confirmed_at=NULL WHERE id=?",
                (team_id,),
            )


async def league_admin_test_toggle(update, context):
    if not await verifica_admin(update): return
    q = update.callback_query; await q.answer()
    new_value = "0" if test_mode_active() else "1"
    set_league_setting("test_mode", new_value)
    stato = "🟢 ATTIVA" if new_value == "1" else "🔴 DISATTIVATA"
    await q.message.reply_text(
        f"🧪 MODALITÀ TEST {stato}\n\n"
        + ("Ora puoi aprire la League come giocatore e bypassare il PRESEASON." if new_value == "1" else "Il bypass admin è stato disattivato."),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ GESTIONE LEAGUE", callback_data="admin_club")]])
    )


async def league_admin_test_player(update, context):
    if not await verifica_admin(update): return
    q = update.callback_query; await q.answer()
    if not test_mode_active():
        await q.message.reply_text("❌ Attiva prima la Modalità Test."); return
    # Mostra esattamente la home che vede un giocatore con stagione attiva.
    user = update.effective_user
    league_user = get_league_user(user.id)
    if not league_user:
        await q.message.reply_text(
            "🧪 VISTA GIOCATORE\n\nPrima crea il tuo username League.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👤 CREA USERNAME", callback_data="league_signup")]])
        ); return
    await q.message.reply_text(
        "🧪 VISTA GIOCATORE — TEST\n\n🏆 BESTPRICE LEAGUE\n🟢 Mercato aperto in modalità test.\n"
        "Puoi creare la squadra, scegliere i 5 prodotti, il Capitano e confermare la rosa.",
        reply_markup=menu_league(),
    )


async def league_admin_test_reset(update, context):
    if not await verifica_admin(update): return
    q = update.callback_query; await q.answer()
    reset_admin_test_player(update.effective_user.id)
    context.user_data.pop("league_waiting", None)
    await q.message.reply_text(
        "♻️ TEST AZZERATO\n\nLa tua squadra, rosa, punteggio ed eventi TEST sono stati azzerati.\nUsername League e Gettoni d'Oro sono rimasti invariati.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 APRI COME GIOCATORE", callback_data="league_admin_test_player")],
            [InlineKeyboardButton("⬅️ GESTIONE LEAGUE", callback_data="admin_club")],
        ]),
    )


async def league_admin_test_sim_team(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer()
    if not test_mode_active():
        await q.message.reply_text("❌ Attiva prima la Modalità Test."); return
    team=get_team(update.effective_user.id)
    if not team or not team["confirmed"]:
        await q.message.reply_text("⚠️ Prima crea e conferma la tua squadra test.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👤 APRI COME GIOCATORE", callback_data="league_admin_test_player")]])); return
    products=team_products(team["id"])
    buttons=[[InlineKeyboardButton(("©️ " if p["is_captain"] else "")+p["name"], callback_data=f"league_test_prod_{p['product_code']}")] for p in products]
    buttons.append([InlineKeyboardButton("⬅️ GESTIONE LEAGUE", callback_data="admin_club")])
    await q.message.reply_text("⚽ SIMULA OFFERTA SULLA TUA ROSA\n\nScegli il prodotto:", reply_markup=InlineKeyboardMarkup(buttons))


async def league_admin_test_product(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer(); code=q.data.replace("league_test_prod_", "", 1)
    with connessione() as db:
        p=db.execute("SELECT name FROM league_products WHERE code=?",(code,)).fetchone()
    if not p: return
    buttons=[[InlineKeyboardButton(f"-{d}%", callback_data=f"league_test_score_{code}_{d}") for d in (10,20,30)],
             [InlineKeyboardButton(f"-{d}%", callback_data=f"league_test_score_{code}_{d}") for d in (40,50,60)],
             [InlineKeyboardButton("⬅️ SCEGLI PRODOTTO", callback_data="league_admin_test_sim")]]
    await q.message.reply_text(f"🧪 {p['name']}\n\nScegli lo sconto da simulare:", reply_markup=InlineKeyboardMarkup(buttons))


async def league_admin_test_score(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer()
    m=re.fullmatch(r"league_test_score_(.+)_(10|20|30|40|50|60)", q.data)
    if not m: return
    code, discount=m.groups(); discount=int(discount)
    uid=update.effective_user.id; team=get_team(uid)
    if not test_mode_active() or not team or not team["confirmed"]: return
    products=team_products(team["id"]); selected=next((p for p in products if p["product_code"]==code),None)
    if not selected: return
    base, coeff, points=product_adjusted_points(code,discount,bool(selected["is_captain"]))
    event_key=f"TEST:{uid}:{team['id']}:{code}:{ora()}"
    with connessione() as db:
        db.execute("UPDATE league_teams SET score=score+? WHERE id=?",(points,team["id"]))
        db.execute("""INSERT INTO league_score_events
            (event_key,season_code,telegram_id,team_id,product_code,discount,base_points,multiplier,points,reason,created_at,is_test)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,1)""",
            (event_key,SEASON_CODE,uid,team["id"],code,discount,base,int(league_setting("captain_multiplier","2")) if selected["is_captain"] else 1,points,"SIMULAZIONE TEST ADMIN",ora()))
    updated=get_team(uid)
    captain_note=f" · ©️ x{league_setting('captain_multiplier','2')}" if selected["is_captain"] else ""
    await q.message.reply_text(
        f"🚨 GOOOOL! ⚽🧪\n\n{selected['name']} è sceso del {discount}%!\n\n"
        f"Base: +{base} · coeff. {coeff:g}x{captain_note}\n⚽ +{points} PUNTI TEST\n\n"
        f"{updated['team_name']} → {updated['score']} punti\n\nℹ️ Evento marcato TEST e azzerabile dal pannello admin.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚽ SIMULA ALTRA OFFERTA", callback_data="league_admin_test_sim")],[InlineKeyboardButton("🏆 CLASSIFICA", callback_data="league_rank")]])
    )


# Ridefinizione finale del pannello admin con Modalità Test.
async def admin_club_menu(update, context):
    if not await verifica_admin(update): return
    q=update.callback_query; await q.answer()
    with connessione() as db:
        users=db.execute("SELECT COUNT(*) FROM league_users").fetchone()[0]
        teams=db.execute("SELECT COUNT(*) FROM league_teams WHERE season_code=? AND confirmed=1",(SEASON_CODE,)).fetchone()[0]
        events=db.execute("SELECT COUNT(*) FROM league_score_events WHERE season_code=?",(SEASON_CODE,)).fetchone()[0]
    test_on=test_mode_active()
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 GIOCATORI",callback_data="league_admin_users"),InlineKeyboardButton("🏆 CLASSIFICA",callback_data="league_rank")],
        [InlineKeyboardButton("📦 PRODOTTI",callback_data="league_admin_products"),InlineKeyboardButton("⚽ PUNTEGGI",callback_data="league_admin_scoring")],
        [InlineKeyboardButton("📜 EVENTI",callback_data="league_admin_events")],
        [InlineKeyboardButton("🔴 DISATTIVA TEST" if test_on else "🟢 ATTIVA TEST", callback_data="league_admin_test_toggle")],
        [InlineKeyboardButton("👤 APRI COME GIOCATORE", callback_data="league_admin_test_player"), InlineKeyboardButton("⚽ SIMULA OFFERTA", callback_data="league_admin_test_sim")],
        [InlineKeyboardButton("♻️ RESET MIA SQUADRA TEST", callback_data="league_admin_test_reset")],
        [InlineKeyboardButton("⬅️ MENU PRINCIPALE",callback_data="menu_admin")],
    ])
    extra=countdown_text() if stato_stagione()=="PRESEASON" else ""
    await q.message.reply_text(
        f"⚙️ GESTIONE BESTPRICE LEAGUE\n\n📅 {SEASON_NAME}\n🟢 Stato reale: {stato_stagione()}\n"
        f"🧪 Test admin: {'ATTIVO' if test_on else 'DISATTIVATO'}\n👥 Giocatori: {users}\n⚽ Squadre confermate: {teams}\n📜 Eventi punti: {events}\n\n{extra}",
        reply_markup=kb,
    )
