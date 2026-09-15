import os
import asyncio
import sqlite3
import html
import json
import re
import random
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import deque

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from amazon_client import get_items, search_items

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CLUB / PUNTI
# =========================================================

from club import (
    inizializza_database,
    registra_utente,
    menu_club,
    mostra_punti,
    invita_amici,
    mostra_premi,
    richiedi_premio,
    gestisci_premio_admin,
    club_home,

    admin_club_menu,
    admin_club_utenti,
    admin_club_utente,
    admin_modifica_punti,
    admin_storico_utente,
    admin_movimenti,
    admin_inviti,
    admin_premi,
)


# =========================================================
# CONFIGURAZIONE
# =========================================================

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHAT_ID"]
CASA_CHANNEL_ID = os.environ.get("TELEGRAM_CHAT_ID_CASA", "@BestPrice24hCasa")
CASA_CHANNEL_URL = "https://t.me/BestPrice24hCasa"
TECH_CHANNEL_URL = "https://t.me/bestprice_2026"
TECH_CATEGORIE = {"elettronica", "informatica", "smartphone", "tvaudio", "gaming"}
CASA_CATEGORIE = {
    "casa", "elettrodomestici", "faidate", "giardino", "arredamento",
    "illuminazione",
}
ADMIN_ID = os.environ.get("ADMIN_TELEGRAM_ID")
DB_PATH = os.environ.get("CLUB_DB_PATH", "club.db")
ROMA_TZ = ZoneInfo("Europe/Rome")
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "bestprice24h_logo.png"
AMAZON_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "amazon_logo.png"
FONT_BOLD_PATH = Path(__file__).resolve().parent / "assets" / "DejaVuSans-Bold.ttf"
RACCOLTA_CASA_LOCK = asyncio.Lock()
RACCOLTA_TECH_LOCK = asyncio.Lock()
TIKTOK_LOCK = asyncio.Lock()
BUFFER_API_URL = "https://api.buffer.com"
TIKTOK_MEDIA_DIR = Path(
    os.environ.get(
        "TIKTOK_MEDIA_DIR",
        str(Path(DB_PATH).resolve().parent / "tiktok_media"),
    )
)


def canale_pubblicazione_per_categoria(categoria):
    """Instrada le categorie Casa sul relativo canale; le altre restano su TECH."""
    return CASA_CHANNEL_ID if categoria in CASA_CATEGORIE else CHANNEL_ID

(
    AUTO_INTERVALLO,
    AUTO_FASCIA,
    FILTRO_MARCHIO_AGGIUNGI,
    FILTRO_MARCHIO_RIMUOVI,
    FILTRO_PAROLA_AGGIUNGI,
    FILTRO_PAROLA_RIMUOVI,
    PRIORITA_AGGIUNGI,
    PRIORITA_RIMUOVI,
    PRIORITA_ACCESSORIO_AGGIUNGI,
    PRIORITA_ACCESSORIO_RIMUOVI,
    ARCHIVIO_RICERCA,
) = range(300, 311)

AUTO_CATEGORIE = {
    "elettronica": ("📱 Elettronica", ["offerte elettronica", "cuffie bluetooth", "dispositivi smart home"]),
    "informatica": ("💻 Informatica", ["offerte informatica", "accessori PC", "computer e tablet"]),
    "smartphone": ("📲 Smartphone", ["smartphone in offerta", "accessori smartphone", "caricabatterie powerbank"]),
    "tvaudio": ("📺 TV e audio", ["smart TV in offerta", "soundbar altoparlanti", "cuffie auricolari"]),
    "gaming": ("🎮 Gaming", ["offerte gaming", "accessori gaming", "videogiochi e console"]),
    "casa": ("🏠 Casa e cucina", ["offerte casa e cucina", "accessori cucina", "pulizia casa"]),
    "elettrodomestici": ("🔌 Elettrodomestici", ["piccoli elettrodomestici", "elettrodomestici cucina", "aspirapolvere in offerta"]),
    "persona": ("🧴 Cura personale", ["cura della persona", "rasoi elettrici", "asciugacapelli piastre"]),
    "bellezza": ("💄 Bellezza", ["prodotti bellezza", "skincare in offerta", "profumi e cosmetici"]),
    "sport": ("🏋️ Sport", ["offerte sport fitness", "attrezzatura sportiva", "abbigliamento sportivo"]),
    "faidate": ("🛠 Fai da te", ["offerte fai da te", "utensili elettrici", "attrezzi bricolage"]),
    "giardino": ("🌿 Giardino", ["offerte giardino", "attrezzi giardinaggio", "arredo esterno"]),
    "arredamento": ("🛋 Arredamento", ["offerte arredamento casa", "mobili salvaspazio", "organizzazione casa"]),
    "illuminazione": ("💡 Illuminazione", ["offerte illuminazione", "lampade led casa", "illuminazione smart"]),
    "giocattoli": ("🧸 Giochi e giocattoli", ["giocattoli in offerta", "giochi da tavolo", "LEGO in offerta"]),
}

AUTO_HASHTAG = {
    "elettronica": "#Elettronica",
    "informatica": "#Informatica",
    "smartphone": "#Smartphone",
    "tvaudio": "#TVeAudio",
    "casa": "#CasaECucina",
    "gaming": "#Gaming",
    "elettrodomestici": "#Elettrodomestici",
    "sport": "#Sport",
    "persona": "#CuraPersonale",
    "bellezza": "#Bellezza",
    "faidate": "#FaiDaTe",
    "giardino": "#Giardino",
    "arredamento": "#Arredamento",
    "illuminazione": "#Illuminazione",
    "giocattoli": "#GiochiEGiocattoli",
}

# Raccolte economiche pubblicate esclusivamente nel canale CASA. Ogni tema
# mantiene ricerche e parole di pertinenza proprie, evitando raccolte casuali.
RACCOLTE_CASA_TEMI = {
    "bagno": {
        "etichetta": "🛁 BAGNO",
        "titolo": "PICCOLI AFFARI PER IL BAGNO",
        "termini": ("accessori bagno offerta", "organizer bagno", "prodotti bagno casa"),
        "parole": {"bagno", "doccia", "sapone", "spazzolino", "wc", "asciugamano", "portaoggetti"},
    },
    "cucina": {
        "etichetta": "🍳 CUCINA",
        "titolo": "PICCOLI AFFARI PER LA CUCINA",
        "termini": ("accessori cucina offerta", "utensili cucina", "contenitori cucina"),
        "parole": {"cucina", "utensile", "contenitore", "spatola", "mestolo", "tagliere", "barattolo"},
    },
    "pulizia": {
        "etichetta": "🧽 PULIZIA",
        "titolo": "PICCOLI AFFARI PER LA PULIZIA",
        "termini": ("prodotti pulizia casa offerta", "panni spugne pulizia", "detergenti casa offerta"),
        "parole": {"pulizia", "detergente", "spugna", "panno", "sacchetti", "mocio", "scopa"},
    },
    "organizzazione": {
        "etichetta": "🧺 ORGANIZZAZIONE",
        "titolo": "PICCOLI AFFARI SALVASPAZIO",
        "termini": ("organizer casa offerta", "accessori salvaspazio", "scatole organizzazione casa"),
        "parole": {"organizer", "organizzazione", "salvaspazio", "scatola", "cassetto", "armadio", "contenitore"},
    },
    "dispensa": {
        "etichetta": "🍝 DISPENSA",
        "titolo": "OFFERTE PER LA DISPENSA",
        "termini": ("pasta confezione multipla offerta", "riso pacco convenienza", "caffè offerta confezione"),
        "parole": {"pasta", "riso", "caffè", "tonno", "conserve", "dispensa", "confezione"},
    },
    "faidate": {
        "etichetta": "🔧 PICCOLO FAI DA TE",
        "titolo": "PICCOLI AFFARI FAI DA TE",
        "termini": ("piccoli accessori fai da te", "minuteria bricolage offerta", "nastri punte utensili offerta"),
        "parole": {"fai da te", "bricolage", "nastro", "punta", "vite", "gancio", "utensile"},
    },
}

MARCHI_RACCOLTE_CASA = {
    "amazon basics", "ariel", "barilla", "bialetti", "brabantia", "caffè borbone",
    "cif", "dash", "finish", "folletto", "lavazza", "mastro lindo", "nivea",
    "rio mare", "scotti", "scottex", "tescoma", "vileda", "wpro",
}


# Raccolte multiple dedicate al canale TECH.
RACCOLTE_TECH_TEMI = {
    "smartphone": {
        "etichetta": "📱 SMARTPHONE",
        "titolo": "SCELTE TECH: SMARTPHONE E ACCESSORI",
        "termini": (
            "smartphone in offerta",
            "accessori smartphone di marca",
            "caricabatterie powerbank in offerta",
        ),
        "parole": {
            "smartphone", "telefono", "iphone", "galaxy", "pixel",
            "caricatore", "powerbank", "magsafe",
        },
    },
    "informatica": {
        "etichetta": "💻 INFORMATICA",
        "titolo": "SCELTE TECH: INFORMATICA",
        "termini": (
            "accessori PC in offerta",
            "SSD mouse tastiera in offerta",
            "notebook tablet in offerta",
        ),
        "parole": {
            "computer", "notebook", "tablet", "ssd", "mouse",
            "tastiera", "monitor", "router", "stampante",
        },
    },
    "audio": {
        "etichetta": "🎧 AUDIO E TV",
        "titolo": "SCELTE TECH: AUDIO E TV",
        "termini": (
            "cuffie bluetooth in offerta",
            "speaker soundbar in offerta",
            "TV audio in offerta",
        ),
        "parole": {
            "cuffie", "auricolari", "speaker", "soundbar",
            "televisore", "tv", "audio", "bluetooth",
        },
    },
    "gaming": {
        "etichetta": "🎮 GAMING",
        "titolo": "SCELTE TECH: GAMING",
        "termini": (
            "accessori gaming in offerta",
            "controller gaming in offerta",
            "videogiochi console in offerta",
        ),
        "parole": {
            "gaming", "controller", "console", "playstation",
            "xbox", "nintendo", "videogioco", "cuffie",
        },
    },
    "smarthome": {
        "etichetta": "🏠 SMART HOME",
        "titolo": "SCELTE TECH: SMART HOME",
        "termini": (
            "smart home in offerta",
            "prese lampadine smart in offerta",
            "telecamere sicurezza smart in offerta",
        ),
        "parole": {
            "smart home", "presa smart", "lampadina", "telecamera",
            "videocitofono", "sensore", "echo", "ring", "tapo",
        },
    },
}

MARCHI_RACCOLTE_TECH = {
    "amazon", "amazon basics", "anker", "apple", "asus", "belkin", "bose",
    "canon", "corsair", "crucial", "dell", "dji", "eufy", "garmin", "google",
    "gopro", "honor", "hp", "huawei", "hyperx", "intel", "jabra", "jbl",
    "kingston", "lenovo", "lg", "logitech", "meta", "microsoft", "motorola",
    "msi", "netgear", "nintendo", "nothing", "oneplus", "oppo", "panasonic",
    "philips", "playstation", "razer", "realme", "ring", "samsung", "sandisk",
    "seagate", "sennheiser", "sony", "soundcore", "steelseries", "tapo",
    "tcl", "tp-link", "ugreen", "western digital", "xiaomi", "xbox",
}

MARCHI_AUTORIZZATI = {
    "elettronica": {
        "amazon", "amazon basics", "anker", "apple", "baseus", "belkin", "bose",
        "canon", "dji", "eufy", "fujifilm", "garmin", "google", "gopro", "hama",
        "huawei", "jabra", "jbl", "kodak", "lg", "logitech", "motorola", "netgear",
        "nikon", "nokia", "nothing", "oneplus", "oppo", "panasonic", "philips",
        "polaroid", "realme", "ring", "samsung", "sennheiser", "sony", "soundcore",
        "spigen", "tapo", "tp-link", "ugreen", "xiaomi",
    },
    "informatica": {
        "aoc", "acer", "amd", "apple", "asrock", "asus", "benq", "brother",
        "canon", "corsair", "creative", "crucial", "dell", "epson", "gigabyte",
        "hp", "huawei", "hyperx", "intel", "keychron", "kingston", "lenovo",
        "lexar", "lg", "logitech", "microsoft", "msi", "netgear", "nvidia",
        "nzxt", "pny", "razer", "samsung", "sandisk", "seagate", "steelseries",
        "synology", "tp-link", "trust", "ugreen", "western digital", "wd", "zotac",
    },
    "smartphone": {
        "amazon", "anker", "apple", "baseus", "belkin", "blackview", "crosscall",
        "esr", "fairphone", "google", "honor", "huawei", "motorola", "nokia",
        "nothing", "oneplus", "oppo", "otterbox", "realme", "samsung", "spigen",
        "tcl", "ugreen", "vivo", "xiaomi", "zte",
    },
    "tvaudio": {
        "amazon", "amazon fire tv", "audio-technica", "bang & olufsen", "beats",
        "bose", "denon", "edifier", "grundig", "harman kardon", "hisense", "jabra",
        "jbl", "klipsch", "lg", "loewe", "marshall", "panasonic", "philips",
        "pioneer", "polk audio", "samsung", "sennheiser", "sharp", "skullcandy",
        "sonos", "sony", "soundcore", "tcl", "technics", "toshiba", "yamaha",
    },
    "gaming": {
        "8bitdo", "acer", "amd", "asus", "corsair", "elgato", "gamesir", "gigabyte",
        "hori", "hyperx", "lenovo", "logitech", "meta", "microsoft", "msi", "nacon",
        "nintendo", "nvidia", "oculus", "playstation", "razer", "roccat", "samsung",
        "seagate", "sony", "steelseries", "thrustmaster", "turtle beach", "xbox",
    },
    "casa": {
        "alessi", "amazon basics", "amefa", "ballarini", "bialetti", "bormioli rocco",
        "brabantia", "brita", "curver", "fiskars", "guzzini", "ikea", "joseph joseph",
        "kasanova", "keter", "lagostina", "le creuset", "leifheit", "luminarc",
        "moneta", "pedrini", "pyrex", "rcr", "risoli", "scotch-brite", "simplehuman",
        "tefal", "tescoma", "vileda", "wmf", "zwilling",
    },
    "elettrodomestici": {
        "aeg", "aeroccino", "ariete", "beko", "bialetti", "bissell", "black+decker",
        "bosch", "braun", "candy", "cecotec", "de'longhi", "delonghi", "dreame",
        "dyson", "electrolux", "gaggia", "haier", "hisense", "hoover", "hotpoint",
        "imetec", "indesit", "irobot", "karcher", "kenwood", "kitchenaid", "krups",
        "lavazza", "lg", "miele", "moulinex", "nespresso", "ninja", "panasonic",
        "philips", "roborock", "rowenta", "samsung", "saeco", "shark", "smeg",
        "tefal", "whirlpool", "xiaomi",
    },
    "persona": {
        "babyliss", "braun", "colgate", "dyson", "foreo", "ghd", "gillette",
        "imetec", "laica", "medisana", "oral-b", "panasonic", "philips",
        "remington", "rowenta", "sensodyne", "sonicare", "veet", "waterpik",
    },
    "bellezza": {
        "avene", "bioderma", "biotherm", "cerave", "clarins", "clinique", "collistar",
        "eucerin", "garnier", "kiehl's", "l'oreal paris", "la roche-posay", "lancôme",
        "mac", "max factor", "maybelline", "nivea", "olaplex", "ordinary", "revlon",
        "foreo", "rimmel", "shiseido", "the ordinary", "vichy", "wella",
    },
    "sport": {
        "adidas", "arena", "asics", "brooks", "callaway", "campagnolo", "castelli",
        "continental", "domyos", "dunlop", "fitbit", "garmin", "head", "joma",
        "kappa", "kiprun", "mizuno", "new balance", "nike", "oakley", "polar",
        "puma", "quechua", "reebok", "salomon", "shimano", "speedo", "suunto",
        "the north face", "under armour", "wilson", "yonex",
    },
    "faidate": {
        "3m", "abb", "bahco", "beta", "black+decker", "bosch", "bostik", "dewalt",
        "dremel", "einhell", "facom", "fischer", "hilti", "karcher", "knipex", "loctite",
        "makita", "metabo", "milwaukee", "pattex", "ryobi", "stanley", "tacklife",
        "usag", "wera", "wiha", "wolfcraft", "worx",
    },
    "giardino": {
        "black+decker", "bosch", "einhell", "fiskars", "gardena", "greenworks",
        "husqvarna", "karcher", "makita", "ryobi", "stihl", "weber", "worx",
    },
    "arredamento": {
        "amazon basics", "brabantia", "curver", "emuca", "ikea", "keter",
        "songmics", "tontarelli", "vasagle", "wenko", "yamazaki", "zinus",
    },
    "illuminazione": {
        "amazon basics", "artemide", "eglo", "govee", "ledvance", "nanoleaf",
        "osram", "paulmann", "philips", "philips hue", "tapo", "xiaomi",
    },
    "giocattoli": {
        "asmodee", "barbie", "bruder", "chicco", "clementoni", "crayola", "disney",
        "fisher-price", "funko", "geomag", "giochi preziosi", "hasbro", "hot wheels",
        "lego", "lisciani", "mattel", "mga entertainment", "nerf", "nintendo", "pinypon",
        "play-doh", "playmobil", "ravensburger", "schleich", "spin master", "vtech",
    },
}

PAROLE_INDESIDERATE = {
    "generico", "senza marca", "confezione vuota", "solo ricambio",
    "adesivo decorativo", "guscio universale", "compatibile universale",
}

PAROLE_CATEGORIA = {
    "elettronica": {"cuffie", "auricolari", "bluetooth", "smart", "elettronica", "speaker", "caricatore"},
    "informatica": {"pc", "computer", "notebook", "tablet", "ssd", "mouse", "tastiera", "stampante", "router"},
    "smartphone": {"smartphone", "telefono", "iphone", "galaxy", "pixel", "powerbank", "caricabatterie"},
    "tvaudio": {"tv", "televisore", "soundbar", "cuffie", "auricolari", "speaker", "audio"},
    "gaming": {"gaming", "videogioco", "console", "controller", "playstation", "xbox", "nintendo"},
    "casa": {"casa", "cucina", "pentola", "padella", "pulizia", "contenitore", "organizer"},
    "elettrodomestici": {"aspirapolvere", "friggitrice", "robot", "frullatore", "macchina", "forno", "elettrodomestico"},
    "persona": {"rasoio", "spazzolino", "asciugacapelli", "piastra", "epilatore", "cura"},
    "bellezza": {"bellezza", "crema", "profumo", "cosmetico", "skincare", "makeup", "shampoo"},
    "sport": {"sport", "fitness", "palestra", "running", "scarpe", "allenamento", "smartwatch"},
    "faidate": {"trapano", "avvitatore", "utensile", "attrezzo", "bricolage", "fai da te"},
    "giardino": {"giardino", "giardinaggio", "tagliaerba", "decespugliatore", "irrigazione", "barbecue", "esterno"},
    "arredamento": {"arredamento", "mobile", "scaffale", "scrivania", "sedia", "armadio", "comodino"},
    "illuminazione": {"lampada", "lampadina", "led", "plafoniera", "applique", "illuminazione", "luce"},
    "giocattoli": {"gioco", "giocattolo", "lego", "bambini", "bambino", "bambina", "puzzle"},
}

# parola da cercare, marchio obbligatorio, bonus di priorità
PRODOTTI_PRIORITARI_DEFAULT = {
    "elettronica": [
        ("airpods", "apple", 5), ("gopro", "gopro", 4),
        ("fire tv", "amazon", 5), ("kindle", "amazon", 4),
        ("echo", "amazon", 4), ("ring", "ring", 4),
        ("dji", "dji", 5), ("garmin", "garmin", 4),
        ("quietcomfort", "bose", 5), ("wh-1000xm", "sony", 5),
        ("jbl charge", "jbl", 4),
    ],
    "informatica": [
        ("macbook", "apple", 5), ("ipad", "apple", 5),
        ("surface", "microsoft", 4), ("galaxy book", "samsung", 4),
        ("ssd", "samsung", 3), ("thinkpad", "lenovo", 4),
        ("zenbook", "asus", 4), ("xps", "dell", 4),
        ("logitech mx", "logitech", 4), ("ssd", "sandisk", 3),
        ("deco", "tp-link", 4),
    ],
    "smartphone": [
        ("iphone", "apple", 5), ("galaxy s", "samsung", 4),
        ("galaxy z", "samsung", 4), ("pixel", "google", 4),
        ("xiaomi", "xiaomi", 3), ("razr", "motorola", 3),
        ("galaxy a", "samsung", 3), ("redmi note", "xiaomi", 4),
        ("oneplus", "oneplus", 4), ("honor magic", "honor", 4),
        ("oppo find", "oppo", 4), ("oppo reno", "oppo", 3),
    ],
    "tvaudio": [
        ("oled", "lg", 5), ("oled", "sony", 5),
        ("oled", "samsung", 5), ("soundbar", "bose", 4),
        ("soundbar", "sonos", 4), ("bravia", "sony", 4),
        ("qled", "samsung", 4), ("uled", "hisense", 4),
        ("soundbar", "jbl", 3), ("marshall", "marshall", 4),
        ("wh-1000xm", "sony", 5), ("galaxy buds", "samsung", 4),
    ],
    "gaming": [
        ("playstation 5", "sony", 5), ("ps5", "sony", 5),
        ("xbox series", "microsoft", 5), ("nintendo switch", "nintendo", 5),
        ("rog ally", "asus", 4),
        ("playstation portal", "sony", 5), ("meta quest", "meta", 5),
        ("logitech g", "logitech", 4), ("razer", "razer", 4),
        ("steelseries", "steelseries", 4), ("corsair gaming", "corsair", 4),
    ],
    "casa": [
        ("le creuset", "le creuset", 4), ("bialetti", "bialetti", 3),
        ("lagostina", "lagostina", 3), ("tefal", "tefal", 3),
        ("pyrex", "pyrex", 3), ("brita", "brita", 4),
        ("brabantia", "brabantia", 3), ("joseph joseph", "joseph joseph", 4),
        ("tescoma", "tescoma", 3), ("wmf", "wmf", 4),
    ],
    "elettrodomestici": [
        ("dyson", "dyson", 5), ("roomba", "irobot", 5),
        ("roborock", "roborock", 4), ("friggitrice", "ninja", 4),
        ("nespresso", "nespresso", 4), ("dreame", "dreame", 4),
        ("airfryer", "philips", 4), ("de'longhi", "delonghi", 4),
        ("kitchenaid", "kitchenaid", 4), ("moulinex", "moulinex", 3),
        ("rowenta", "rowenta", 3),
    ],
    "persona": [
        ("series 9", "braun", 4), ("sonicare", "philips", 4),
        ("airwrap", "dyson", 5), ("supersonic", "dyson", 5),
    ],
    "bellezza": [
        ("cerave", "cerave", 3), ("la roche-posay", "la roche-posay", 3),
        ("olaplex", "olaplex", 4), ("foreo", "foreo", 4),
    ],
    "sport": [
        ("forerunner", "garmin", 5), ("fenix", "garmin", 5),
        ("apple watch", "apple", 5), ("polar", "polar", 4),
        ("suunto", "suunto", 4),
    ],
    "faidate": [
        ("professional", "bosch", 4), ("dewalt", "dewalt", 4),
        ("makita", "makita", 4), ("milwaukee", "milwaukee", 4),
        ("black+decker", "black+decker", 3), ("einhell", "einhell", 3),
        ("dremel", "dremel", 4), ("stanley", "stanley", 3),
        ("karcher", "karcher", 4), ("fischer", "fischer", 3),
    ],
    "giardino": [
        ("gardena", "gardena", 4), ("fiskars", "fiskars", 3),
        ("tagliaerba", "bosch", 4), ("barbecue", "weber", 4),
        ("karcher", "karcher", 4), ("makita", "makita", 4),
        ("ryobi", "ryobi", 3), ("einhell", "einhell", 3),
        ("worx", "worx", 3),
    ],
    "arredamento": [
        ("songmics", "songmics", 3), ("vasagle", "vasagle", 3),
        ("keter", "keter", 3), ("zinus", "zinus", 3),
        ("brabantia", "brabantia", 3), ("curver", "curver", 3),
        ("wenko", "wenko", 3), ("yamazaki", "yamazaki", 4),
        ("simplehuman", "simplehuman", 4),
    ],
    "illuminazione": [
        ("hue", "philips hue", 5), ("govee", "govee", 4),
        ("ledvance", "ledvance", 3), ("tapo", "tapo", 3),
        ("nanoleaf", "nanoleaf", 4), ("osram", "osram", 3),
        ("artemide", "artemide", 4), ("eglo", "eglo", 3),
        ("smart light", "xiaomi", 3),
    ],
    "giocattoli": [
        ("lego", "lego", 5), ("barbie", "mattel", 4),
        ("hot wheels", "mattel", 4), ("playmobil", "playmobil", 4),
    ],
}

PAROLE_ACCESSORI_PRIORITA_DEFAULT = {
    "accessorio", "adattatore", "cavo", "caricatore", "case", "compatibile",
    "cover", "cinturino", "custodia", "pellicola", "protezione", "ricambio",
    "supporto", "vetro temperato",
}

# Alcuni prodotti arrivano dalle API con il marchio commerciale invece
# della società proprietaria (es. PlayStation invece di Sony).
MARCHI_ALIAS_PRIORITA = {
    "sony": {"sony", "playstation"},
    "playstation": {"sony", "playstation"},
    "microsoft": {"microsoft", "xbox"},
    "xbox": {"microsoft", "xbox"},
    "meta": {"meta", "oculus"},
    "oculus": {"meta", "oculus"},
    "google": {"google", "fitbit", "nest"},
    "amazon": {"amazon", "kindle", "fire tv", "ring", "eero"},
}


(
    LINK,
    NOME,
    PREZZO,
    VECCHIO_PREZZO,
    CONFERMA,
    RAPIDO,
    DATI_AUTOMATICI,
    PROGRAMMA_DATA,
    PROGRAMMA_ORA,
    CONFERMA_ORARIO,
) = range(10)

(
    PROG_SELEZIONE,
    PROG_GESTIONE,
    PROG_MODIFICA_MENU,
    PROG_EDIT_NOME,
    PROG_EDIT_PREZZO,
    PROG_EDIT_VECCHIO,
    PROG_EDIT_LINK,
    PROG_EDIT_DATA_ORA,
) = range(100, 108)

(
    FOTO_SCELTA,
    FOTO_ATTESA,
    PROG_IMMAGINE_MENU,
    PROG_IMMAGINE_ATTESA,
) = range(200, 204)


ultime_offerte = deque(maxlen=10)



# =========================================================
# RECAP GIORNALIERO OFFERTE - ORE 22:01
# =========================================================

def inizializza_recap():

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recap_offerte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            link TEXT NOT NULL,
            prezzo TEXT,
            vecchio_prezzo TEXT,
            pubblicata_il TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recap_giorni (
            data TEXT PRIMARY KEY,
            inviato_il TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recap_giorni_canali (
            data TEXT NOT NULL,
            canale TEXT NOT NULL,
            inviato_il TEXT NOT NULL,
            PRIMARY KEY (data, canale)
        )
    """)
    # Conserva lo stato dei vecchi recap TECH, evitando di reinviarli dopo
    # l'aggiornamento. CASA mantiene invece un proprio stato indipendente.
    cur.execute("""
        INSERT OR IGNORE INTO recap_giorni_canali (data, canale, inviato_il)
        SELECT data, 'tech', inviato_il FROM recap_giorni
    """)

    # Campi aggiuntivi per poter reinviare rapidamente i post storici.
    cur.execute("PRAGMA table_info(recap_offerte)")
    colonne_recap = {riga[1] for riga in cur.fetchall()}

    if "messaggio" not in colonne_recap:
        cur.execute("ALTER TABLE recap_offerte ADD COLUMN messaggio TEXT")

    if "foto_file_id" not in colonne_recap:
        cur.execute("ALTER TABLE recap_offerte ADD COLUMN foto_file_id TEXT")

    if "template" not in colonne_recap:
        cur.execute("ALTER TABLE recap_offerte ADD COLUMN template TEXT DEFAULT 'pulito'")

    nuove_colonne_recap = {
        "asin": "TEXT",
        "categoria": "TEXT DEFAULT 'manuale'",
        "telegram_chat_id": "TEXT",
        "origine": "TEXT DEFAULT 'manuale'",
        "sconto": "INTEGER DEFAULT 0",
        "telegram_message_id": "INTEGER",
        "stato": "TEXT DEFAULT 'pubblicata'",
    }
    cur.execute("PRAGMA table_info(recap_offerte)")
    colonne_recap = {riga[1] for riga in cur.fetchall()}
    for colonna, definizione in nuove_colonne_recap.items():
        if colonna not in colonne_recap:
            cur.execute(f"ALTER TABLE recap_offerte ADD COLUMN {colonna} {definizione}")
    # Le pubblicazioni precedenti alla creazione del canale CASA erano TECH.
    cur.execute(
        "UPDATE recap_offerte SET telegram_chat_id=? WHERE telegram_chat_id IS NULL OR telegram_chat_id=''",
        (CHANNEL_ID,),
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recap_data ON recap_offerte(pubblicata_il DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recap_canale ON recap_offerte(telegram_chat_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recap_asin ON recap_offerte(asin)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_recap_origine ON recap_offerte(origine)")

    db.commit()
    db.close()


def salva_offerta_recap(
    nome,
    link,
    prezzo,
    vecchio_prezzo="NO",
    messaggio=None,
    foto_file_id=None,
    template="pulito",
    asin=None,
    categoria="manuale",
    telegram_chat_id=None,
    origine="manuale",
    sconto=0,
    telegram_message_id=None,
    stato="pubblicata",
):

    if not nome or not link:
        return

    adesso = datetime.now(ROMA_TZ)

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    asin = asin or risolvi_asin_da_link(link)
    cur.execute("""
        INSERT INTO recap_offerte (
            nome,
            link,
            prezzo,
            vecchio_prezzo,
            pubblicata_il,
            messaggio,
            foto_file_id,
            template, asin, categoria, telegram_chat_id, origine,
            sconto, telegram_message_id, stato
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nome,
        link,
        prezzo or "",
        vecchio_prezzo or "NO",
        adesso.isoformat(timespec="seconds"),
        messaggio,
        foto_file_id,
        template or "pulito",
        asin,
        categoria or "manuale",
        telegram_chat_id or CHANNEL_ID,
        origine or "manuale",
        int(sconto or 0),
        telegram_message_id,
        stato or "pubblicata",
    ))

    db.commit()
    db.close()


def offerte_pubblicate_per_web(limit=60, base_url=""):
    """Restituisce le stesse offerte già pubblicate su Telegram."""
    limite = max(1, min(int(limit or 60), 100))
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        righe = db.execute(
            """
            SELECT id, nome, link, prezzo, vecchio_prezzo, pubblicata_il,
                   asin, categoria, telegram_chat_id, origine, sconto,
                   telegram_message_id, foto_file_id
            FROM recap_offerte
            WHERE stato='pubblicata' AND link IS NOT NULL AND link<>''
            ORDER BY pubblicata_il DESC, id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
    finally:
        db.close()

    offerte = []
    for riga in righe:
        chat_id = str(riga["telegram_chat_id"] or CHANNEL_ID)
        canale = "casa" if chat_id.lower() == str(CASA_CHANNEL_ID).lower() else "tech"
        username = chat_id[1:] if chat_id.startswith("@") else ""
        message_id = riga["telegram_message_id"]
        telegram_url = (
            f"https://t.me/{username}/{message_id}"
            if username and message_id
            else None
        )
        asin = str(riga["asin"] or "").strip().upper()
        offerte.append({
            "id": riga["id"],
            "nome": riga["nome"],
            "link": riga["link"],
            "prezzo": riga["prezzo"] or "",
            "vecchio_prezzo": riga["vecchio_prezzo"] or "",
            "pubblicata_il": riga["pubblicata_il"],
            "asin": asin,
            "categoria": riga["categoria"] or "altro",
            "canale": canale,
            "origine": riga["origine"] or "manuale",
            "sconto": int(riga["sconto"] or 0),
            "telegram_url": telegram_url,
            "immagine": (
                f"{base_url}/api/offerte/{riga['id']}/immagine"
                if base_url and riga["foto_file_id"] else None
            ),
        })
    return offerte


def foto_offerta_per_web(offerta_id):
    db = sqlite3.connect(DB_PATH)
    try:
        riga = db.execute(
            "SELECT foto_file_id FROM recap_offerte WHERE id=? AND stato='pubblicata'",
            (int(offerta_id),),
        ).fetchone()
    finally:
        db.close()
    if not riga or not riga[0]:
        return None, None

    riferimento = str(riga[0]).strip()
    if riferimento.startswith(("http://", "https://")):
        risposta = requests.get(riferimento, timeout=15)
    else:
        info = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getFile",
            params={"file_id": riferimento},
            timeout=10,
        )
        info.raise_for_status()
        percorso = info.json().get("result", {}).get("file_path")
        if not percorso:
            return None, None
        risposta = requests.get(
            f"https://api.telegram.org/file/bot{TOKEN}/{percorso}",
            timeout=15,
        )
    risposta.raise_for_status()
    contenuto = risposta.content
    if not contenuto or len(contenuto) > 10 * 1024 * 1024:
        return None, None
    tipo = risposta.headers.get("Content-Type", "image/jpeg").split(";", 1)[0]
    if not tipo.startswith("image/"):
        tipo = "image/jpeg"
    return contenuto, tipo


class OfferteWebHandler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200):
        corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "public, max-age=30")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        percorso = self.path.split("?", 1)[0].rstrip("/") or "/"
        if percorso == "/health":
            self._json({"ok": True})
            return
        if percorso == "/api/offerte":
            try:
                dominio = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
                if dominio:
                    base_url = f"https://{dominio.strip().strip('/')}"
                else:
                    host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
                    host = host if re.fullmatch(r"[A-Za-z0-9.:-]+", host) else ""
                    protocollo = self.headers.get("X-Forwarded-Proto", "https")
                    protocollo = protocollo if protocollo in {"http", "https"} else "https"
                    base_url = f"{protocollo}://{host}" if host else ""
                self._json({
                    "offerte": offerte_pubblicate_per_web(base_url=base_url),
                    "aggiornato_il": datetime.now(ROMA_TZ).isoformat(timespec="seconds"),
                })
            except Exception as exc:
                print(f"Errore API offerte web: {exc}")
                self._json({"offerte": [], "errore": "temporaneo"}, status=500)
            return
        immagine = re.fullmatch(r"/api/offerte/(\d+)/immagine", percorso)
        if immagine:
            try:
                contenuto, tipo = foto_offerta_per_web(immagine.group(1))
                if not contenuto:
                    self._json({"errore": "immagine non disponibile"}, status=404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(contenuto)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(contenuto)
            except Exception as exc:
                print(f"Errore immagine offerta web: {exc}")
                self._json({"errore": "immagine non disponibile"}, status=404)
            return
        media_tiktok = re.fullmatch(
            r"/media/tiktok/(tiktok_[0-9]{8}_[0-9]{4}_[0-9]+\.jpg)",
            percorso,
        )
        if media_tiktok:
            file_media = TIKTOK_MEDIA_DIR / media_tiktok.group(1)
            try:
                contenuto = file_media.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(contenuto)))
                self.send_header("Cache-Control", "public, max-age=604800")
                self.end_headers()
                self.wfile.write(contenuto)
            except (OSError, ValueError):
                self._json({"errore": "immagine non disponibile"}, status=404)
            return
        self._json({"errore": "non trovato"}, status=404)

    def log_message(self, formato, *argomenti):
        return


def avvia_api_offerte_web():
    porta = os.environ.get("PORT")
    if not porta:
        print("🌐 API offerte web non avviata: variabile PORT assente")
        return
    server = ThreadingHTTPServer(("0.0.0.0", int(porta)), OfferteWebHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"🌐 API offerte web attiva sulla porta {porta}")


def inizializza_tiktok():
    """Prepara lo storico che impedisce doppi post TikTok nello stesso slot."""
    TIKTOK_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tiktok_pubblicazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_data TEXT NOT NULL,
            slot_ora TEXT NOT NULL,
            categoria TEXT,
            titolo TEXT,
            file_immagine TEXT,
            buffer_post_id TEXT,
            stato TEXT NOT NULL DEFAULT 'preparazione',
            tentativi INTEGER NOT NULL DEFAULT 0,
            errore TEXT,
            creato_il TEXT NOT NULL,
            aggiornato_il TEXT NOT NULL,
            UNIQUE(slot_data, slot_ora)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tiktok_pubblicazioni_prodotti (
            pubblicazione_id INTEGER NOT NULL,
            asin TEXT NOT NULL,
            usato_il TEXT NOT NULL,
            PRIMARY KEY (pubblicazione_id, asin),
            FOREIGN KEY (pubblicazione_id) REFERENCES tiktok_pubblicazioni(id)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_tiktok_prodotti_asin "
        "ON tiktok_pubblicazioni_prodotti(asin, usato_il)"
    )
    db.execute("CREATE TABLE IF NOT EXISTS tiktok_config (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL)")
    for chiave, valore in {
        "attiva": "1",
        "orari": os.environ.get("TIKTOK_POST_TIMES", "12:30,20:30"),
        "sconto": os.environ.get("TIKTOK_MIN_DISCOUNT", "20"),
    }.items():
        db.execute("INSERT OR IGNORE INTO tiktok_config VALUES (?, ?)", (chiave, valore))
    db.commit()
    db.close()


TIKTOK_STILI = (
    ("#F7FAFC", "#17212B", "#168AAD", "#FFFFFF"),
    ("#071426", "#FFFFFF", "#00A8FF", "#102A43"),
    ("#101010", "#F5D67B", "#C89B3C", "#1D1D1D"),
    ("#F20D18", "#FFFFFF", "#171717", "#FFFFFF"),
    ("#F5F5F5", "#222222", "#FF9900", "#FFFFFF"),
    ("#24113D", "#FFFFFF", "#D946EF", "#FFFFFF"),
    ("#063B2B", "#FFFFFF", "#10B981", "#FFFFFF"),
    ("#F5EEDF", "#181818", "#A64B2A", "#FFFFFF"),
    ("#FFD438", "#102A43", "#1D4ED8", "#FFFFFF"),
    ("#111827", "#E5E7EB", "#60A5FA", "#FFFFFF"),
)


def leggi_config_tiktok():
    with sqlite3.connect(DB_PATH) as db:
        return dict(db.execute("SELECT chiave, valore FROM tiktok_config"))


def salva_config_tiktok(chiave, valore):
    with sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT OR REPLACE INTO tiktok_config VALUES (?, ?)", (chiave, str(valore)))


async def gestisci_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    if query.data == "tiktok_test":
        return await testa_tiktok(update, context)
    await query.answer()
    azione = query.data
    config = leggi_config_tiktok()
    if azione == "tiktok_toggle":
        salva_config_tiktok("attiva", "0" if config["attiva"] == "1" else "1")
    elif azione.startswith("tiktok_times_"):
        orari = azione.removeprefix("tiktok_times_").split("_")
        salva_config_tiktok("orari", ",".join(x[:2] + ":" + x[2:] for x in orari))
    elif azione.startswith("tiktok_discount_"):
        salva_config_tiktok("sconto", azione.rsplit("_", 1)[1])
    ritorno = [InlineKeyboardButton("⬅️ TORNA A TIKTOK", callback_data="tiktok_menu")]
    if azione == "tiktok_times":
        return await query.edit_message_text(
            "🕒 DUE POST AL GIORNO — ORA ITALIANA\nScegli gli orari. I post già inviati a Buffer restano programmati.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(label, callback_data=data)] for label, data in [
                    ("11:30 / 19:30", "tiktok_times_1130_1930"),
                    ("12:30 / 20:30", "tiktok_times_1230_2030"),
                    ("13:00 / 21:00", "tiktok_times_1300_2100"),
                ]
            ] + [ritorno]),
        )
    if azione == "tiktok_discount":
        return await query.edit_message_text(
            "🎯 FILTRI TIKTOK\nModalità SELETTIVA: due prodotti TECH della stessa categoria.\nScegli lo sconto minimo:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{n}%", callback_data=f"tiktok_discount_{n}") for n in (10, 20, 30, 40)],
                ritorno,
            ]),
        )
    if azione == "tiktok_history":
        with sqlite3.connect(DB_PATH) as db:
            righe = db.execute(
                "SELECT slot_data, slot_ora, stato, titolo, errore FROM tiktok_pubblicazioni ORDER BY id DESC LIMIT 8"
            ).fetchall()
        testo = "📋 STORICO TIKTOK\nProgrammato = accettato da Buffer; controlla su Buffer l’esito finale.\n\n"
        testo += "\n\n".join(
            f"{data} {ora} · {stato}\n{titolo or ''}" + (f"\nErrore: {errore[:180]}" if errore else "")
            for data, ora, stato, titolo, errore in righe
        ) or "Nessun invio registrato."
        return await query.edit_message_text(testo, reply_markup=InlineKeyboardMarkup([ritorno]))
    config = leggi_config_tiktok()
    attiva = config["attiva"] == "1"
    operativo = _tiktok_configurato()
    testo = (
        "🎵 AUTOMAZIONE TIKTOK\n\n"
        f"Stato: {'🟢 ATTIVA' if attiva else '🔴 IN PAUSA'}\n"
        f"Invio: {'abilitato' if operativo else 'non abilitato (pausa o configurazione Railway)'}\n"
        f"Orari italiani: {' / '.join(_orari_tiktok())}\n"
        f"Sconto minimo: {config['sconto']}%\n"
        "Modalità: SELETTIVA · 2 prodotti TECH della stessa categoria\n\n"
        "La pausa ferma i prossimi invii. Un invio già in corso o già consegnato a Buffer va controllato su Buffer."
    )
    await query.edit_message_text(testo, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 METTI IN PAUSA" if attiva else "🟢 ATTIVA", callback_data="tiktok_toggle")],
        [InlineKeyboardButton("🧪 ANTEPRIMA COMPLETA", callback_data="tiktok_test")],
        [InlineKeyboardButton("🕒 ORARI", callback_data="tiktok_times"), InlineKeyboardButton("🎯 FILTRI", callback_data="tiktok_discount")],
        [InlineKeyboardButton("📋 STORICO E STATO", callback_data="tiktok_history")],
        [InlineKeyboardButton("APRI BUFFER", url="https://publish.buffer.com")],
        [InlineKeyboardButton("⬅️ MENU PRINCIPALE", callback_data="menu_admin")],
    ]))


def _orari_tiktok():
    valori = []
    for valore in leggi_config_tiktok()["orari"].split(","):
        valore = valore.strip()
        try:
            datetime.strptime(valore, "%H:%M")
        except ValueError:
            continue
        if valore not in valori:
            valori.append(valore)
    return valori[:2]


def _tiktok_configurato():
    attivo = os.environ.get("TIKTOK_AUTO_ENABLED", "1").strip().lower()
    return (
        attivo not in {"0", "false", "no", "off"}
        and leggi_config_tiktok()["attiva"] == "1"
        and bool(os.environ.get("BUFFER_API_KEY"))
        and bool(os.environ.get("BUFFER_TIKTOK_CHANNEL_ID"))
        and bool(os.environ.get("RAILWAY_PUBLIC_DOMAIN"))
    )


def _candidati_tiktok_per_categoria():
    """Raggruppa le migliori offerte già pubblicate nel canale TECH."""
    limite_giorni = max(1, int(os.environ.get("TIKTOK_CANDIDATE_DAYS", "7")))
    riuso_giorni = max(1, int(os.environ.get("TIKTOK_REUSE_DAYS", "14")))
    data_minima = (datetime.now(ROMA_TZ) - timedelta(days=limite_giorni)).isoformat(timespec="seconds")
    riuso_da = (datetime.now(ROMA_TZ) - timedelta(days=riuso_giorni)).isoformat(timespec="seconds")
    categorie = sorted(TECH_CATEGORIE)
    segnaposti = ",".join("?" for _ in categorie)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        righe = db.execute(
            f"""
            SELECT r.id, r.asin, r.nome, r.link, r.prezzo, r.vecchio_prezzo,
                   r.categoria, r.sconto, r.pubblicata_il
            FROM recap_offerte r
            WHERE r.stato='pubblicata'
              AND r.telegram_chat_id=?
              AND r.categoria IN ({segnaposti})
              AND r.asin IS NOT NULL AND r.asin<>''
              AND r.pubblicata_il>=?
              AND COALESCE(r.origine, 'manuale')<>'raccolta'
              AND NOT EXISTS (
                  SELECT 1 FROM tiktok_pubblicazioni_prodotti tp
                  WHERE tp.asin=r.asin AND tp.usato_il>=?
              )
            ORDER BY r.sconto DESC, r.pubblicata_il DESC, r.id DESC
            LIMIT 80
            """,
            [str(CHANNEL_ID), *categorie, data_minima, riuso_da],
        ).fetchall()
    finally:
        db.close()

    gruppi = {}
    asin_visti = set()
    for riga in righe:
        asin = str(riga["asin"] or "").upper()
        if not asin or asin in asin_visti:
            continue
        asin_visti.add(asin)
        gruppi.setdefault(riga["categoria"], []).append(dict(riga))
    gruppi = {categoria: prodotti for categoria, prodotti in gruppi.items() if len(prodotti) >= 2}
    return sorted(
        gruppi.items(),
        key=lambda elemento: sum(int(p.get("sconto") or 0) for p in elemento[1][:2]),
        reverse=True,
    )


async def seleziona_coppia_tiktok():
    minimo_sconto = max(0, int(leggi_config_tiktok()["sconto"]))
    for categoria, righe in _candidati_tiktok_per_categoria():
        righe = righe[:10]
        per_asin = {str(riga["asin"]).upper(): riga for riga in righe}
        configurazione = leggi_config_automatica("tech")
        snapshot_filtri = carica_snapshot_filtri(categoria, configurazione)
        try:
            items = await asyncio.to_thread(get_items, list(per_asin))
        except Exception as errore:
            print(f"Errore aggiornamento candidati TikTok ({categoria}): {errore}")
            continue
        prodotti = []
        for item in items:
            prodotto = estrai_prodotto_creators(item)
            if not prodotto or int(prodotto.get("sconto") or 0) < minimo_sconto:
                continue
            riga = per_asin.get(str(prodotto.get("asin") or "").upper())
            if not riga:
                continue
            bonus_priorita, nome_priorita = valuta_priorita_prodotto(
                prodotto, categoria, snapshot_filtri
            )
            approvato, punteggio, motivi = valuta_qualita_prodotto(
                prodotto,
                categoria,
                "selettiva",
                snapshot_filtri,
                bonus_priorita,
            )
            if not approvato:
                continue
            prodotto["link"] = riga["link"]
            prodotto["categoria"] = categoria
            prodotto["bonus_priorita"] = bonus_priorita
            prodotto["nome_priorita"] = nome_priorita
            prodotto["punteggio_qualita"] = punteggio
            prodotto["motivi_qualita"] = motivi
            prodotti.append(prodotto)
        prodotti.sort(
            key=lambda p: (
                int(p.get("bonus_priorita") or 0),
                int(p.get("punteggio_qualita") or 0),
                int(p.get("sconto") or 0),
            ),
            reverse=True,
        )
        if len(prodotti) >= 2:
            return prodotti[:2], categoria
    return [], None


def _testo_su_righe(disegno, testo, font, larghezza, massimo_righe=3):
    parole = str(testo or "").split()
    righe = []
    corrente = ""
    for parola in parole:
        prova = f"{corrente} {parola}".strip()
        if disegno.textbbox((0, 0), prova, font=font)[2] <= larghezza:
            corrente = prova
        else:
            if corrente:
                righe.append(corrente)
            corrente = parola
            if len(righe) >= massimo_righe - 1:
                break
    if corrente and len(righe) < massimo_righe:
        righe.append(corrente)
    consumate = len(" ".join(righe))
    if consumate < len(str(testo or "")) and righe:
        ultima = righe[-1]
        while ultima and disegno.textbbox((0, 0), ultima + "…", font=font)[2] > larghezza:
            ultima = ultima[:-1]
        righe[-1] = ultima.rstrip() + "…"
    return righe


def crea_locandina_tiktok(prodotti, categoria, indice_stile=0):
    sfondo, testo, accento, scheda = TIKTOK_STILI[indice_stile % len(TIKTOK_STILI)]
    canvas = Image.new("RGB", (1080, 1920), sfondo)
    disegno = ImageDraw.Draw(canvas)
    font_titolo = _font_terminata(62)
    font_categoria = _font_terminata(34)
    font_nome = _font_terminata(34)
    font_prima = _font_terminata(28)
    font_prezzo = _font_terminata(58)
    font_sconto = _font_terminata(36)
    font_cta = _font_terminata(43)

    disegno.text((64, 72), "2 OFFERTE DA NON PERDERE", font=font_titolo, fill=testo)
    etichetta = AUTO_CATEGORIE.get(categoria, (categoria.upper(),))[0]
    etichetta = re.sub(r"^[^A-Za-zÀ-ÿ0-9]+\s*", "", etichetta).upper()
    disegno.text((66, 154), etichetta, font=font_categoria, fill=accento)
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo = ImageOps.contain(logo, (185, 120), Image.Resampling.LANCZOS)
        canvas.paste(logo, (1080 - logo.width - 55, 130), logo)

    for indice, prodotto in enumerate(prodotti[:2]):
        y0 = 285 + indice * 650
        y1 = y0 + 585
        disegno.rounded_rectangle((48, y0, 1032, y1), radius=38, fill=scheda, outline=accento, width=8)
        disegno.rounded_rectangle((72, y0 + 24, 493, y1 - 24), radius=26, fill="#FFFFFF")
        try:
            risposta = requests.get(prodotto["immagine"], timeout=15)
            risposta.raise_for_status()
            foto = Image.open(BytesIO(risposta.content)).convert("RGB")
            foto = ImageOps.contain(foto, (365, 460), Image.Resampling.LANCZOS)
            canvas.paste(foto, (282 - foto.width // 2, y0 + 292 - foto.height // 2))
        except Exception as errore:
            print(f"Immagine TikTok non disponibile: {errore}")

        disegno.rounded_rectangle((82, y0 + 35, 162, y0 + 105), radius=18, fill=accento)
        disegno.text((105, y0 + 48), f"{indice + 1}", font=font_sconto, fill="#FFFFFF")
        nome_x = 530
        nome_y = y0 + 42
        for riga in _testo_su_righe(disegno, prodotto.get("nome"), font_nome, 450, 3):
            disegno.text((nome_x, nome_y), riga, font=font_nome, fill="#171717")
            nome_y += 45

        vecchio = _prezzo_caption_raccolta_tech(prodotto.get("vecchio_prezzo"))
        attuale = _prezzo_caption_raccolta_tech(prodotto.get("prezzo"))
        if vecchio != "—":
            disegno.text((nome_x, y0 + 245), f"Prima {vecchio}", font=font_prima, fill="#777777")
            bbox = disegno.textbbox((nome_x, y0 + 245), f"Prima {vecchio}", font=font_prima)
            disegno.line((bbox[0], (bbox[1] + bbox[3]) // 2, bbox[2], (bbox[1] + bbox[3]) // 2), fill="#E11D48", width=4)
        disegno.text((nome_x, y0 + 310), attuale, font=font_prezzo, fill=accento)
        sconto = int(prodotto.get("sconto") or 0)
        disegno.rounded_rectangle((nome_x, y0 + 405, 760, y0 + 482), radius=22, fill=accento)
        disegno.text((553, y0 + 421), f"-{sconto}%", font=font_sconto, fill="#FFFFFF")

    disegno.rounded_rectangle((145, 1635, 935, 1765), radius=55, fill=accento)
    cta = "SCOPRI L’OFFERTA"
    bbox = disegno.textbbox((0, 0), cta, font=font_cta)
    disegno.text(((1080 - (bbox[2] - bbox[0])) // 2, 1672), cta, font=font_cta, fill="#FFFFFF")
    disegno.text((215, 1800), "Prezzi e disponibilità possono variare", font=_font_terminata(25), fill=testo)

    output = BytesIO()
    output.name = "bestprice24h_tiktok.jpg"
    canvas.save(output, "JPEG", quality=93, optimize=True)
    output.seek(0)
    return output


def crea_testi_tiktok(prodotti, categoria):
    sconto_migliore = max(int(p.get("sconto") or 0) for p in prodotti)
    etichetta = AUTO_CATEGORIE.get(categoria, (categoria,))[0]
    etichetta = re.sub(r"^[^A-Za-zÀ-ÿ0-9]+\s*", "", etichetta)
    titolo = f"-{sconto_migliore}%: due offerte {etichetta}"
    righe = [titolo]
    for indice, prodotto in enumerate(prodotti, start=1):
        nome = accorcia_nome_articolo(prodotto.get("nome"))
        if len(nome) > 75:
            nome = nome[:72].rsplit(" ", 1)[0] + "…"
        prima = _prezzo_caption_raccolta_tech(prodotto.get("vecchio_prezzo"))
        ora = _prezzo_caption_raccolta_tech(prodotto.get("prezzo"))
        righe.append(
            f"{indice}. {nome}\nPrima: {prima} | Ora: {ora} "
            f"(-{int(prodotto.get('sconto') or 0)}%)\n{prodotto.get('link')}"
        )
    hashtag_categoria = AUTO_HASHTAG.get(categoria, "#tecnologia")
    righe.extend([
        "Scopri le offerte prima che terminino.",
        f"BESTPRICE24H: {TECH_CHANNEL_URL}",
        "Unisciti a BESTPRICE24H, invita i tuoi amici e guadagna buoni regalo Amazon!",
        "Prezzo e disponibilità possono variare.",
        f"#adv #amazon {hashtag_categoria} #offerteamazon #bestprice24h #risparmio",
    ])
    return titolo[:90], "\n\n".join(righe)[:2200]


def _pubblica_su_buffer(titolo, descrizione, media_url, pubblica_il):
    query = """
    mutation CreateTikTokPost($input: CreatePostInput!) {
      createPost(input: $input) {
        __typename
        ... on PostActionSuccess { post { id text } }
        ... on MutationError { message }
      }
    }
    """
    input_post = {
        "text": descrizione,
        "channelId": os.environ["BUFFER_TIKTOK_CHANNEL_ID"],
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": pubblica_il.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "assets": [{"image": {"url": media_url}}],
        "metadata": {"tiktok": {"title": titolo}},
    }
    risposta = requests.post(
        BUFFER_API_URL,
        headers={
            "Authorization": f"Bearer {os.environ['BUFFER_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={"query": query, "variables": {"input": input_post}},
        timeout=30,
    )
    risposta.raise_for_status()
    payload = risposta.json()
    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0].get("message", "Errore API Buffer"))
    risultato = (payload.get("data") or {}).get("createPost") or {}
    if risultato.get("__typename") != "PostActionSuccess":
        raise RuntimeError(risultato.get("message") or "Buffer non ha accettato il post")
    return str((risultato.get("post") or {}).get("id") or "")


async def _prepara_slot_tiktok(bot, data_slot, ora_slot):
    if TIKTOK_LOCK.locked():
        return False
    async with TIKTOK_LOCK:
        adesso = datetime.now(ROMA_TZ)
        db = sqlite3.connect(DB_PATH)
        riga = db.execute(
            "SELECT id, stato, tentativi FROM tiktok_pubblicazioni WHERE slot_data=? AND slot_ora=?",
            (data_slot, ora_slot),
        ).fetchone()
        inviati = db.execute(
            "SELECT COUNT(*) FROM tiktok_pubblicazioni WHERE slot_data=? AND stato IN ('programmato','pubblicato')", (data_slot,)
        ).fetchone()[0]
        if inviati >= 2 or not _tiktok_configurato():
            db.close()
            return False
        if riga and riga[1] in {"programmato", "pubblicato"}:
            db.close()
            return False
        if riga and int(riga[2] or 0) >= 3:
            db.close()
            return False
        if riga:
            pubblicazione_id = riga[0]
            db.execute(
                "UPDATE tiktok_pubblicazioni SET stato='preparazione', tentativi=tentativi+1, aggiornato_il=? WHERE id=?",
                (adesso.isoformat(timespec="seconds"), pubblicazione_id),
            )
        else:
            cursore = db.execute(
                """
                INSERT INTO tiktok_pubblicazioni (
                    slot_data, slot_ora, stato, tentativi, creato_il, aggiornato_il
                ) VALUES (?, ?, 'preparazione', 1, ?, ?)
                """,
                (data_slot, ora_slot, adesso.isoformat(timespec="seconds"), adesso.isoformat(timespec="seconds")),
            )
            pubblicazione_id = cursore.lastrowid
        db.commit()
        db.close()

        try:
            prodotti, categoria = await seleziona_coppia_tiktok()
            if len(prodotti) < 2:
                raise RuntimeError("non ci sono due offerte TECH valide della stessa categoria")
            db = sqlite3.connect(DB_PATH)
            numero_stile = db.execute(
                "SELECT COUNT(*) FROM tiktok_pubblicazioni WHERE stato IN ('programmato','pubblicato')"
            ).fetchone()[0]
            db.close()
            immagine = await asyncio.to_thread(
                crea_locandina_tiktok, prodotti, categoria, numero_stile
            )
            nome_file = f"tiktok_{data_slot.replace('-', '')}_{ora_slot.replace(':', '')}_{pubblicazione_id}.jpg"
            percorso_file = TIKTOK_MEDIA_DIR / nome_file
            percorso_file.write_bytes(immagine.getvalue())
            dominio = os.environ["RAILWAY_PUBLIC_DOMAIN"].strip().strip("/")
            media_url = f"https://{dominio}/media/tiktok/{nome_file}"
            titolo, descrizione = crea_testi_tiktok(prodotti, categoria)
            pubblica_il = max(
                datetime.now(ROMA_TZ) + timedelta(minutes=2),
                datetime.strptime(f"{data_slot} {ora_slot}", "%Y-%m-%d %H:%M").replace(tzinfo=ROMA_TZ),
            )
            if not _tiktok_configurato():
                raise RuntimeError("automazione messa in pausa prima dell'invio")
            buffer_post_id = await asyncio.to_thread(
                _pubblica_su_buffer, titolo, descrizione, media_url, pubblica_il
            )
            aggiornato = datetime.now(ROMA_TZ).isoformat(timespec="seconds")
            db = sqlite3.connect(DB_PATH)
            db.execute(
                """
                UPDATE tiktok_pubblicazioni
                SET categoria=?, titolo=?, file_immagine=?, buffer_post_id=?,
                    stato='programmato', errore=NULL, aggiornato_il=?
                WHERE id=?
                """,
                (categoria, titolo, nome_file, buffer_post_id, aggiornato, pubblicazione_id),
            )
            db.executemany(
                "INSERT OR IGNORE INTO tiktok_pubblicazioni_prodotti (pubblicazione_id, asin, usato_il) VALUES (?, ?, ?)",
                [(pubblicazione_id, p["asin"], aggiornato) for p in prodotti],
            )
            db.commit()
            db.close()
            await _notifica_admin_automazione(
                bot,
                f"✅ Post TikTok programmato per le {pubblica_il.strftime('%H:%M')}: "
                f"{AUTO_CATEGORIE.get(categoria, (categoria,))[0]} · 2 prodotti · stile {numero_stile % 10 + 1}.",
            )
            return True
        except Exception as errore:
            db = sqlite3.connect(DB_PATH)
            db.execute(
                "UPDATE tiktok_pubblicazioni SET stato='errore', errore=?, aggiornato_il=? WHERE id=?",
                (str(errore)[:1000], datetime.now(ROMA_TZ).isoformat(timespec="seconds"), pubblicazione_id),
            )
            db.commit()
            db.close()
            print(f"Errore automazione TikTok: {errore}")
            await _notifica_admin_automazione(bot, f"❌ Post TikTok non programmato: {str(errore)[:700]}")
            return False


async def controlla_pubblicazioni_tiktok(app):
    while True:
        try:
            if _tiktok_configurato():
                adesso = datetime.now(ROMA_TZ)
                for ora_slot in _orari_tiktok():
                    slot = datetime.strptime(
                        f"{adesso.date().isoformat()} {ora_slot}", "%Y-%m-%d %H:%M"
                    ).replace(tzinfo=ROMA_TZ)
                    ritardo = (adesso - slot).total_seconds()
                    if 0 <= ritardo <= 15 * 60:
                        await _prepara_slot_tiktok(
                            app.bot, adesso.date().isoformat(), ora_slot
                        )
        except Exception as errore:
            print(f"Errore controllo TikTok: {errore}")
        await asyncio.sleep(30)


async def testa_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    if update.callback_query:
        await update.callback_query.answer()
    destinazione = update.effective_message
    messaggio = await destinazione.reply_text("🔎 Preparo un'anteprima TikTok con due offerte TECH…")
    prodotti, categoria = await seleziona_coppia_tiktok()
    if len(prodotti) < 2:
        await messaggio.edit_text("ℹ️ Non ci sono due offerte TECH valide della stessa categoria negli ultimi giorni.")
        return
    immagine = await asyncio.to_thread(crea_locandina_tiktok, prodotti, categoria, 0)
    titolo, descrizione = crea_testi_tiktok(prodotti, categoria)
    await messaggio.delete()
    await destinazione.reply_photo(photo=immagine, caption=f"🧪 ANTEPRIMA TIKTOK\n{titolo}")
    await destinazione.reply_text(descrizione, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("🎵 MENU TIKTOK", callback_data="tiktok_menu")
    ]]))


def crea_caption_con_link(messaggio, link, messaggio_gia_html=False):
    """Crea una didascalia uniforme senza mostrare l'URL completo."""
    corpo = messaggio if messaggio_gia_html else html.escape(str(messaggio or ""))
    link_sicuro = html.escape(str(link or ""), quote=True)
    return (
        f"{corpo}\n\n"
        f"👉 <a href=\"{link_sicuro}\">Scopri l’offerta su Amazon</a>\n\n"
        "⚡ Prezzo e disponibilità possono variare."
    )


def rimuovi_link_finale_da_messaggio(messaggio):
    """Pulisce recap storici che contenevano già link e avvertenza finali."""
    testo = str(messaggio or "")
    testo = re.sub(
        r"\n\n👉\s*(?:<a\s+href=\"[^\"]+\">Scopri l’offerta su Amazon</a>|https?://\S+)"
        r"\n\n⚡\s*Prezzo e disponibilità\s+possono variare\.?\s*$",
        "",
        testo,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return testo.strip()


def registra_pubblicazione_monitorata(
    *,
    nome,
    link,
    message_id,
    foto_file_id=None,
    categoria="manuale",
    sconto=0,
    soglia_sconto=0,
    asin=None,
    deal_end_time=None,
    telegram_chat_id=None,
):
    """Registra qualsiasi post Amazon per duplicati e controllo disponibilità."""
    asin = asin or risolvi_asin_da_link(link)
    if not asin:
        return False

    adesso = datetime.now(ROMA_TZ)
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        INSERT OR IGNORE INTO invii_automatici (
            asin, nome, link, categoria, sconto, slot_data, slot_ora, stato,
            creato_il, telegram_message_id, telegram_photo_file_id,
            soglia_sconto, deal_end_time, ultima_verifica, telegram_chat_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pubblicata', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asin,
            nome,
            link,
            categoria or "manuale",
            int(sconto or 0),
            adesso.date().isoformat(),
            "P" + adesso.strftime("%H%M%S%f"),
            adesso.isoformat(timespec="seconds"),
            message_id,
            foto_file_id,
            int(soglia_sconto or 0),
            deal_end_time,
            adesso.isoformat(timespec="seconds"),
            telegram_chat_id or CHANNEL_ID,
        ),
    )
    db.commit()
    db.close()
    return True


def estrai_vecchio_prezzo_da_messaggio(messaggio):

    if not messaggio:
        return "NO"

    match = re.search(
        r"(?:Prima|Listino):\s*([^\n€]+)",
        messaggio,
        flags=re.IGNORECASE,
    )

    if not match:
        return "NO"

    valore = match.group(1).strip()
    return valore or "NO"


def estrai_sconto_da_messaggio(messaggio):
    """Legge percentuali sia dai template manuali sia da quelli HTML."""
    testo = re.sub(r"<[^>]+>", "", str(messaggio or ""))
    match = re.search(r"(?:sconto\s*:?[ ]*|📉\s*)-?(\d{1,3})%", testo, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def offerte_recap_di_oggi(telegram_chat_id):

    oggi = datetime.now(ROMA_TZ).date().isoformat()

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            nome,
            link,
            prezzo,
            vecchio_prezzo,
            pubblicata_il
        FROM recap_offerte
        WHERE substr(pubblicata_il, 1, 10) = ?
          AND telegram_chat_id = ?
        ORDER BY pubblicata_il DESC
    """, (oggi, str(telegram_chat_id)))

    risultati = cur.fetchall()
    db.close()

    return risultati


def recap_gia_inviato(oggi, canale):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute(
        "SELECT 1 FROM recap_giorni_canali WHERE data = ? AND canale = ?",
        (oggi, canale),
    )

    trovato = cur.fetchone() is not None
    db.close()

    return trovato


def segna_recap_inviato(oggi, canale):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO recap_giorni_canali (data, canale, inviato_il)
        VALUES (?, ?, ?)
    """, (
        oggi,
        canale,
        datetime.now(ROMA_TZ).isoformat(timespec="seconds"),
    ))

    db.commit()
    db.close()


def crea_righe_recap(offerte):

    righe = []

    for numero, (nome, link, prezzo, vecchio, _) in enumerate(offerte, start=1):

        nome_breve = accorcia_nome_articolo(nome)
        nome_html = html.escape(str(nome_breve))
        link_html = html.escape(str(link), quote=True)
        prezzo_testo = str(prezzo or "—").strip()
        if prezzo_testo != "—" and "€" not in prezzo_testo:
            prezzo_testo += " €"
        prezzo_html = html.escape(prezzo_testo)

        if vecchio and str(vecchio).upper() != "NO":
            vecchio_testo = str(vecchio).strip()
            if "€" not in vecchio_testo:
                vecchio_testo += " €"
            vecchio_html = html.escape(vecchio_testo)
        else:
            vecchio_html = "—"

        righe.append(
            f'#<b>{numero}</b> <a href="{link_html}">{nome_html}</a>\n'
            f'❌ Prima: <s>{vecchio_html}</s>\n'
            f'✅ Ora: <b>{prezzo_html}</b>'
        )

    return righe


async def invia_recap_giornaliero(bot, canale, telegram_chat_id):

    offerte = offerte_recap_di_oggi(telegram_chat_id)

    if not offerte:
        return False

    righe = crea_righe_recap(offerte)

    intestazione = (
        f"🔥 <b>RECAP {canale.upper()} DI OGGI</b>\n\n"
    )

    club_footer = (
        "\n\n────────────────\n"
        '🎁 <a href="https://t.me/BestPrice24h_bot">'
        "<b>Entra nel Club</b></a>"
        " → invita amici e accumula punti!\n"
        "👥 Invita amici • ⭐ Accumula punti • 🎁 Ottieni premi"
    )

    messaggi = []
    corrente = intestazione

    for riga in righe:

        candidato = corrente + riga + "\n\n"

        if (
            len(candidato) + len(club_footer) > 3900
            and corrente != intestazione
        ):
            messaggi.append(corrente.rstrip())
            corrente = intestazione + riga + "\n\n"
        else:
            corrente = candidato

    if corrente.strip():
        messaggi.append(
            corrente.rstrip() + club_footer
        )

    for testo in messaggi:
        await bot.send_message(
            chat_id=telegram_chat_id,
            text=testo,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    return True


async def controlla_recap(app):

    while True:

        try:
            adesso = datetime.now(ROMA_TZ)
            oggi = adesso.date().isoformat()

            orario_recap_raggiunto = (
                adesso.hour > 22
                or (adesso.hour == 22 and adesso.minute >= 1)
            )

            if orario_recap_raggiunto:
                for canale, telegram_chat_id in (
                    ("tech", CHANNEL_ID),
                    ("casa", CASA_CHANNEL_ID),
                ):
                    if recap_gia_inviato(oggi, canale):
                        continue
                    inviato = await invia_recap_giornaliero(
                        app.bot, canale, telegram_chat_id
                    )

                    # Ogni canale viene segnato soltanto se aveva offerte.
                    if inviato:
                        segna_recap_inviato(oggi, canale)

        except Exception as errore:
            print(f"Errore recap giornaliero: {errore}")

        await asyncio.sleep(30)


# =========================================================
# PROGRAMMAZIONE INVIO OFFERTE
# =========================================================


def salva_foto_programmazione(
    programmazione_id,
    foto_file_id,
):

    if not foto_file_id:
        return

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET foto_file_id = ?
        WHERE id = ?
    """, (
        foto_file_id,
        programmazione_id,
    ))

    db.commit()
    db.close()



def inizializza_programmazioni():

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS programmazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            messaggio TEXT NOT NULL,
            link TEXT NOT NULL,
            prezzo TEXT,
            vecchio_prezzo TEXT DEFAULT 'NO',
            template TEXT DEFAULT 'pulito',
            foto_file_id TEXT,
            invio_previsto TEXT NOT NULL,
            stato TEXT DEFAULT 'attesa',
            data_creazione TEXT NOT NULL
        )
    """)

    # Migrazione automatica per database già esistenti.
    cur.execute("PRAGMA table_info(programmazioni)")
    colonne = {
        riga[1]
        for riga in cur.fetchall()
    }

    if "vecchio_prezzo" not in colonne:
        cur.execute(
            "ALTER TABLE programmazioni "
            "ADD COLUMN vecchio_prezzo TEXT DEFAULT 'NO'"
        )

    if "template" not in colonne:
        cur.execute(
            "ALTER TABLE programmazioni "
            "ADD COLUMN template TEXT DEFAULT 'pulito'"
        )

    if "foto_file_id" not in colonne:
        cur.execute(
            "ALTER TABLE programmazioni "
            "ADD COLUMN foto_file_id TEXT"
        )

    if "telegram_chat_id" not in colonne:
        cur.execute(
            "ALTER TABLE programmazioni "
            "ADD COLUMN telegram_chat_id TEXT"
        )

    db.commit()
    db.close()


def salva_programmazione(
    nome,
    messaggio,
    link,
    prezzo,
    invio_previsto_locale,
    telegram_chat_id=CHANNEL_ID,
):

    # Salviamo in UTC per evitare problemi
    # con ora legale/solare.
    invio_previsto_utc = (
        invio_previsto_locale
        .astimezone(timezone.utc)
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    vecchio_prezzo = (
        estrai_vecchio_prezzo_da_messaggio(
            messaggio
        )
    )

    if messaggio.startswith(
        "🚨 SUPER OFFERTA AMAZON"
    ):
        template = "aggressivo"

    elif messaggio.startswith(
        "⚡ TECH DEAL"
    ):
        template = "tech"

    else:
        template = "pulito"

    cur.execute("""
        INSERT INTO programmazioni (
            nome,
            messaggio,
            link,
            prezzo,
            vecchio_prezzo,
            template,
            foto_file_id,
            telegram_chat_id,
            invio_previsto,
            stato,
            data_creazione
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'attesa', ?)
    """, (
        nome,
        messaggio,
        link,
        prezzo,
        vecchio_prezzo,
        template,
        None,
        telegram_chat_id or CHANNEL_ID,
        invio_previsto_utc.isoformat(
            timespec="seconds"
        ),
        datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        ),
    ))

    programmazione_id = cur.lastrowid

    db.commit()
    db.close()

    return (
        programmazione_id,
        invio_previsto_locale
    )


async def invia_offerta_programmata(
    bot,
    programmazione,
):

    (
        programmazione_id,
        nome,
        messaggio,
        link,
        prezzo,
        foto_file_id,
        telegram_chat_id,
    ) = programmazione
    destinazione = telegram_chat_id or CHANNEL_ID

    messaggio_html = messaggio.startswith("__RICERCA_HTML__")
    if messaggio_html:
        messaggio = messaggio.replace("__RICERCA_HTML__", "", 1)
    messaggio_con_link = crea_caption_con_link(
        messaggio,
        link,
        messaggio_gia_html=messaggio_html,
    )

    bottone_offerta = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎁 CLUB",
                    url="https://t.me/BestPrice24h_bot",
                ),
                InlineKeyboardButton(
                    "🛒 APRI",
                    url=link,
                )
            ]
        ]
    )

    if foto_file_id:
        messaggio_telegram = await bot.send_photo(
            chat_id=destinazione,
            photo=foto_file_id,
            caption=messaggio_con_link,
            parse_mode="HTML",
            reply_markup=bottone_offerta,
        )
    else:
        messaggio_telegram = await bot.send_message(
            chat_id=destinazione,
            text=messaggio_con_link,
            parse_mode="HTML",
            reply_markup=bottone_offerta,
        )

    foto_monitoraggio = foto_file_id
    if getattr(messaggio_telegram, "photo", None):
        foto_monitoraggio = messaggio_telegram.photo[-1].file_id
    sconto_programmato = estrai_sconto_da_messaggio(messaggio) or calcola_sconto(
        prezzo,
        estrai_vecchio_prezzo_da_messaggio(messaggio),
    ) or 0
    registra_pubblicazione_monitorata(
        nome=nome,
        link=link,
        message_id=messaggio_telegram.message_id,
        foto_file_id=foto_monitoraggio,
        sconto=sconto_programmato,
        soglia_sconto=sconto_programmato,
        telegram_chat_id=destinazione,
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET stato = 'inviata'
        WHERE id = ?
    """, (
        programmazione_id,
    ))

    db.commit()
    db.close()

    ultime_offerte.appendleft(
        {
            "nome": nome,
            "link": link,
            "prezzo": prezzo,
        }
    )

    salva_offerta_recap(
        nome,
        link,
        prezzo,
        estrai_vecchio_prezzo_da_messaggio(messaggio),
        messaggio=messaggio,
        foto_file_id=foto_file_id,
        asin=risolvi_asin_da_link(link),
        telegram_chat_id=destinazione,
        origine="programmato",
        sconto=sconto_programmato,
        telegram_message_id=messaggio_telegram.message_id,
    )
    if str(destinazione) == str(CASA_CHANNEL_ID):
        await controlla_raccolta_dopo_post_casa(bot)
    elif str(destinazione) == str(CHANNEL_ID):
        await controlla_raccolta_dopo_post_tech(bot)


async def controlla_programmazioni(app):

    while True:

        try:

            db = sqlite3.connect(DB_PATH)
            cur = db.cursor()

            cur.execute("""
                SELECT
                    id,
                    nome,
                    messaggio,
                    link,
                    prezzo,
                    foto_file_id,
                    telegram_chat_id
                FROM programmazioni
                WHERE stato = 'attesa'
                  AND invio_previsto <= ?
                ORDER BY invio_previsto ASC
            """, (
                datetime.now(
                    timezone.utc
                ).isoformat(
                    timespec="seconds"
                ),
            ))

            programmazioni = cur.fetchall()

            db.close()

            for programmazione in programmazioni:

                try:

                    await invia_offerta_programmata(
                        app.bot,
                        programmazione,
                    )

                except Exception as errore:

                    print(
                        "Errore invio programmato: "
                        f"{errore}"
                    )

        except Exception as errore:

            print(
                "Errore controllo programmazioni: "
                f"{errore}"
            )

        await asyncio.sleep(30)


async def avvia_programmazioni(app):

    app.create_task(
        controlla_programmazioni(app)
    )

    app.create_task(
        controlla_recap(app)
    )

    app.create_task(
        controlla_invii_automatici(app)
    )

    app.create_task(
        controlla_offerte_terminate(app)
    )

    app.create_task(
        controlla_pubblicazioni_tiktok(app)
    )


# =========================================================
# SICUREZZA ADMIN
# =========================================================

def autorizzato(update: Update) -> bool:

    if not ADMIN_ID:
        return False

    user = update.effective_user

    if not user:
        return False

    return str(user.id) == str(ADMIN_ID)


async def controlla_autorizzazione(update: Update):

    if autorizzato(update):
        return True

    if update.message:
        await update.message.reply_text(
            "⛔ Questa funzione è riservata all'amministratore."
        )

    elif update.callback_query:
        await update.callback_query.answer(
            "⛔ Funzione riservata all'amministratore.",
            show_alert=True,
        )

    return False


# =========================================================
# INVIO AUTOMATICO - CONFIGURAZIONE
# =========================================================

def inizializza_automazione():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS configurazione_automatica (
            chiave TEXT PRIMARY KEY,
            valore TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categorie_automatiche (
            categoria TEXT PRIMARY KEY
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categorie_automatiche_canali (
            canale TEXT NOT NULL,
            categoria TEXT NOT NULL,
            PRIMARY KEY (canale, categoria)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS marchi_qualita (
            categoria TEXT NOT NULL,
            marchio TEXT NOT NULL COLLATE NOCASE,
            PRIMARY KEY (categoria, marchio)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS parole_indesiderate_qualita (
            parola TEXT PRIMARY KEY COLLATE NOCASE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prodotti_prioritari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT NOT NULL,
            parola TEXT NOT NULL COLLATE NOCASE,
            marchio TEXT NOT NULL COLLATE NOCASE,
            bonus INTEGER NOT NULL DEFAULT 3,
            UNIQUE(categoria, parola, marchio)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS parole_accessori_priorita (
            parola TEXT PRIMARY KEY COLLATE NOCASE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raccolte_casa_temi (
            tema TEXT PRIMARY KEY
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raccolte_casa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tema TEXT NOT NULL,
            telegram_chat_id TEXT NOT NULL,
            telegram_message_id INTEGER,
            telegram_photo_file_id TEXT,
            pubblicata_il TEXT NOT NULL,
            stato TEXT NOT NULL DEFAULT 'pubblicata'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raccolte_casa_prodotti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raccolta_id INTEGER NOT NULL,
            posizione INTEGER NOT NULL,
            asin TEXT NOT NULL,
            nome TEXT NOT NULL,
            link TEXT NOT NULL,
            prezzo TEXT,
            vecchio_prezzo TEXT,
            immagine_url TEXT,
            sconto INTEGER DEFAULT 0,
            stato TEXT NOT NULL DEFAULT 'pubblicata',
            verifiche_fallite INTEGER DEFAULT 0,
            ultima_verifica TEXT,
            UNIQUE(raccolta_id, asin),
            FOREIGN KEY (raccolta_id) REFERENCES raccolte_casa(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raccolte_casa_data ON raccolte_casa(pubblicata_il DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raccolte_prodotti_asin ON raccolte_casa_prodotti(asin)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raccolte_tech_temi (
            tema TEXT PRIMARY KEY
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raccolte_tech (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tema TEXT NOT NULL,
            telegram_chat_id TEXT NOT NULL,
            telegram_message_id INTEGER,
            telegram_photo_file_id TEXT,
            pubblicata_il TEXT NOT NULL,
            stato TEXT NOT NULL DEFAULT 'pubblicata'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raccolte_tech_prodotti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raccolta_id INTEGER NOT NULL,
            posizione INTEGER NOT NULL,
            asin TEXT NOT NULL,
            nome TEXT NOT NULL,
            link TEXT NOT NULL,
            prezzo TEXT,
            vecchio_prezzo TEXT,
            immagine_url TEXT,
            sconto INTEGER DEFAULT 0,
            stato TEXT NOT NULL DEFAULT 'pubblicata',
            verifiche_fallite INTEGER DEFAULT 0,
            ultima_verifica TEXT,
            UNIQUE(raccolta_id, asin),
            FOREIGN KEY (raccolta_id) REFERENCES raccolte_tech(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raccolte_tech_data ON raccolte_tech(pubblicata_il DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raccolte_tech_prodotti_asin ON raccolte_tech_prodotti(asin)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invii_automatici (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asin TEXT,
            nome TEXT,
            link TEXT,
            categoria TEXT,
            sconto INTEGER,
            slot_data TEXT NOT NULL,
            slot_ora TEXT NOT NULL,
            stato TEXT NOT NULL,
            creato_il TEXT NOT NULL,
            UNIQUE(slot_data, slot_ora)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocco_duplicati_canali (
            canale TEXT NOT NULL,
            asin TEXT NOT NULL,
            stato TEXT NOT NULL DEFAULT 'prenotata',
            prenotato_il TEXT NOT NULL,
            pubblicato_il TEXT,
            PRIMARY KEY (canale, asin)
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_blocco_duplicati_pubblicato "
        "ON blocco_duplicati_canali(canale, pubblicato_il)"
    )
    cur.execute("PRAGMA table_info(invii_automatici)")
    colonne_invii = {riga[1] for riga in cur.fetchall()}
    nuove_colonne = {
        "telegram_message_id": "INTEGER",
        "prezzo": "TEXT",
        "vecchio_prezzo": "TEXT",
        "soglia_sconto": "INTEGER",
        "verifiche_fallite": "INTEGER DEFAULT 0",
        "terminata_il": "TEXT",
        "deal_end_time": "TEXT",
        "ultima_verifica": "TEXT",
        "telegram_photo_file_id": "TEXT",
        "sconto_modificato_notificato": "INTEGER DEFAULT 0",
        "telegram_chat_id": "TEXT",
    }
    for colonna, definizione in nuove_colonne.items():
        if colonna not in colonne_invii:
            cur.execute(f"ALTER TABLE invii_automatici ADD COLUMN {colonna} {definizione}")
    defaults = {
        "attiva": "0",
        "intervallo_minuti": "120",
        "ora_inizio": "09:00",
        "ora_fine": "21:00",
        "prossimo_invio": "",
        "sconto_minimo": "20",
        "qualita_prodotti": "selettiva",
        "punteggio_minimo": "5",
        "bonus_sconto_da": "30",
        "priorita_amazon": "1",
        "tentativi_ricerca": "6",
        "giorni_blocco_duplicati": "10",
        "raggruppa_varianti": "1",
        "indice_categoria_automatica": "0",
        "indice_categoria_ricerca": "0",
    }
    defaults_casa = {
        **defaults,
        "intervallo_minuti": "60",
        "ora_inizio": "08:30",
        "ora_fine": "21:00",
    }
    for chiave, valore in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)",
            (chiave, valore),
        )
        cur.execute(
            "INSERT OR IGNORE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)",
            (f"casa:{chiave}", defaults_casa[chiave]),
        )

    defaults_raccolte = {
        "raccolte_attive": "0",
        "raccolte_frequenza_post": "4",
        "raccolte_quantita": "4",
        "raccolte_prezzo_massimo": "25",
        "raccolte_sconto_minimo": "10",
        "raccolte_qualita": "selettiva",
        "raccolte_indice_tema": "0",
        "raccolte_ultimo_tentativo": "",
    }
    for chiave, valore in defaults_raccolte.items():
        cur.execute(
            "INSERT OR IGNORE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)",
            (f"casa:{chiave}", valore),
        )
    defaults_raccolte_tech = {
        **defaults_raccolte,
        "raccolte_prezzo_massimo": "75",
        "raccolte_qualita": "standard",
    }
    for chiave, valore in defaults_raccolte_tech.items():
        cur.execute(
            "INSERT OR IGNORE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)",
            (f"tech:{chiave}", valore),
        )
    if not cur.execute("SELECT 1 FROM raccolte_casa_temi LIMIT 1").fetchone():
        cur.executemany(
            "INSERT INTO raccolte_casa_temi (tema) VALUES (?)",
            [(tema,) for tema in RACCOLTE_CASA_TEMI],
        )
    if not cur.execute("SELECT 1 FROM raccolte_tech_temi LIMIT 1").fetchone():
        cur.executemany(
            "INSERT INTO raccolte_tech_temi (tema) VALUES (?)",
            [(tema,) for tema in RACCOLTE_TECH_TEMI],
        )

    # Nuova configurazione selettiva: applicata una sola volta e senza
    # cancellare marchi, parole o priorità personalizzati.
    selettiva_v2 = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave='selettiva_v2'"
    ).fetchone()
    if not selettiva_v2:
        for prefisso in ("", "casa:"):
            cur.execute(
                "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES (?, '0')",
                (f"{prefisso}attiva",),
            )
            cur.execute(
                "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES (?, '')",
                (f"{prefisso}prossimo_invio",),
            )
            cur.execute(
                "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES (?, '4')",
                (f"{prefisso}punteggio_minimo",),
            )
            cur.execute(
                "INSERT OR IGNORE INTO configurazione_automatica (chiave, valore) VALUES (?, '6')",
                (f"{prefisso}tentativi_ricerca",),
            )
            cur.execute(
                "INSERT OR IGNORE INTO configurazione_automatica (chiave, valore) VALUES (?, '10')",
                (f"{prefisso}giorni_blocco_duplicati",),
            )
            cur.execute(
                "INSERT OR IGNORE INTO configurazione_automatica (chiave, valore) VALUES (?, '1')",
                (f"{prefisso}raggruppa_varianti",),
            )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) VALUES ('selettiva_v2', '1')"
        )

    # Migrazione eseguita una sola volta: conserva le categorie TECH esistenti,
    # senza reinserire in futuro quelle che l'utente deciderà di rimuovere.
    categorie_migrate = cur.execute(
        "SELECT valore FROM configurazione_automatica "
        "WHERE chiave = 'categorie_canali_migrate_v1'"
    ).fetchone()
    if not categorie_migrate:
        cur.execute(
            """
            INSERT OR IGNORE INTO categorie_automatiche_canali (canale, categoria)
            SELECT 'tech', categoria FROM categorie_automatiche
            """
        )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) "
            "VALUES ('categorie_canali_migrate_v1', '1')"
        )
    casa_inizializzata = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = 'casa:categorie_seed_v1'"
    ).fetchone()
    if not casa_inizializzata:
        cur.executemany(
            "INSERT OR IGNORE INTO categorie_automatiche_canali (canale, categoria) VALUES ('casa', ?)",
            [(categoria,) for categoria in sorted(CASA_CATEGORIE)],
        )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) "
            "VALUES ('casa:categorie_seed_v1', '1')"
        )
    filtri_inizializzati = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = 'filtri_seed_v1'"
    ).fetchone()
    if not filtri_inizializzati:
        for categoria, marchi in MARCHI_AUTORIZZATI.items():
            cur.executemany(
                "INSERT OR IGNORE INTO marchi_qualita (categoria, marchio) VALUES (?, ?)",
                [(categoria, marchio.strip()) for marchio in marchi],
            )
        cur.executemany(
            "INSERT OR IGNORE INTO parole_indesiderate_qualita (parola) VALUES (?)",
            [(parola.strip(),) for parola in PAROLE_INDESIDERATE],
        )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) VALUES ('filtri_seed_v1', '1')"
        )
    catalogo_v2 = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = 'marchi_catalogo_v2'"
    ).fetchone()
    if not catalogo_v2:
        # Aggiornamento non distruttivo: conserva i marchi aggiunti dall'utente
        # e inserisce una sola volta quelli del catalogo ampliato.
        for categoria, marchi in MARCHI_AUTORIZZATI.items():
            cur.executemany(
                "INSERT OR IGNORE INTO marchi_qualita (categoria, marchio) VALUES (?, ?)",
                [(categoria, marchio.strip()) for marchio in marchi],
            )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) "
            "VALUES ('marchi_catalogo_v2', '1')"
        )
    catalogo_v3 = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = 'marchi_catalogo_v3'"
    ).fetchone()
    if not catalogo_v3:
        for categoria, marchi in MARCHI_AUTORIZZATI.items():
            cur.executemany(
                "INSERT OR IGNORE INTO marchi_qualita (categoria, marchio) VALUES (?, ?)",
                [(categoria, marchio.strip()) for marchio in marchi],
            )
        # Corregge una voce errata presente nel primo catalogo distribuito.
        cur.execute(
            "DELETE FROM marchi_qualita WHERE categoria = 'persona' AND lower(marchio) = 'imed'"
        )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) "
            "VALUES ('marchi_catalogo_v3', '1')"
        )
    catalogo_v4 = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = 'marchi_catalogo_v4'"
    ).fetchone()
    if not catalogo_v4:
        for categoria, marchi in MARCHI_AUTORIZZATI.items():
            cur.executemany(
                "INSERT OR IGNORE INTO marchi_qualita (categoria, marchio) VALUES (?, ?)",
                [(categoria, marchio.strip()) for marchio in marchi],
            )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) "
            "VALUES ('marchi_catalogo_v4', '1')"
        )
    priorita_v1 = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = 'priorita_seed_v1'"
    ).fetchone()
    if not priorita_v1:
        for categoria, regole in PRODOTTI_PRIORITARI_DEFAULT.items():
            cur.executemany(
                """
                INSERT OR IGNORE INTO prodotti_prioritari
                    (categoria, parola, marchio, bonus)
                VALUES (?, ?, ?, ?)
                """,
                [(categoria, parola, marchio, bonus) for parola, marchio, bonus in regole],
            )
        cur.executemany(
            "INSERT OR IGNORE INTO parole_accessori_priorita (parola) VALUES (?)",
            [(parola,) for parola in PAROLE_ACCESSORI_PRIORITA_DEFAULT],
        )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) "
            "VALUES ('priorita_seed_v1', '1')"
        )
    dispositivi_amazon_v1 = cur.execute(
        "SELECT valore FROM configurazione_automatica "
        "WHERE chiave = 'priorita_dispositivi_amazon_v1'"
    ).fetchone()
    if not dispositivi_amazon_v1:
        # Aggiorna anche i database esistenti senza cancellare le priorità
        # aggiunte manualmente dall'amministratore.
        cur.executemany(
            """
            INSERT OR IGNORE INTO prodotti_prioritari
                (categoria, parola, marchio, bonus)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("elettronica", "fire tv", "amazon", 5),
                ("elettronica", "kindle", "amazon", 4),
                ("elettronica", "echo", "amazon", 4),
                ("elettronica", "ring", "ring", 4),
            ],
        )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) "
            "VALUES ('priorita_dispositivi_amazon_v1', '1')"
        )
    priorita_v2 = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = 'priorita_catalogo_v2'"
    ).fetchone()
    if not priorita_v2:
        # Aggiornamento non distruttivo: aggiunge il catalogo ampliato anche
        # ai database Railway esistenti e conserva tutte le regole personali.
        for categoria, regole in PRODOTTI_PRIORITARI_DEFAULT.items():
            cur.executemany(
                """
                INSERT OR IGNORE INTO prodotti_prioritari
                    (categoria, parola, marchio, bonus)
                VALUES (?, ?, ?, ?)
                """,
                [(categoria, parola, marchio, bonus) for parola, marchio, bonus in regole],
            )
        cur.execute(
            "INSERT INTO configurazione_automatica (chiave, valore) "
            "VALUES ('priorita_catalogo_v2', '1')"
        )
    versione = cur.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = 'versione_config'"
    ).fetchone()
    if not versione or versione[0] != "3":
        cur.execute(
            "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES ('attiva', '0')"
        )
        cur.execute(
            "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES ('versione_config', '3')"
        )
    db.commit()
    db.close()


def _chiave_config_canale(canale, chiave):
    return chiave if canale == "tech" else f"{canale}:{chiave}"


def leggi_config_automatica(canale="tech"):
    if canale not in {"tech", "casa"}:
        canale = "tech"
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute("SELECT chiave, valore FROM configurazione_automatica")
    valori_grezzi = dict(cur.fetchall())
    valori = {
        chiave: valore
        for chiave in (
            "attiva", "intervallo_minuti", "ora_inizio", "ora_fine",
            "prossimo_invio", "sconto_minimo", "qualita_prodotti",
            "punteggio_minimo", "bonus_sconto_da", "priorita_amazon",
            "tentativi_ricerca", "giorni_blocco_duplicati", "raggruppa_varianti",
        )
        if (valore := valori_grezzi.get(_chiave_config_canale(canale, chiave)))
        is not None
    }
    cur.execute(
        """
        SELECT categoria FROM categorie_automatiche_canali
        WHERE canale = ? ORDER BY categoria
        """,
        (canale,),
    )
    categorie_consentite = TECH_CATEGORIE if canale == "tech" else CASA_CATEGORIE
    categorie = [
        riga[0] for riga in cur.fetchall() if riga[0] in categorie_consentite
    ]
    db.close()
    return {
        "attiva": valori.get("attiva", "0") == "1",
        "intervallo_minuti": int(valori.get("intervallo_minuti", "120")),
        "ora_inizio": valori.get("ora_inizio", "09:00"),
        "ora_fine": valori.get("ora_fine", "21:00"),
        "prossimo_invio": valori.get("prossimo_invio", ""),
        "sconto_minimo": int(valori.get("sconto_minimo", "20")),
        "qualita_prodotti": valori.get("qualita_prodotti", "selettiva"),
        "punteggio_minimo": int(valori.get("punteggio_minimo", "4")),
        "bonus_sconto_da": int(valori.get("bonus_sconto_da", "30")),
        "priorita_amazon": valori.get("priorita_amazon", "1") == "1",
        "tentativi_ricerca": int(valori.get("tentativi_ricerca", "6")),
        "giorni_blocco_duplicati": int(valori.get("giorni_blocco_duplicati", "10")),
        "raggruppa_varianti": valori.get("raggruppa_varianti", "1") == "1",
        "categorie": categorie,
    }


def salva_config_automatica(chiave, valore, canale="tech"):
    db = sqlite3.connect(DB_PATH)
    db.execute(
        "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)",
        (_chiave_config_canale(canale, chiave), str(valore)),
    )
    db.commit()
    db.close()


def leggi_config_raccolte_casa():
    db = sqlite3.connect(DB_PATH)
    valori = dict(db.execute(
        "SELECT chiave, valore FROM configurazione_automatica WHERE chiave LIKE 'casa:raccolte_%'"
    ).fetchall())
    temi = [
        riga[0] for riga in db.execute(
            "SELECT tema FROM raccolte_casa_temi ORDER BY tema"
        ).fetchall()
        if riga[0] in RACCOLTE_CASA_TEMI
    ]
    db.close()
    valore = lambda chiave, default: valori.get(f"casa:{chiave}", default)
    return {
        "attive": valore("raccolte_attive", "0") == "1",
        "frequenza_post": int(valore("raccolte_frequenza_post", "4")),
        "quantita": int(valore("raccolte_quantita", "4")),
        "prezzo_massimo": int(valore("raccolte_prezzo_massimo", "25")),
        "sconto_minimo": int(valore("raccolte_sconto_minimo", "10")),
        "qualita": valore("raccolte_qualita", "selettiva"),
        "indice_tema": int(valore("raccolte_indice_tema", "0")),
        "ultimo_tentativo": valore("raccolte_ultimo_tentativo", ""),
        "temi": temi,
    }


def salva_config_raccolta(chiave, valore):
    salva_config_automatica(f"raccolte_{chiave}", valore, "casa")


def imposta_tema_raccolta(tema):
    if tema not in RACCOLTE_CASA_TEMI:
        return
    db = sqlite3.connect(DB_PATH)
    presente = db.execute(
        "SELECT 1 FROM raccolte_casa_temi WHERE tema=?", (tema,)
    ).fetchone()
    if presente:
        db.execute("DELETE FROM raccolte_casa_temi WHERE tema=?", (tema,))
    else:
        db.execute("INSERT INTO raccolte_casa_temi (tema) VALUES (?)", (tema,))
    db.commit()
    db.close()

def leggi_config_raccolte_tech():
    db = sqlite3.connect(DB_PATH)
    valori = dict(db.execute(
        "SELECT chiave, valore FROM configurazione_automatica WHERE chiave LIKE 'tech:raccolte_%'"
    ).fetchall())
    temi = [
        riga[0] for riga in db.execute(
            "SELECT tema FROM raccolte_tech_temi ORDER BY tema"
        ).fetchall()
        if riga[0] in RACCOLTE_TECH_TEMI
    ]
    db.close()
    valore = lambda chiave, default: valori.get(f"tech:{chiave}", default)
    return {
        "attive": valore("raccolte_attive", "0") == "1",
        "frequenza_post": int(valore("raccolte_frequenza_post", "4")),
        "quantita": int(valore("raccolte_quantita", "4")),
        "prezzo_massimo": int(valore("raccolte_prezzo_massimo", "75")),
        "sconto_minimo": int(valore("raccolte_sconto_minimo", "10")),
        "qualita": valore("raccolte_qualita", "standard"),
        "indice_tema": int(valore("raccolte_indice_tema", "0")),
        "ultimo_tentativo": valore("raccolte_ultimo_tentativo", ""),
        "temi": temi,
    }


def salva_config_raccolta_tech(chiave, valore):
    # Le raccolte TECH hanno uno spazio di configurazione indipendente.
    # La configurazione automatica TECH generale usa chiavi senza prefisso,
    # quindi qui il prefisso va scritto esplicitamente.
    db = sqlite3.connect(DB_PATH)
    db.execute(
        "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)",
        (f"tech:raccolte_{chiave}", str(valore)),
    )
    db.commit()
    db.close()


def imposta_tema_raccolta_tech(tema):
    if tema not in RACCOLTE_TECH_TEMI:
        return
    db = sqlite3.connect(DB_PATH)
    presente = db.execute(
        "SELECT 1 FROM raccolte_tech_temi WHERE tema=?", (tema,)
    ).fetchone()
    if presente:
        db.execute("DELETE FROM raccolte_tech_temi WHERE tema=?", (tema,))
    else:
        db.execute("INSERT INTO raccolte_tech_temi (tema) VALUES (?)", (tema,))
    db.commit()
    db.close()


def ruota_categorie_persistente(categorie, chiave, canale="tech"):
    """Ruota le categorie e memorizza il punto di partenza della prossima ricerca."""
    categorie = list(categorie)
    if not categorie:
        return []
    db = sqlite3.connect(DB_PATH)
    riga = db.execute(
        "SELECT valore FROM configurazione_automatica WHERE chiave = ?",
        (_chiave_config_canale(canale, chiave),),
    ).fetchone()
    indice = int(riga[0]) if riga and str(riga[0]).isdigit() else 0
    indice %= len(categorie)
    ordinate = categorie[indice:] + categorie[:indice]
    db.execute(
        "INSERT OR REPLACE INTO configurazione_automatica (chiave, valore) VALUES (?, ?)",
        (_chiave_config_canale(canale, chiave), str((indice + 1) % len(categorie))),
    )
    db.commit()
    db.close()
    return ordinate


def leggi_marchi_qualita(categoria=None):
    db = sqlite3.connect(DB_PATH)
    if categoria:
        righe = db.execute(
            "SELECT marchio FROM marchi_qualita WHERE categoria = ? ORDER BY marchio COLLATE NOCASE",
            (categoria,),
        ).fetchall()
        risultato = [riga[0] for riga in righe]
    else:
        righe = db.execute(
            "SELECT categoria, marchio FROM marchi_qualita ORDER BY categoria, marchio COLLATE NOCASE"
        ).fetchall()
        risultato = righe
    db.close()
    return risultato


def leggi_parole_indesiderate():
    db = sqlite3.connect(DB_PATH)
    righe = db.execute(
        "SELECT parola FROM parole_indesiderate_qualita ORDER BY parola COLLATE NOCASE"
    ).fetchall()
    db.close()
    return [riga[0] for riga in righe]


def leggi_prodotti_prioritari(categoria=None):
    db = sqlite3.connect(DB_PATH)
    if categoria:
        righe = db.execute(
            """
            SELECT id, categoria, parola, marchio, bonus
            FROM prodotti_prioritari
            WHERE categoria = ?
            ORDER BY bonus DESC, parola COLLATE NOCASE
            """,
            (categoria,),
        ).fetchall()
    else:
        righe = db.execute(
            """
            SELECT id, categoria, parola, marchio, bonus
            FROM prodotti_prioritari
            ORDER BY categoria, bonus DESC, parola COLLATE NOCASE
            """
        ).fetchall()
    db.close()
    return righe


def leggi_parole_accessori_priorita():
    db = sqlite3.connect(DB_PATH)
    righe = db.execute(
        "SELECT parola FROM parole_accessori_priorita ORDER BY parola COLLATE NOCASE"
    ).fetchall()
    db.close()
    return [riga[0] for riga in righe]


def termini_prioritari_categoria(categoria):
    termini = []
    for _, _, parola, _, _ in leggi_prodotti_prioritari(categoria):
        if parola.lower() not in {termine.lower() for termine in termini}:
            termini.append(parola)
    return termini


def _testo_elenco(valori, vuoto="nessuno"):
    return ", ".join(valori) if valori else vuoto


async def mostra_menu_filtri(query):
    configurazione = leggi_config_automatica()
    priorita = "ATTIVA" if configurazione["priorita_amazon"] else "DISATTIVATA"
    tastiera = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏷 MARCHI AUTORIZZATI", callback_data="filter_brands")],
        [InlineKeyboardButton("🚫 PAROLE ESCLUSE", callback_data="filter_words")],
        [InlineKeyboardButton("🚀 PRODOTTI PRIORITARI", callback_data="priority_menu")],
        [InlineKeyboardButton(
            f"⭐ PUNTEGGIO MINIMO: {configurazione['punteggio_minimo']}",
            callback_data="filter_score",
        )],
        [InlineKeyboardButton(
            f"📉 BONUS SCONTO: DAL {configurazione['bonus_sconto_da']}%",
            callback_data="filter_bonus",
        )],
        [InlineKeyboardButton(
            f"🏪 PRIORITÀ AMAZON: {priorita}",
            callback_data="filter_amazon",
        )],
        [InlineKeyboardButton("📊 RIEPILOGO FILTRI", callback_data="filter_summary")],
        [InlineKeyboardButton("♻️ RIPRISTINA PREDEFINITI", callback_data="filter_reset")],
        [InlineKeyboardButton("⬅️ TORNA ALLE IMPOSTAZIONI", callback_data="settings_menu")],
    ])
    await query.edit_message_text(
        "⚙️ Filtri della modalità selettiva\n\n"
        "Puoi modificare questi valori senza intervenire sul codice. "
        "Ogni modifica disattiva l’automazione: riattivala dopo aver terminato.",
        reply_markup=tastiera,
    )


def _callback_ritorno_filtri(context):
    return "selective_menu" if context.user_data.get("filtri_da_selettiva") else "auto_filtri"


def _categorie_filtri_context(context):
    if not context.user_data.get("filtri_da_selettiva"):
        return set(AUTO_CATEGORIE)
    return TECH_CATEGORIE if _auto_canale_corrente(context) == "tech" else CASA_CATEGORIE


async def mostra_categorie_marchi(query, context):
    conteggi = {}
    for categoria, _ in leggi_marchi_qualita():
        conteggi[categoria] = conteggi.get(categoria, 0) + 1
    tastiera = [
        [InlineKeyboardButton(
            f"{etichetta.upper()} ({conteggi.get(codice, 0)})",
            callback_data=f"filter_brandcat_{codice}",
        )]
        for codice, (etichetta, _) in AUTO_CATEGORIE.items()
        if codice in _categorie_filtri_context(context)
    ]
    tastiera.append([InlineKeyboardButton("⬅️ INDIETRO", callback_data=_callback_ritorno_filtri(context))])
    await query.edit_message_text(
        "🏷 Scegli la categoria di cui vuoi gestire i marchi:",
        reply_markup=InlineKeyboardMarkup(tastiera),
    )


async def mostra_gestione_marchi(query, context, categoria=None):
    categoria = categoria or context.user_data.get("filtro_categoria")
    if categoria not in AUTO_CATEGORIE:
        return await mostra_categorie_marchi(query, context)
    context.user_data["filtro_categoria"] = categoria
    marchi = leggi_marchi_qualita(categoria)
    etichetta = AUTO_CATEGORIE[categoria][0]
    testo = (
        f"🏷 Marchi autorizzati — {etichetta}\n\n"
        f"{_testo_elenco(marchi)}\n\n"
        f"Totale: {len(marchi)}"
    )
    tastiera = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ AGGIUNGI MARCHIO", callback_data="filter_brand_add")],
        [InlineKeyboardButton("➖ RIMUOVI MARCHIO", callback_data="filter_brand_remove")],
        [InlineKeyboardButton("⬅️ CAMBIA CATEGORIA", callback_data="filter_brands")],
        [InlineKeyboardButton("⚙️ MENU FILTRI", callback_data=_callback_ritorno_filtri(context))],
    ])
    await query.edit_message_text(testo[:4000], reply_markup=tastiera)


async def mostra_gestione_parole(query, context):
    parole = leggi_parole_indesiderate()
    await query.edit_message_text(
        "🚫 Parole escluse\n\n"
        f"{_testo_elenco(parole)}\n\n"
        "Se una di queste espressioni compare nel titolo, il prodotto perde 3 punti.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ AGGIUNGI PAROLA", callback_data="filter_word_add")],
            [InlineKeyboardButton("➖ RIMUOVI PAROLA", callback_data="filter_word_remove")],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data=_callback_ritorno_filtri(context))],
        ]),
    )


async def gestisci_filtri(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    azione = query.data
    canale_filtri = (
        _auto_canale_corrente(context)
        if context.user_data.get("filtri_da_selettiva") else "tech"
    )

    if azione == "auto_filtri":
        context.user_data["filtri_da_selettiva"] = False
        return await mostra_menu_filtri(query)
    if azione == "filter_brands":
        return await mostra_categorie_marchi(query, context)
    if azione.startswith("filter_brandcat_"):
        categoria = azione.replace("filter_brandcat_", "", 1)
        return await mostra_gestione_marchi(query, context, categoria)
    if azione == "filter_words":
        return await mostra_gestione_parole(query, context)
    if azione == "filter_score":
        tastiera = [
            [InlineKeyboardButton(str(v), callback_data=f"filter_score_{v}") for v in range(3, 7)],
            [InlineKeyboardButton(str(v), callback_data=f"filter_score_{v}") for v in range(7, 9)],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data="auto_filtri")],
        ]
        return await query.edit_message_text(
            "⭐ Punteggio minimo\n\nPiù è alto, più la selezione è severa. Consigliato: 5.",
            reply_markup=InlineKeyboardMarkup(tastiera),
        )
    if azione.startswith("filter_score_"):
        valore = int(azione.rsplit("_", 1)[1])
        salva_config_automatica("punteggio_minimo", valore, canale_filtri)
        salva_config_automatica("attiva", 0, canale_filtri)
        return await mostra_menu_filtri(query)
    if azione == "filter_bonus":
        valori = (20, 25, 30, 35, 40)
        tastiera = [[
            InlineKeyboardButton(f"{v}%", callback_data=f"filter_bonus_{v}") for v in valori
        ], [InlineKeyboardButton("⬅️ INDIETRO", callback_data="auto_filtri")]]
        return await query.edit_message_text(
            "📉 Da quale sconto assegnare +2 punti?\n\nConsigliato: 30%.",
            reply_markup=InlineKeyboardMarkup(tastiera),
        )
    if azione.startswith("filter_bonus_"):
        valore = int(azione.rsplit("_", 1)[1])
        salva_config_automatica("bonus_sconto_da", valore, canale_filtri)
        salva_config_automatica("attiva", 0, canale_filtri)
        return await mostra_menu_filtri(query)
    if azione == "filter_amazon":
        attiva = leggi_config_automatica(canale_filtri)["priorita_amazon"]
        salva_config_automatica("priorita_amazon", 0 if attiva else 1, canale_filtri)
        salva_config_automatica("attiva", 0, canale_filtri)
        return await mostra_menu_filtri(query)
    if azione == "filter_summary":
        config = leggi_config_automatica(canale_filtri)
        conteggio_marchi = len(leggi_marchi_qualita())
        conteggio_parole = len(leggi_parole_indesiderate())
        conteggio_priorita = len(leggi_prodotti_prioritari())
        return await query.edit_message_text(
            "📊 Riepilogo filtri\n\n"
            f"Modalità: {config['qualita_prodotti'].capitalize()}\n"
            f"Sconto minimo per la pubblicazione: {config['sconto_minimo']}%\n"
            f"Punteggio minimo: {config['punteggio_minimo']}\n"
            f"Bonus +2 dallo sconto: {config['bonus_sconto_da']}%\n"
            f"Priorità Amazon (+3): {'attiva' if config['priorita_amazon'] else 'disattivata'}\n"
            f"Marchi autorizzati: {conteggio_marchi}\n"
            f"Parole escluse: {conteggio_parole}\n"
            f"Prodotti prioritari: {conteggio_priorita}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ INDIETRO", callback_data="auto_filtri")
            ]]),
        )
    if azione == "filter_reset":
        return await query.edit_message_text(
            "♻️ Vuoi ripristinare tutti i marchi, le parole escluse e i punteggi predefiniti?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ SÌ, RIPRISTINA", callback_data="filter_reset_yes")],
                [InlineKeyboardButton("❌ ANNULLA", callback_data="auto_filtri")],
            ]),
        )
    if azione == "filter_reset_yes":
        db = sqlite3.connect(DB_PATH)
        db.execute("DELETE FROM marchi_qualita")
        db.execute("DELETE FROM parole_indesiderate_qualita")
        for categoria, marchi in MARCHI_AUTORIZZATI.items():
            db.executemany(
                "INSERT INTO marchi_qualita (categoria, marchio) VALUES (?, ?)",
                [(categoria, marchio) for marchio in marchi],
            )
        db.executemany(
            "INSERT INTO parole_indesiderate_qualita (parola) VALUES (?)",
            [(parola,) for parola in PAROLE_INDESIDERATE],
        )
        db.commit()
        db.close()
        salva_config_automatica("punteggio_minimo", 4, canale_filtri)
        salva_config_automatica("bonus_sconto_da", 30, canale_filtri)
        salva_config_automatica("priorita_amazon", 1, canale_filtri)
        salva_config_automatica("attiva", 0, canale_filtri)
        return await mostra_menu_filtri(query)


async def richiedi_modifica_filtro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    azione = query.data
    mappa = {
        "filter_brand_add": (FILTRO_MARCHIO_AGGIUNGI, "Scrivi il marchio da aggiungere."),
        "filter_brand_remove": (FILTRO_MARCHIO_RIMUOVI, "Scrivi il marchio da rimuovere."),
        "filter_word_add": (FILTRO_PAROLA_AGGIUNGI, "Scrivi la parola o l’espressione da escludere."),
        "filter_word_remove": (FILTRO_PAROLA_RIMUOVI, "Scrivi la parola o l’espressione da rimuovere."),
    }
    stato, istruzione = mappa[azione]
    if "brand" in azione and context.user_data.get("filtro_categoria") not in AUTO_CATEGORIE:
        await query.edit_message_text("❌ Seleziona prima una categoria.")
        return ConversationHandler.END
    await query.edit_message_text(
        f"{istruzione}\n\nUsa il nome esatto, per esempio: Philips\n"
        "Per annullare scrivi /annulla"
    )
    return stato


def _pulisci_valore_filtro(testo):
    return re.sub(r"\s+", " ", str(testo or "").strip())[:80]


async def ricevi_modifica_filtro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    valore = _pulisci_valore_filtro(update.message.text)
    stato = context.user_data.get("stato_filtro_corrente")
    if len(valore) < 2:
        await update.message.reply_text("❌ Inserisci almeno 2 caratteri.")
        return stato

    # Lo stato viene valorizzato dai quattro wrapper registrati nel ConversationHandler.
    categoria = context.user_data.get("filtro_categoria")
    db = sqlite3.connect(DB_PATH)
    if stato == FILTRO_MARCHIO_AGGIUNGI:
        db.execute(
            "INSERT OR IGNORE INTO marchi_qualita (categoria, marchio) VALUES (?, ?)",
            (categoria, valore),
        )
        messaggio = f"✅ Marchio aggiunto in {AUTO_CATEGORIE[categoria][0]}: {valore}"
    elif stato == FILTRO_MARCHIO_RIMUOVI:
        cursore = db.execute(
            "DELETE FROM marchi_qualita WHERE categoria = ? AND marchio = ? COLLATE NOCASE",
            (categoria, valore),
        )
        messaggio = "✅ Marchio rimosso." if cursore.rowcount else "ℹ️ Marchio non trovato."
    elif stato == FILTRO_PAROLA_AGGIUNGI:
        db.execute(
            "INSERT OR IGNORE INTO parole_indesiderate_qualita (parola) VALUES (?)",
            (valore,),
        )
        messaggio = f"✅ Parola esclusa aggiunta: {valore}"
    else:
        cursore = db.execute(
            "DELETE FROM parole_indesiderate_qualita WHERE parola = ? COLLATE NOCASE",
            (valore,),
        )
        messaggio = "✅ Parola rimossa." if cursore.rowcount else "ℹ️ Parola non trovata."
    db.commit()
    db.close()
    canale = _auto_canale_corrente(context) if context.user_data.get("filtri_da_selettiva") else "tech"
    salva_config_automatica("attiva", 0, canale)
    await update.message.reply_text(
        messaggio + "\n\nL’automazione è stata disattivata: riattivala dopo le modifiche.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ TORNA AI FILTRI", callback_data=_callback_ritorno_filtri(context))
        ]]),
    )
    context.user_data.pop("stato_filtro_corrente", None)
    return ConversationHandler.END


def _imposta_stato_filtro(stato):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["stato_filtro_corrente"] = stato
        return await richiedi_modifica_filtro(update, context)
    return handler


async def mostra_menu_priorita(query, context):
    consentite = _categorie_filtri_context(context)
    regole = [riga for riga in leggi_prodotti_prioritari() if riga[1] in consentite]
    await query.edit_message_text(
        "🚀 PRODOTTI PRIORITARI\n\n"
        "Le priorità servono a far emergere prodotti importanti prima delle offerte comuni.\n"
        f"Regole attive: {len(regole)}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 PRIORITÀ PER CATEGORIA", callback_data="priority_categories")],
            [InlineKeyboardButton("🚫 PAROLE ANTI-ACCESSORIO", callback_data="priority_accessories")],
            [InlineKeyboardButton("♻️ RIPRISTINA PRIORITÀ", callback_data="priority_reset")],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data=_callback_ritorno_filtri(context))],
        ]),
    )


async def mostra_categorie_priorita(query, context):
    conteggi = {}
    for _, categoria, _, _, _ in leggi_prodotti_prioritari():
        conteggi[categoria] = conteggi.get(categoria, 0) + 1
    tastiera = [[InlineKeyboardButton(
        f"{etichetta.upper()} ({conteggi.get(codice, 0)})",
        callback_data=f"priority_cat_{codice}",
    )] for codice, (etichetta, _) in AUTO_CATEGORIE.items()
       if codice in _categorie_filtri_context(context)]
    tastiera.append([InlineKeyboardButton("⬅️ INDIETRO", callback_data="priority_menu")])
    await query.edit_message_text(
        "🚀 Scegli la categoria:", reply_markup=InlineKeyboardMarkup(tastiera)
    )


async def mostra_regole_priorita(query, context, categoria=None):
    categoria = categoria or context.user_data.get("priorita_categoria")
    if categoria not in AUTO_CATEGORIE:
        return await mostra_categorie_priorita(query, context)
    context.user_data["priorita_categoria"] = categoria
    regole = leggi_prodotti_prioritari(categoria)
    righe = [f"🚀 PRIORITÀ — {AUTO_CATEGORIE[categoria][0]}\n"]
    for regola_id, _, parola, marchio, bonus in regole:
        righe.append(f"#{regola_id} · {parola} · {marchio} · +{bonus}")
    if not regole:
        righe.append("Nessuna regola configurata.")
    await query.edit_message_text(
        "\n".join(righe)[:3900],
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ AGGIUNGI PRIORITÀ", callback_data="priority_add")],
            [InlineKeyboardButton("➖ RIMUOVI PRIORITÀ", callback_data="priority_remove")],
            [InlineKeyboardButton("⬅️ CAMBIA CATEGORIA", callback_data="priority_categories")],
            [InlineKeyboardButton("🚀 MENU PRIORITÀ", callback_data="priority_menu")],
        ]),
    )


async def mostra_accessori_priorita(query):
    parole = leggi_parole_accessori_priorita()
    await query.edit_message_text(
        "🚫 PAROLE ANTI-ACCESSORIO\n\n"
        f"{_testo_elenco(parole)}\n\n"
        "Se una di queste parole compare nel titolo, il prodotto non riceve il bonus priorità.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ AGGIUNGI PAROLA", callback_data="priority_access_add")],
            [InlineKeyboardButton("➖ RIMUOVI PAROLA", callback_data="priority_access_remove")],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data="priority_menu")],
        ]),
    )


async def gestisci_priorita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    azione = query.data
    if azione == "priority_menu":
        return await mostra_menu_priorita(query, context)
    if azione == "priority_categories":
        return await mostra_categorie_priorita(query, context)
    if azione.startswith("priority_cat_"):
        return await mostra_regole_priorita(
            query, context, azione.replace("priority_cat_", "", 1)
        )
    if azione == "priority_accessories":
        return await mostra_accessori_priorita(query)
    if azione == "priority_reset":
        return await query.edit_message_text(
            "♻️ Ripristinare tutte le priorità e le parole anti-accessorio predefinite?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ SÌ, RIPRISTINA", callback_data="priority_reset_yes")],
                [InlineKeyboardButton("❌ ANNULLA", callback_data="priority_menu")],
            ]),
        )
    if azione == "priority_reset_yes":
        db = sqlite3.connect(DB_PATH)
        db.execute("DELETE FROM prodotti_prioritari")
        db.execute("DELETE FROM parole_accessori_priorita")
        for categoria, regole in PRODOTTI_PRIORITARI_DEFAULT.items():
            db.executemany(
                "INSERT INTO prodotti_prioritari (categoria, parola, marchio, bonus) VALUES (?, ?, ?, ?)",
                [(categoria, parola, marchio, bonus) for parola, marchio, bonus in regole],
            )
        db.executemany(
            "INSERT INTO parole_accessori_priorita (parola) VALUES (?)",
            [(parola,) for parola in PAROLE_ACCESSORI_PRIORITA_DEFAULT],
        )
        db.commit()
        db.close()
        canale = _auto_canale_corrente(context) if context.user_data.get("filtri_da_selettiva") else "tech"
        salva_config_automatica("attiva", 0, canale)
        return await mostra_menu_priorita(query, context)


async def richiedi_modifica_priorita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    azione = query.data
    if azione in {"priority_add", "priority_remove"}:
        if context.user_data.get("priorita_categoria") not in AUTO_CATEGORIE:
            await query.edit_message_text("❌ Seleziona prima una categoria.")
            return ConversationHandler.END
    istruzioni = {
        "priority_add": (
            PRIORITA_AGGIUNGI,
            "Scrivi: PRODOTTO | MARCHIO | BONUS\n\nEsempio: iPhone | Apple | 5",
        ),
        "priority_remove": (
            PRIORITA_RIMUOVI,
            "Scrivi il numero della regola da rimuovere. Esempio: 12",
        ),
        "priority_access_add": (
            PRIORITA_ACCESSORIO_AGGIUNGI,
            "Scrivi la parola anti-accessorio da aggiungere. Esempio: cover",
        ),
        "priority_access_remove": (
            PRIORITA_ACCESSORIO_RIMUOVI,
            "Scrivi la parola anti-accessorio da rimuovere.",
        ),
    }
    stato, testo = istruzioni[azione]
    context.user_data["stato_priorita_corrente"] = stato
    await query.edit_message_text(testo + "\n\nPer annullare scrivi /annulla")
    return stato


async def ricevi_modifica_priorita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    stato = context.user_data.get("stato_priorita_corrente")
    testo = _pulisci_valore_filtro(update.message.text)
    categoria = context.user_data.get("priorita_categoria")
    db = sqlite3.connect(DB_PATH)
    messaggio = ""
    try:
        if stato == PRIORITA_AGGIUNGI:
            parti = [parte.strip() for parte in testo.split("|")]
            if len(parti) != 3:
                await update.message.reply_text("❌ Usa il formato: iPhone | Apple | 5")
                return stato
            parola, marchio, bonus_testo = parti
            bonus = int(bonus_testo)
            if not parola or not marchio or bonus < 1 or bonus > 10:
                raise ValueError
            db.execute(
                """
                INSERT OR REPLACE INTO prodotti_prioritari
                    (id, categoria, parola, marchio, bonus)
                VALUES (
                    (SELECT id FROM prodotti_prioritari WHERE categoria=? AND parola=? COLLATE NOCASE AND marchio=? COLLATE NOCASE),
                    ?, ?, ?, ?
                )
                """,
                (categoria, parola, marchio, categoria, parola, marchio, bonus),
            )
            messaggio = f"✅ Priorità salvata: {parola} · {marchio} · +{bonus}"
        elif stato == PRIORITA_RIMUOVI:
            regola_id = int(testo.lstrip("#"))
            cursore = db.execute(
                "DELETE FROM prodotti_prioritari WHERE id=? AND categoria=?",
                (regola_id, categoria),
            )
            messaggio = "✅ Priorità rimossa." if cursore.rowcount else "ℹ️ Regola non trovata."
        elif stato == PRIORITA_ACCESSORIO_AGGIUNGI:
            if len(testo) < 2:
                raise ValueError
            db.execute(
                "INSERT OR IGNORE INTO parole_accessori_priorita (parola) VALUES (?)", (testo,)
            )
            messaggio = f"✅ Parola anti-accessorio aggiunta: {testo}"
        elif stato == PRIORITA_ACCESSORIO_RIMUOVI:
            cursore = db.execute(
                "DELETE FROM parole_accessori_priorita WHERE parola=? COLLATE NOCASE", (testo,)
            )
            messaggio = "✅ Parola rimossa." if cursore.rowcount else "ℹ️ Parola non trovata."
        else:
            raise ValueError
        db.commit()
    except (TypeError, ValueError):
        db.close()
        await update.message.reply_text("❌ Valore non valido. Controlla il formato e riprova.")
        return stato
    db.close()
    canale = _auto_canale_corrente(context) if context.user_data.get("filtri_da_selettiva") else "tech"
    salva_config_automatica("attiva", 0, canale)
    context.user_data.pop("stato_priorita_corrente", None)
    await update.message.reply_text(
        messaggio + "\n\nL’automazione è stata disattivata: riattivala dopo le modifiche.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🚀 TORNA ALLE PRIORITÀ", callback_data="priority_menu")
        ]]),
    )
    return ConversationHandler.END


def tastiera_automazione(configurazione, canale):
    stato = "🟢 ATTIVA" if configurazione["attiva"] else "🔴 DISATTIVATA"
    etichetta_qualita = (
        "SOLO MARCHE"
        if configurazione["qualita_prodotti"] == "marche"
        else configurazione["qualita_prodotti"].upper()
    )
    righe = [
        [InlineKeyboardButton(f"STATO: {stato}", callback_data="auto_toggle")],
        [InlineKeyboardButton(
            f"⏱ OGNI {configurazione['intervallo_minuti']} MINUTI",
            callback_data="auto_intervallo",
        )],
        [InlineKeyboardButton(
            f"🕒 DALLE {configurazione['ora_inizio']} ALLE {configurazione['ora_fine']}",
            callback_data="auto_fascia",
        )],
        [InlineKeyboardButton("🗂 CATEGORIE PRODOTTI", callback_data="auto_categorie")],
        [InlineKeyboardButton(
            f"📉 SCONTO MINIMO: {configurazione['sconto_minimo']}%",
            callback_data="auto_sconto",
        )],
        [InlineKeyboardButton(
            f"🎯 QUALITÀ: {etichetta_qualita}",
            callback_data="auto_qualita",
        )],
        [InlineKeyboardButton(
            f"🔁 BLOCCO DUPLICATI: {configurazione['giorni_blocco_duplicati']} GIORNI",
            callback_data="auto_duplicates",
        )],
    ]
    if configurazione["qualita_prodotti"] == "selettiva":
        righe.append([
            InlineKeyboardButton("⚙️ PERSONALIZZA SELETTIVA", callback_data="selective_menu")
        ])
    if canale == "casa":
        righe.append([
            InlineKeyboardButton("🧺 RACCOLTE CASA", callback_data="casa_collections")
        ])
    else:
        righe.append([
            InlineKeyboardButton("📦 RACCOLTE TECH", callback_data="tech_collections")
        ])
    righe.extend([
        [InlineKeyboardButton("🔎 CERCA OFFERTE", callback_data=f"offer_search_{canale}")],
        [InlineKeyboardButton("🧪 TESTA RICERCA", callback_data="auto_test")],
        [InlineKeyboardButton("⬅️ TORNA AI CANALI", callback_data="auto_channels")],
    ])
    return InlineKeyboardMarkup(righe)


def _auto_canale_corrente(context):
    canale = context.user_data.get("auto_canale", "tech")
    return canale if canale in {"tech", "casa"} else "tech"


async def mostra_menu_raccolte_casa(query):
    configurazione = leggi_config_raccolte_casa()
    stato = "🟢 ATTIVE" if configurazione["attive"] else "🔴 DISATTIVATE"
    qualita = configurazione["qualita"].upper()
    temi = [RACCOLTE_CASA_TEMI[x]["etichetta"] for x in configurazione["temi"]]
    await query.edit_message_text(
        "🧺 RACCOLTE CASA\n\n"
        f"Stato: {stato}\n"
        f"Frequenza: ogni {configurazione['frequenza_post']} post CASA\n"
        f"Prodotti: {configurazione['quantita']}\n"
        f"Prezzo massimo: {configurazione['prezzo_massimo']} €\n"
        f"Sconto minimo: {configurazione['sconto_minimo']}%\n"
        f"Qualità: {qualita}\n"
        f"Temi: {', '.join(temi) if temi else 'nessuno'}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"STATO: {stato}", callback_data="casa_bundle_toggle")],
            [InlineKeyboardButton(
                f"🔁 OGNI {configurazione['frequenza_post']} POST CASA",
                callback_data="casa_bundle_frequency",
            )],
            [InlineKeyboardButton(
                f"📦 PRODOTTI: {configurazione['quantita']}",
                callback_data="casa_bundle_quantity",
            )],
            [InlineKeyboardButton(
                f"💶 PREZZO MASSIMO: {configurazione['prezzo_massimo']} €",
                callback_data="casa_bundle_price",
            )],
            [InlineKeyboardButton(
                f"📉 SCONTO MINIMO: {configurazione['sconto_minimo']}%",
                callback_data="casa_bundle_discount",
            )],
            [InlineKeyboardButton(
                f"🎯 QUALITÀ: {qualita}", callback_data="casa_bundle_quality"
            )],
            [InlineKeyboardButton("🗂 SCEGLI TEMI", callback_data="casa_bundle_themes")],
            [InlineKeyboardButton("🧪 TESTA RACCOLTA", callback_data="casa_bundle_test")],
            [InlineKeyboardButton("⬅️ TORNA ALL'AUTOMAZIONE CASA", callback_data="auto_menu")],
        ]),
    )


async def mostra_temi_raccolte_casa(query):
    selezionati = set(leggi_config_raccolte_casa()["temi"])
    tastiera = []
    for tema, dati in RACCOLTE_CASA_TEMI.items():
        segno = "✅" if tema in selezionati else "▫️"
        tastiera.append([InlineKeyboardButton(
            f"{segno} {dati['etichetta']}", callback_data=f"casa_bundle_theme_{tema}"
        )])
    tastiera.append([InlineKeyboardButton("✅ FATTO", callback_data="casa_collections")])
    await query.edit_message_text(
        "🗂 Scegli i temi delle raccolte. Ogni post conterrà prodotti dello stesso tema:",
        reply_markup=InlineKeyboardMarkup(tastiera),
    )


async def gestisci_raccolte_casa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    azione = query.data
    configurazione = leggi_config_raccolte_casa()

    if azione == "casa_collections":
        return await mostra_menu_raccolte_casa(query)
    if azione == "casa_bundle_toggle":
        if not configurazione["attive"] and not configurazione["temi"]:
            await query.message.reply_text("❌ Seleziona prima almeno un tema.")
            return
        salva_config_raccolta("attive", 0 if configurazione["attive"] else 1)
        return await mostra_menu_raccolte_casa(query)
    menu_valori = {
        "casa_bundle_frequency": ("Ogni quanti post CASA?", (2, 4, 6, 8), "frequency", " POST"),
        "casa_bundle_quantity": ("Quanti prodotti nella raccolta?", (2, 4, 6), "quantity", ""),
        "casa_bundle_price": ("Prezzo massimo per prodotto", (15, 25, 40, 60), "price", " €"),
        "casa_bundle_discount": ("Sconto minimo", (5, 10, 15, 20), "discount", "%"),
    }
    if azione in menu_valori:
        titolo, valori, prefisso, suffisso = menu_valori[azione]
        return await query.edit_message_text(
            titolo,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"{valore}{suffisso}", callback_data=f"casa_bundle_{prefisso}_{valore}"
                ) for valore in valori],
                [InlineKeyboardButton("⬅️ INDIETRO", callback_data="casa_collections")],
            ]),
        )
    impostazioni = {
        "casa_bundle_frequency_": "frequenza_post",
        "casa_bundle_quantity_": "quantita",
        "casa_bundle_price_": "prezzo_massimo",
        "casa_bundle_discount_": "sconto_minimo",
    }
    for prefisso, chiave in impostazioni.items():
        if azione.startswith(prefisso):
            salva_config_raccolta(chiave, int(azione[len(prefisso):]))
            return await mostra_menu_raccolte_casa(query)
    if azione == "casa_bundle_quality":
        return await query.edit_message_text(
            "🎯 Qualità delle raccolte",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("SELETTIVA", callback_data="casa_bundle_quality_selettiva")],
                [InlineKeyboardButton("STANDARD", callback_data="casa_bundle_quality_standard")],
                [InlineKeyboardButton("⬅️ INDIETRO", callback_data="casa_collections")],
            ]),
        )
    if azione.startswith("casa_bundle_quality_"):
        salva_config_raccolta("qualita", azione.rsplit("_", 1)[1])
        return await mostra_menu_raccolte_casa(query)
    if azione == "casa_bundle_themes":
        return await mostra_temi_raccolte_casa(query)
    if azione.startswith("casa_bundle_theme_"):
        imposta_tema_raccolta(azione.replace("casa_bundle_theme_", "", 1))
        return await mostra_temi_raccolte_casa(query)
    if azione == "casa_bundle_test":
        return await testa_raccolta_casa(query, context)


async def mostra_menu_raccolte_tech(query):
    configurazione = leggi_config_raccolte_tech()
    stato = "🟢 ATTIVE" if configurazione["attive"] else "🔴 DISATTIVATE"
    qualita = configurazione["qualita"].upper()
    temi = [RACCOLTE_TECH_TEMI[x]["etichetta"] for x in configurazione["temi"]]
    await query.edit_message_text(
        "📦 RACCOLTE TECH\n\n"
        f"Stato: {stato}\n"
        f"Frequenza: ogni {configurazione['frequenza_post']} post TECH\n"
        f"Prodotti: {configurazione['quantita']}\n"
        f"Prezzo massimo: {configurazione['prezzo_massimo']} €\n"
        f"Sconto minimo: {configurazione['sconto_minimo']}%\n"
        f"Qualità: {qualita}\n"
        f"Temi: {', '.join(temi) if temi else 'nessuno'}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"STATO: {stato}", callback_data="tech_bundle_toggle")],
            [InlineKeyboardButton(
                f"🔁 OGNI {configurazione['frequenza_post']} POST TECH",
                callback_data="tech_bundle_frequency",
            )],
            [InlineKeyboardButton(
                f"📦 PRODOTTI: {configurazione['quantita']}",
                callback_data="tech_bundle_quantity",
            )],
            [InlineKeyboardButton(
                f"💶 PREZZO MASSIMO: {configurazione['prezzo_massimo']} €",
                callback_data="tech_bundle_price",
            )],
            [InlineKeyboardButton(
                f"📉 SCONTO MINIMO: {configurazione['sconto_minimo']}%",
                callback_data="tech_bundle_discount",
            )],
            [InlineKeyboardButton(
                f"🎯 QUALITÀ: {qualita}", callback_data="tech_bundle_quality"
            )],
            [InlineKeyboardButton("🗂 SCEGLI TEMI", callback_data="tech_bundle_themes")],
            [InlineKeyboardButton("🧪 TESTA RACCOLTA", callback_data="tech_bundle_test")],
            [InlineKeyboardButton("⬅️ TORNA ALL'AUTOMAZIONE TECH", callback_data="auto_menu")],
        ]),
    )


async def mostra_temi_raccolte_tech(query):
    selezionati = set(leggi_config_raccolte_tech()["temi"])
    tastiera = []
    for tema, dati in RACCOLTE_TECH_TEMI.items():
        segno = "✅" if tema in selezionati else "▫️"
        tastiera.append([InlineKeyboardButton(
            f"{segno} {dati['etichetta']}", callback_data=f"tech_bundle_theme_{tema}"
        )])
    tastiera.append([InlineKeyboardButton("✅ FATTO", callback_data="tech_collections")])
    await query.edit_message_text(
        "🗂 Scegli i temi delle raccolte. Ogni post conterrà prodotti dello stesso tema:",
        reply_markup=InlineKeyboardMarkup(tastiera),
    )


async def gestisci_raccolte_tech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    azione = query.data
    configurazione = leggi_config_raccolte_tech()

    if azione == "tech_collections":
        return await mostra_menu_raccolte_tech(query)
    if azione == "tech_bundle_toggle":
        if not configurazione["attive"] and not configurazione["temi"]:
            await query.message.reply_text("❌ Seleziona prima almeno un tema.")
            return
        salva_config_raccolta_tech("attive", 0 if configurazione["attive"] else 1)
        return await mostra_menu_raccolte_tech(query)
    menu_valori = {
        "tech_bundle_frequency": ("Ogni quanti post TECH?", (2, 4, 6, 8), "frequency", " POST"),
        "tech_bundle_quantity": ("Quanti prodotti nella raccolta?", (2, 4, 6), "quantity", ""),
        "tech_bundle_price": ("Prezzo massimo per prodotto", (40, 75, 150, 300), "price", " €"),
        "tech_bundle_discount": ("Sconto minimo", (5, 10, 15, 20), "discount", "%"),
    }
    if azione in menu_valori:
        titolo, valori, prefisso, suffisso = menu_valori[azione]
        return await query.edit_message_text(
            titolo,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"{valore}{suffisso}", callback_data=f"tech_bundle_{prefisso}_{valore}"
                ) for valore in valori],
                [InlineKeyboardButton("⬅️ INDIETRO", callback_data="tech_collections")],
            ]),
        )
    impostazioni = {
        "tech_bundle_frequency_": "frequenza_post",
        "tech_bundle_quantity_": "quantita",
        "tech_bundle_price_": "prezzo_massimo",
        "tech_bundle_discount_": "sconto_minimo",
    }
    for prefisso, chiave in impostazioni.items():
        if azione.startswith(prefisso):
            salva_config_raccolta_tech(chiave, int(azione[len(prefisso):]))
            return await mostra_menu_raccolte_tech(query)
    if azione == "tech_bundle_quality":
        return await query.edit_message_text(
            "🎯 Qualità delle raccolte",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("SELETTIVA", callback_data="tech_bundle_quality_selettiva")],
                [InlineKeyboardButton("STANDARD", callback_data="tech_bundle_quality_standard")],
                [InlineKeyboardButton("⬅️ INDIETRO", callback_data="tech_collections")],
            ]),
        )
    if azione.startswith("tech_bundle_quality_"):
        salva_config_raccolta_tech("qualita", azione.rsplit("_", 1)[1])
        return await mostra_menu_raccolte_tech(query)
    if azione == "tech_bundle_themes":
        return await mostra_temi_raccolte_tech(query)
    if azione.startswith("tech_bundle_theme_"):
        imposta_tema_raccolta_tech(azione.replace("tech_bundle_theme_", "", 1))
        return await mostra_temi_raccolte_tech(query)
    if azione == "tech_bundle_test":
        return await testa_raccolta_tech(query, context)


async def mostra_menu_selettiva(query, context):
    """Impostazioni selettive indipendenti per il canale scelto."""
    canale = _auto_canale_corrente(context)
    configurazione = leggi_config_automatica(canale)
    context.user_data["filtri_da_selettiva"] = True
    context.user_data["filtro_canale"] = canale
    nome_canale = "TECH" if canale == "tech" else "CASA"
    amazon = "ATTIVA" if configurazione["priorita_amazon"] else "DISATTIVATA"
    varianti = "ATTIVO" if configurazione["raggruppa_varianti"] else "DISATTIVO"
    await query.edit_message_text(
        f"⚙️ MODALITÀ SELETTIVA — {nome_canale}\n\n"
        "Il punteggio ordina i prodotti migliori; un articolo affidabile e pertinente "
        "può essere usato come riserva se non ci sono candidati sopra soglia.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏷 MARCHI AUTORIZZATI", callback_data="filter_brands")],
            [InlineKeyboardButton("🚫 PAROLE ESCLUSE", callback_data="filter_words")],
            [InlineKeyboardButton("🚀 PRODOTTI PRIORITARI", callback_data="priority_menu")],
            [InlineKeyboardButton(
                f"⭐ PUNTEGGIO PREFERITO: {configurazione['punteggio_minimo']}",
                callback_data="selective_score",
            )],
            [InlineKeyboardButton(
                f"📉 BONUS SCONTO: DAL {configurazione['bonus_sconto_da']}%",
                callback_data="selective_bonus",
            )],
            [InlineKeyboardButton(
                f"🏪 PRIORITÀ AMAZON: {amazon}", callback_data="selective_amazon"
            )],
            [InlineKeyboardButton(
                f"🔎 TENTATIVI RICERCA: {configurazione['tentativi_ricerca']}",
                callback_data="selective_searches",
            )],
            [InlineKeyboardButton(
                f"🧩 RAGGRUPPA VARIANTI: {varianti}", callback_data="selective_variants"
            )],
            [InlineKeyboardButton("♻️ RIPRISTINA CONSIGLIATI", callback_data="selective_reset")],
            [InlineKeyboardButton("⬅️ TORNA ALL'AUTOMAZIONE", callback_data="auto_menu")],
        ]),
    )


async def gestisci_selettiva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    azione = query.data
    canale = _auto_canale_corrente(context)
    configurazione = leggi_config_automatica(canale)

    if azione == "selective_menu":
        return await mostra_menu_selettiva(query, context)
    menu_valori = {
        "selective_score": ("Punteggio preferito", (3, 4, 5, 6, 7, 8), "selective_score"),
        "selective_bonus": ("Bonus +2 a partire dallo sconto", (20, 25, 30, 35, 40), "selective_bonus"),
        "selective_searches": ("Numero massimo di ricerche per invio", (3, 6, 9), "selective_searches"),
    }
    if azione in menu_valori:
        titolo, valori, prefisso = menu_valori[azione]
        suffisso = "%" if azione == "selective_bonus" else ""
        righe = []
        for indice in range(0, len(valori), 3):
            righe.append([
                InlineKeyboardButton(f"{valore}{suffisso}", callback_data=f"{prefisso}_{valore}")
                for valore in valori[indice:indice + 3]
            ])
        righe.append([InlineKeyboardButton("⬅️ INDIETRO", callback_data="selective_menu")])
        return await query.edit_message_text(titolo, reply_markup=InlineKeyboardMarkup(righe))

    modificata = False
    associazioni = {
        "selective_score_": "punteggio_minimo",
        "selective_bonus_": "bonus_sconto_da",
        "selective_searches_": "tentativi_ricerca",
    }
    for prefisso, chiave in associazioni.items():
        if azione.startswith(prefisso):
            salva_config_automatica(chiave, int(azione[len(prefisso):]), canale)
            modificata = True
            break
    if azione == "selective_amazon":
        salva_config_automatica("priorita_amazon", 0 if configurazione["priorita_amazon"] else 1, canale)
        modificata = True
    elif azione == "selective_variants":
        salva_config_automatica("raggruppa_varianti", 0 if configurazione["raggruppa_varianti"] else 1, canale)
        modificata = True
    elif azione == "selective_reset":
        return await query.edit_message_text(
            "Ripristinare i valori consigliati per questo canale?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ SÌ", callback_data="selective_reset_yes")],
                [InlineKeyboardButton("❌ ANNULLA", callback_data="selective_menu")],
            ]),
        )
    elif azione == "selective_reset_yes":
        for chiave, valore in {
            "punteggio_minimo": 4,
            "bonus_sconto_da": 30,
            "priorita_amazon": 1,
            "tentativi_ricerca": 6,
            "raggruppa_varianti": 1,
        }.items():
            salva_config_automatica(chiave, valore, canale)
        modificata = True
    if modificata:
        salva_config_automatica("attiva", 0, canale)
        salva_config_automatica("prossimo_invio", "", canale)
    await mostra_menu_selettiva(query, context)


def testo_automazione(configurazione, canale):
    categorie = [AUTO_CATEGORIE[x][0] for x in configurazione["categorie"] if x in AUTO_CATEGORIE]
    etichetta_qualita = (
        "Solo marche"
        if configurazione["qualita_prodotti"] == "marche"
        else configurazione["qualita_prodotti"].capitalize()
    )
    intestazione = "📱 TECH" if canale == "tech" else "🏠 CASA"
    return (
        f"🤖 INVIO AUTOMATICO — {intestazione}\n\n"
        f"Stato: {'🟢 Attivo' if configurazione['attiva'] else '🔴 Disattivato'}\n"
        f"Intervallo: {configurazione['intervallo_minuti']} minuti\n"
        f"Orario: {configurazione['ora_inizio']}–{configurazione['ora_fine']}\n"
        f"Sconto minimo: {configurazione['sconto_minimo']}%\n"
        f"Qualità prodotti: {etichetta_qualita}\n"
        f"Blocco duplicati: {configurazione['giorni_blocco_duplicati']} giorni\n"
        f"Categorie: {', '.join(categorie) if categorie else 'nessuna'}"
    )


async def menu_automazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    await aggiorna_menu_automazione(query, context)


async def seleziona_canale_automazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    context.user_data["auto_canale"] = query.data.rsplit("_", 1)[1]
    await aggiorna_menu_automazione(query, context)


async def mostra_canali_automazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Primo livello dell'invio automatico: stato dei canali collegati."""
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    config_tech = leggi_config_automatica("tech")
    config_casa = leggi_config_automatica("casa")
    stato_tech = "🟢 ATTIVO" if config_tech["attiva"] else "🔴 DISATTIVATO"
    stato_casa = "🟢 ATTIVO" if config_casa["attiva"] else "🔴 DISATTIVATO"
    await query.edit_message_text(
        "🤖 INVIO AUTOMATICO\n\n"
        "Seleziona il canale da gestire:\n\n"
        f"📱 TECH — {stato_tech}\n"
        f"🏠 CASA — {stato_casa}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📱 TECH — {stato_tech}", callback_data="auto_channel_tech")],
            [InlineKeyboardButton(f"🏠 CASA — {stato_casa}", callback_data="auto_channel_casa")],
            [InlineKeyboardButton("📊 STATO GENERALE", callback_data="auto_status")],
            [InlineKeyboardButton("⬅️ TORNA AL MENU PRINCIPALE", callback_data="menu_admin")],
        ]),
    )


async def mostra_stato_automazioni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    tech = leggi_config_automatica("tech")
    casa = leggi_config_automatica("casa")
    categorie_tech = [AUTO_CATEGORIE[x][0] for x in tech["categorie"]]
    categorie_casa = [AUTO_CATEGORIE[x][0] for x in casa["categorie"]]
    await query.edit_message_text(
        "📊 STATO GENERALE AUTOMAZIONI\n\n"
        f"📱 TECH: {'ATTIVO' if tech['attiva'] else 'DISATTIVATO'}\n"
        f"Intervallo: {tech['intervallo_minuti']} minuti · "
        f"{tech['ora_inizio']}–{tech['ora_fine']}\n"
        f"Categorie: {', '.join(categorie_tech) if categorie_tech else 'nessuna'}\n\n"
        f"🏠 CASA: {'ATTIVO' if casa['attiva'] else 'DISATTIVATO'}\n"
        f"Intervallo: {casa['intervallo_minuti']} minuti · "
        f"{casa['ora_inizio']}–{casa['ora_fine']}\n"
        f"Categorie: {', '.join(categorie_casa) if categorie_casa else 'nessuna'}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ TORNA AI CANALI", callback_data="auto_channels")]
        ]),
    )


async def mostra_stato_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    tech = leggi_config_automatica("tech")
    casa = leggi_config_automatica("casa")
    await query.edit_message_text(
        "📊 STATO DEL BOT\n\n"
        "Bot Telegram: ✅ AVVIATO\n"
        "Database: ✅ COLLEGATO\n"
        "Canale TECH: ✅ COLLEGATO\n"
        "Canale CASA: ✅ COLLEGATO\n"
        f"Automazione TECH: {'🟢 ATTIVA' if tech['attiva'] else '🔴 DISATTIVATA'}\n"
        f"Automazione CASA: {'🟢 ATTIVA' if casa['attiva'] else '🔴 DISATTIVATA'}\n\n"
        "Le due automazioni hanno impostazioni indipendenti.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ TORNA ALLE IMPOSTAZIONI", callback_data="settings_menu")]
        ]),
    )


async def aggiorna_menu_automazione(query, context):
    canale = _auto_canale_corrente(context)
    configurazione = leggi_config_automatica(canale)
    await query.edit_message_text(
        testo_automazione(configurazione, canale),
        reply_markup=tastiera_automazione(configurazione, canale),
    )


async def mostra_categorie_automatiche(query, context):
    canale = _auto_canale_corrente(context)
    selezionate = set(leggi_config_automatica(canale)["categorie"])
    consentite = TECH_CATEGORIE if canale == "tech" else CASA_CATEGORIE
    tastiera = []
    for codice, (etichetta, _) in AUTO_CATEGORIE.items():
        if codice not in consentite:
            continue
        segno = "✅" if codice in selezionate else "▫️"
        tastiera.append([
            InlineKeyboardButton(
                f"{segno} {etichetta.upper()}",
                callback_data=f"auto_cat_{codice}",
            )
        ])
    tastiera.append([InlineKeyboardButton("✅ FATTO", callback_data="auto_menu")])
    await query.edit_message_text(
        "🗂 Seleziona le categorie da pubblicare:",
        reply_markup=InlineKeyboardMarkup(tastiera),
    )


async def gestisci_automazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    azione = query.data
    canale = _auto_canale_corrente(context)
    configurazione = leggi_config_automatica(canale)

    if azione == "auto_toggle":
        if configurazione["attiva"]:
            salva_config_automatica("attiva", 0, canale)
            salva_config_automatica("prossimo_invio", "", canale)
            return await aggiorna_menu_automazione(query, context)

        if not configurazione["categorie"]:
            await query.message.reply_text("❌ Seleziona almeno una categoria.")
            return

        adesso = datetime.now(ROMA_TZ)
        salva_config_automatica("attiva", 1, canale)
        configurazione = leggi_config_automatica(canale)

        if _dentro_fascia_automatica(configurazione, adesso):
            prossimo = _calcola_prossimo_invio(configurazione, adesso)
            salva_config_automatica("prossimo_invio", prossimo.isoformat(timespec="seconds"), canale)
            await aggiorna_menu_automazione(query, context)
            await query.message.reply_text("🚀 Automazione attivata. Cerco subito la prima offerta…")
            await esegui_slot_automatico(
                context.application,
                configurazione,
                adesso.date().isoformat(),
                adesso.strftime("%H:%M"),
                canale,
            )
            return

        prossimo = _prossimo_inizio_fascia(configurazione, adesso)
        salva_config_automatica("prossimo_invio", prossimo.isoformat(timespec="seconds"), canale)
        await aggiorna_menu_automazione(query, context)
        await query.message.reply_text(
            f"✅ Automazione attivata. Il primo tentativo partirà alle {prossimo.strftime('%H:%M')}."
        )
        return

    if azione == "auto_duplicates":
        valori = (1, 3, 7, 10, 14, 30)
        tastiera = [
            [InlineKeyboardButton(f"{v} GIORNI", callback_data=f"auto_duplicates_{v}") for v in valori[:3]],
            [InlineKeyboardButton(f"{v} GIORNI", callback_data=f"auto_duplicates_{v}") for v in valori[3:]],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data="auto_menu")],
        ]
        await query.edit_message_text(
            "🔁 BLOCCO DUPLICATI\n\n"
            "Scegli dopo quanti giorni lo stesso prodotto potrà essere pubblicato "
            "nuovamente in questo canale.",
            reply_markup=InlineKeyboardMarkup(tastiera),
        )
        return

    if azione.startswith("auto_duplicates_"):
        giorni = int(azione.rsplit("_", 1)[1])
        salva_config_automatica("giorni_blocco_duplicati", giorni, canale)
        salva_config_automatica("attiva", 0, canale)
        salva_config_automatica("prossimo_invio", "", canale)
        await query.message.reply_text(
            f"✅ Blocco duplicati impostato a {giorni} giorni per "
            f"{'TECH' if canale == 'tech' else 'CASA'}.\n\n"
            "L’automazione è stata disattivata: riattivala dopo la modifica."
        )
        return await aggiorna_menu_automazione(query, context)

    if azione == "auto_sconto":
        valori = (10, 15, 20, 25, 30, 40, 50)
        tastiera = [
            [InlineKeyboardButton(f"{v}%", callback_data=f"auto_disc_{v}") for v in valori[:4]],
            [InlineKeyboardButton(f"{v}%", callback_data=f"auto_disc_{v}") for v in valori[4:]],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data="auto_menu")],
        ]
        await query.edit_message_text("📉 Seleziona lo sconto minimo:", reply_markup=InlineKeyboardMarkup(tastiera))
        return

    if azione == "auto_qualita":
        tastiera = InlineKeyboardMarkup([
            [InlineKeyboardButton("STANDARD", callback_data="auto_quality_standard")],
            [InlineKeyboardButton("SELETTIVA", callback_data="auto_quality_selettiva")],
            [InlineKeyboardButton("SOLO MARCHE", callback_data="auto_quality_marche")],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data="auto_menu")],
        ])
        await query.edit_message_text(
            "🎯 Seleziona la qualità dei prodotti:\n\n"
            "Standard: usa sconto e categoria.\n"
            "Selettiva: applica il punteggio qualità.\n"
            "Solo marche: accetta esclusivamente marchi autorizzati.",
            reply_markup=tastiera,
        )
        return

    if azione.startswith("auto_quality_"):
        modalita = azione.replace("auto_quality_", "", 1)
        if modalita not in {"standard", "selettiva", "marche"}:
            return
        salva_config_automatica("qualita_prodotti", modalita, canale)
        salva_config_automatica("attiva", 0, canale)
        return await aggiorna_menu_automazione(query, context)

    if azione.startswith("auto_disc_"):
        salva_config_automatica("sconto_minimo", int(azione.rsplit("_", 1)[1]), canale)
        salva_config_automatica("attiva", 0, canale)
        return await aggiorna_menu_automazione(query, context)

    if azione == "auto_categorie":
        return await mostra_categorie_automatiche(query, context)

    if azione.startswith("auto_cat_"):
        categoria = azione.replace("auto_cat_", "", 1)
        if categoria not in AUTO_CATEGORIE:
            return
        consentite = TECH_CATEGORIE if canale == "tech" else CASA_CATEGORIE
        if categoria not in consentite:
            return
        db = sqlite3.connect(DB_PATH)
        cur = db.cursor()
        cur.execute(
            "SELECT 1 FROM categorie_automatiche_canali WHERE canale = ? AND categoria = ?",
            (canale, categoria),
        )
        if cur.fetchone():
            cur.execute(
                "DELETE FROM categorie_automatiche_canali WHERE canale = ? AND categoria = ?",
                (canale, categoria),
            )
        else:
            cur.execute(
                "INSERT INTO categorie_automatiche_canali (canale, categoria) VALUES (?, ?)",
                (canale, categoria),
            )
        db.commit()
        db.close()
        salva_config_automatica("attiva", 0, canale)
        return await mostra_categorie_automatiche(query, context)


async def richiedi_intervallo_automatico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⏱ Intervallo tra i post\n\n"
        "Scrivi quanti minuti devono passare tra un post e l’altro.\n\n"
        "Esempio: 120\n\n"
        "Il minimo consentito è 29 minuti."
    )
    return AUTO_INTERVALLO


async def ricevi_intervallo_automatico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    try:
        minuti = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Scrivi soltanto il numero dei minuti, per esempio 120.")
        return AUTO_INTERVALLO
    if minuti < 29 or minuti > 1440:
        await update.message.reply_text("❌ Inserisci un valore tra 29 e 1440 minuti.")
        return AUTO_INTERVALLO
    canale = _auto_canale_corrente(context)
    salva_config_automatica("intervallo_minuti", minuti, canale)
    salva_config_automatica("attiva", 0, canale)
    configurazione = leggi_config_automatica(canale)
    await update.message.reply_text(
        f"✅ Intervallo salvato: {minuti} minuti.\n\n"
        "L’automazione resta disattivata finché non la riattivi.",
        reply_markup=tastiera_automazione(configurazione, canale),
    )
    return ConversationHandler.END


async def richiedi_fascia_automatica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🕒 Orario di attività\n\n"
        "Scrivi l’orario di inizio e quello di fine separati da un trattino.\n\n"
        "Esempio: 09:00-21:00\n\n"
        "Alle 21:00 il bot si fermerà."
    )
    return AUTO_FASCIA


async def ricevi_fascia_automatica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    testo = update.message.text.strip().replace("–", "-").replace("—", "-")
    parti = [x.strip() for x in testo.split("-")]
    if len(parti) != 2:
        await update.message.reply_text("❌ Usa il formato 09:00-21:00.")
        return AUTO_FASCIA
    try:
        inizio = datetime.strptime(parti[0], "%H:%M")
        fine = datetime.strptime(parti[1], "%H:%M")
    except ValueError:
        await update.message.reply_text("❌ Orario non corretto. Usa il formato 09:00-21:00.")
        return AUTO_FASCIA
    inizio_minuti = inizio.hour * 60 + inizio.minute
    fine_minuti = fine.hour * 60 + fine.minute
    if fine_minuti <= inizio_minuti:
        await update.message.reply_text("❌ L’orario finale deve essere successivo a quello iniziale.")
        return AUTO_FASCIA
    ora_inizio = inizio.strftime("%H:%M")
    ora_fine = fine.strftime("%H:%M")
    canale = _auto_canale_corrente(context)
    salva_config_automatica("ora_inizio", ora_inizio, canale)
    salva_config_automatica("ora_fine", ora_fine, canale)
    salva_config_automatica("attiva", 0, canale)
    configurazione = leggi_config_automatica(canale)
    await update.message.reply_text(
        f"✅ Orario salvato: dalle {ora_inizio} alle {ora_fine}.\n\n"
        f"Alle {ora_fine} il bot si fermerà.",
        reply_markup=tastiera_automazione(configurazione, canale),
    )
    return ConversationHandler.END


def estrai_prodotto_creators(item):
    """Converte un Item delle Creators API nel formato usato dal bot."""
    try:
        titolo = item.item_info.title.display_value
        immagine = item.images.primary.large.url
        link = item.detail_page_url
        asin = item.asin

        offerte = item.offers_v2.listings
        if not offerte:
            return None

        offerta = offerte[0]
        prezzo_api = offerta.price
        denaro = prezzo_api.money
        if not denaro or denaro.amount is None:
            return None

        prezzo_valore = float(denaro.amount)
        prezzo = denaro.display_amount or f"{prezzo_valore:.2f} €"
        vecchio_prezzo = None
        vecchio_valore = None

        base = prezzo_api.saving_basis
        if base and base.money and base.money.amount is not None:
            vecchio_valore = float(base.money.amount)
            vecchio_prezzo = base.money.display_amount or f"{vecchio_valore:.2f} €"

        sconto = 0
        if prezzo_api.savings and prezzo_api.savings.percentage is not None:
            sconto = round(float(prezzo_api.savings.percentage))
        elif vecchio_valore and vecchio_valore > prezzo_valore:
            sconto = round((1 - prezzo_valore / vecchio_valore) * 100)

        if not all((titolo, immagine, link, asin)):
            return None

        venditore = None
        if offerta.merchant_info and offerta.merchant_info.name:
            venditore = offerta.merchant_info.name.strip()

        marchio = None
        info_linea = getattr(item.item_info, "by_line_info", None)
        attributo_marchio = getattr(info_linea, "brand", None)
        if attributo_marchio and getattr(attributo_marchio, "display_value", None):
            marchio = attributo_marchio.display_value.strip()
        if not marchio:
            produttore = getattr(info_linea, "manufacturer", None)
            if produttore and getattr(produttore, "display_value", None):
                marchio = produttore.display_value.strip()

        deal_end_time = None
        if offerta.deal_details and offerta.deal_details.end_time:
            deal_end_time = offerta.deal_details.end_time

        return {
            "asin": asin,
            "nome": titolo,
            "prezzo": prezzo,
            "prezzo_valore": prezzo_valore,
            "vecchio_prezzo": vecchio_prezzo,
            "vecchio_valore": vecchio_valore,
            "sconto": sconto,
            "immagine": immagine,
            "link": link,
            "venditore": venditore,
            "marchio": marchio,
            "deal_end_time": deal_end_time,
        }
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def riga_venditore_categoria(prodotto, categoria):
    hashtag = AUTO_HASHTAG.get(categoria, "#OfferteAmazon")
    venditore = prodotto.get("venditore")
    if venditore and "amazon" in venditore.lower():
        # Le Creators API espongono il venditore, ma non garantiscono sempre
        # un campo separato e affidabile per il gestore della spedizione.
        return f"Venduto da <i>Amazon</i> - Categoria: {hashtag}"
    return f"Categoria: {hashtag}"


def _normalizza_qualita(valore):
    testo = unicodedata.normalize("NFKD", str(valore or ""))
    testo = "".join(carattere for carattere in testo if not unicodedata.combining(carattere))
    return re.sub(r"[^a-z0-9+ -]+", "", testo.lower()).strip()


def _testo_contiene_termine(testo, termine):
    """Cerca parole o frasi complete evitando corrispondenze accidentali."""
    testo = _normalizza_qualita(testo)
    termine = _normalizza_qualita(termine)
    if not termine:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(termine)}(?![a-z0-9])", testo))


def carica_snapshot_filtri(categoria=None, configurazione=None):
    """Legge una sola volta dal database tutti i filtri usati nella ricerca."""
    configurazione = configurazione or leggi_config_automatica()
    categorie = [categoria] if categoria else list(AUTO_CATEGORIE)
    return {
        "configurazione": configurazione,
        "marchi": {
            nome: {_normalizza_qualita(x) for x in leggi_marchi_qualita(nome)}
            for nome in categorie
        },
        "indesiderate": tuple(leggi_parole_indesiderate()),
        "priorita": {
            nome: tuple(leggi_prodotti_prioritari(nome))
            for nome in categorie
        },
        "accessori": tuple(leggi_parole_accessori_priorita()),
    }


def valuta_priorita_prodotto(prodotto, categoria, snapshot=None):
    """Restituisce bonus e nome della priorità; gli accessori non ricevono bonus."""
    titolo = _normalizza_qualita(prodotto.get("nome"))
    marchio = _normalizza_qualita(prodotto.get("marchio"))
    snapshot = snapshot or carica_snapshot_filtri(categoria)
    parole_accessori = snapshot["accessori"]
    if any(_testo_contiene_termine(titolo, parola) for parola in parole_accessori):
        return 0, None

    migliore_bonus = 0
    migliore_nome = None
    for _, _, parola, marchio_richiesto, bonus in snapshot["priorita"].get(categoria, ()):
        parola_norm = _normalizza_qualita(parola)
        parola_presente = _testo_contiene_termine(titolo, parola_norm)
        alias_richiesti = {
            _normalizza_qualita(alias)
            for parte_originale in str(marchio_richiesto).split("|")
            for parte in [_normalizza_qualita(parte_originale)]
            for alias in MARCHI_ALIAS_PRIORITA.get(parte, {parte})
            if parte
        }
        marchio_corretto = any(
            marchio == alias or (len(alias) >= 4 and alias in marchio)
            for alias in alias_richiesti
        )
        if parola_presente and marchio_corretto and bonus > migliore_bonus:
            migliore_bonus = int(bonus)
            migliore_nome = parola
    return migliore_bonus, migliore_nome


def valuta_qualita_prodotto(
    prodotto, categoria, modalita, snapshot=None, bonus_priorita=0
):
    """Restituisce approvazione, punteggio e motivazioni, senza filtri di prezzo."""
    modalita = modalita if modalita in {"standard", "selettiva", "marche"} else "selettiva"
    if modalita == "standard":
        return True, 0, ["Modalità standard: nessun filtro qualità"]

    titolo = _normalizza_qualita(prodotto.get("nome"))
    marchio = _normalizza_qualita(prodotto.get("marchio"))
    venditore = _normalizza_qualita(prodotto.get("venditore"))
    snapshot = snapshot or carica_snapshot_filtri(categoria)
    configurazione = snapshot["configurazione"]
    autorizzati = snapshot["marchi"].get(categoria, set())
    marchio_noto = bool(marchio) and any(
        marchio == candidato or (len(candidato) >= 4 and candidato in marchio)
        for candidato in autorizzati
    )
    venduto_amazon = "amazon" in venditore
    indesiderate = [
        parola for parola in snapshot["indesiderate"]
        if _testo_contiene_termine(titolo, parola)
    ]
    pertinente = any(
        _testo_contiene_termine(titolo, parola)
        for parola in PAROLE_CATEGORIA.get(categoria, set())
    )

    punteggio = 0
    motivi = []
    if marchio_noto:
        punteggio += 2
        motivi.append("marchio conosciuto +2")
    elif not marchio:
        punteggio -= 2
        motivi.append("marchio assente -2")
    else:
        motivi.append("marchio non presente nella lista +0")
    if venduto_amazon and configurazione["priorita_amazon"]:
        punteggio += 3
        motivi.append("venduto da Amazon +3")
    if prodotto.get("sconto", 0) >= configurazione["bonus_sconto_da"]:
        punteggio += 2
        motivi.append(f"sconto almeno {configurazione['bonus_sconto_da']}% +2")
    if pertinente:
        punteggio += 1
        motivi.append("titolo pertinente +1")
    if bonus_priorita:
        punteggio += int(bonus_priorita)
        motivi.append(f"prodotto prioritario +{int(bonus_priorita)}")
    if indesiderate:
        punteggio -= 3
        motivi.append(f"parole indesiderate -3: {', '.join(indesiderate)}")

    if modalita == "marche":
        approvato = marchio_noto and not indesiderate
    else:
        # In selettiva la soglia serve soprattutto a ordinare. Blocchiamo solo
        # articoli indesiderati, non pertinenti o senza alcun segnale affidabile.
        affidabile = marchio_noto or venduto_amazon or bonus_priorita > 0
        coerente = pertinente or bonus_priorita > 0
        approvato = affidabile and coerente and not indesiderate
    return approvato, punteggio, motivi


def crea_immagine_brandizzata_da_bytes(contenuto):
    """Applica la grafica BestPrice24h ai byte di una foto prodotto."""
    prodotto = Image.open(BytesIO(contenuto)).convert("RGB")
    canvas = Image.new("RGB", (1080, 1080), "white")

    # Margine bianco uniforme del 16% su tutti i lati del prodotto.
    area_prodotto = (734, 734)
    margine_prodotto = 173
    foto = ImageOps.contain(
        prodotto,
        area_prodotto,
        method=Image.Resampling.LANCZOS,
    )
    posizione_foto = (
        margine_prodotto + (area_prodotto[0] - foto.width) // 2,
        margine_prodotto + (area_prodotto[1] - foto.height) // 2,
    )
    canvas.paste(foto, posizione_foto)

    # Cornice rossa sottile, profilo nero e nessuna ombra esterna.
    disegno = ImageDraw.Draw(canvas)
    disegno.rounded_rectangle(
        (8, 8, 1072, 1072), radius=40, outline="#F20D18", width=18
    )
    disegno.rounded_rectangle(
        (26, 26, 1054, 1054), radius=22, outline="#171717", width=3
    )

    if not LOGO_PATH.exists():
        raise FileNotFoundError(f"Logo non trovato: {LOGO_PATH}")

    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo = ImageOps.contain(logo, (195, 170), Image.Resampling.LANCZOS)
    # Logo BestPrice24h al 59% circa di opacità.
    alpha_logo = logo.getchannel("A").point(lambda valore: valore * 150 // 255)
    logo.putalpha(alpha_logo)
    # Margine del logo: 10 px dal profilo nero, in alto e a destra.
    posizione_logo = (1044 - logo.width, 36)

    # Il logo è opaco; solo una piccola ombra ne migliora la leggibilità.
    alpha_ombra = logo.getchannel("A").point(lambda valore: valore * 90 // 255)
    sagoma_nera = Image.new("RGBA", logo.size, (0, 0, 0, 0))
    sagoma_nera.putalpha(alpha_ombra)
    ombra = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ombra.paste(
        sagoma_nera,
        (posizione_logo[0] + 5, posizione_logo[1] + 6),
        sagoma_nera,
    )
    ombra = ombra.filter(ImageFilter.GaussianBlur(6))

    canvas = Image.alpha_composite(canvas.convert("RGBA"), ombra)
    canvas.alpha_composite(logo, posizione_logo)

    # Logo Amazon originale, centrato nel margine bianco inferiore.
    if AMAZON_LOGO_PATH.exists():
        logo_amazon = Image.open(AMAZON_LOGO_PATH).convert("RGBA")
        # Rende trasparente soltanto lo sfondo bianco del file fornito.
        pixel = []
        for rosso, verde, blu, alpha in logo_amazon.getdata():
            if rosso >= 245 and verde >= 245 and blu >= 245:
                pixel.append((rosso, verde, blu, 0))
            else:
                pixel.append((rosso, verde, blu, alpha))
        logo_amazon.putdata(pixel)
        logo_amazon = ImageOps.contain(
            logo_amazon,
            (220, 92),
            Image.Resampling.LANCZOS,
        )
        posizione_amazon = (
            (1080 - logo_amazon.width) // 2,
            1010 - logo_amazon.height,
        )
        canvas.alpha_composite(logo_amazon, posizione_amazon)

    output = BytesIO()
    output.name = "offerta_bestprice24h.jpg"
    canvas.convert("RGB").save(
        output,
        format="JPEG",
        quality=93,
        optimize=True,
    )
    output.seek(0)
    return output


def crea_immagine_brandizzata(image_url):
    """Scarica la foto Amazon e aggiunge cornice e loghi."""
    risposta = requests.get(image_url, timeout=20)
    risposta.raise_for_status()
    return crea_immagine_brandizzata_da_bytes(risposta.content)


async def prepara_foto_automatica(image_url):
    """Crea la grafica senza bloccare il bot; in errore usa la foto originale."""
    try:
        return await asyncio.to_thread(crea_immagine_brandizzata, image_url)
    except Exception as errore:
        print(f"Impossibile creare immagine brandizzata: {errore}")
        return image_url


def _tema_raccolta_successivo(configurazione):
    temi = [tema for tema in configurazione["temi"] if tema in RACCOLTE_CASA_TEMI]
    if not temi:
        return None
    indice = configurazione["indice_tema"] % len(temi)
    salva_config_raccolta("indice_tema", (indice + 1) % len(temi))
    return temi[indice]


def _prodotto_valido_per_raccolta(
    prodotto,
    tema,
    configurazione,
    parole_indesiderate=None,
    marchi_casa=None,
):
    if not prodotto or prodotto.get("prezzo_valore") is None:
        return False
    if float(prodotto["prezzo_valore"]) > configurazione["prezzo_massimo"]:
        return False
    if int(prodotto.get("sconto") or 0) < configurazione["sconto_minimo"]:
        return False
    titolo = _normalizza_qualita(prodotto.get("nome"))
    marchio = _normalizza_qualita(prodotto.get("marchio"))
    venditore = _normalizza_qualita(prodotto.get("venditore"))
    parole_indesiderate = (
        leggi_parole_indesiderate()
        if parole_indesiderate is None else parole_indesiderate
    )
    if any(_testo_contiene_termine(titolo, parola) for parola in parole_indesiderate):
        return False
    pertinente = any(
        _testo_contiene_termine(titolo, parola)
        for parola in RACCOLTE_CASA_TEMI[tema]["parole"]
    )
    if not pertinente:
        return False
    if configurazione["qualita"] == "standard":
        return True
    marchi_casa = (
        {_normalizza_qualita(x) for x in leggi_marchi_qualita("casa")}
        if marchi_casa is None else marchi_casa
    )
    marchi_raccolte = {_normalizza_qualita(x) for x in MARCHI_RACCOLTE_CASA}
    marchio_noto = bool(marchio) and any(
        marchio == candidato or (len(candidato) >= 4 and candidato in marchio)
        for candidato in marchi_casa | marchi_raccolte
    )
    return marchio_noto or "amazon" in venditore


async def cerca_prodotti_raccolta_casa(configurazione, tema):
    trovati = {}
    giorni_blocco = leggi_config_automatica("casa")["giorni_blocco_duplicati"]
    statistiche = {"ricerche": 0, "analizzati": 0, "prezzo_sconto": 0, "qualita": 0, "duplicati": 0}
    parole_indesiderate = leggi_parole_indesiderate()
    marchi_casa = {_normalizza_qualita(x) for x in leggi_marchi_qualita("casa")}
    for termine in RACCOLTE_CASA_TEMI[tema]["termini"]:
        statistiche["ricerche"] += 1
        try:
            items = await asyncio.to_thread(search_items, termine, "All", 10)
        except Exception as errore:
            print(f"Errore ricerca raccolta CASA ({tema} - {termine}): {errore}")
            continue
        for item in items:
            statistiche["analizzati"] += 1
            prodotto = estrai_prodotto_creators(item)
            if not prodotto:
                continue
            if (
                float(prodotto.get("prezzo_valore") or 0) > configurazione["prezzo_massimo"]
                or int(prodotto.get("sconto") or 0) < configurazione["sconto_minimo"]
            ):
                statistiche["prezzo_sconto"] += 1
                continue
            if _asin_gia_pubblicato(prodotto.get("asin"), giorni_blocco, "casa"):
                statistiche["duplicati"] += 1
                continue
            if not _prodotto_valido_per_raccolta(
                prodotto,
                tema,
                configurazione,
                parole_indesiderate=parole_indesiderate,
                marchi_casa=marchi_casa,
            ):
                statistiche["qualita"] += 1
                continue
            prodotto["categoria"] = "casa"
            prodotto["tema_raccolta"] = tema
            trovati[prodotto["asin"]] = prodotto
        if len(trovati) >= configurazione["quantita"] * 2:
            break
        await asyncio.sleep(1.0)

    candidati = _raggruppa_varianti_prodotti(list(trovati.values()))
    candidati.sort(
        key=lambda p: (int(p.get("sconto") or 0), -float(p.get("prezzo_valore") or 0)),
        reverse=True,
    )
    selezionati = []
    marchi_usati = set()
    for prodotto in candidati:
        marchio = _normalizza_qualita(prodotto.get("marchio"))
        chiave_marchio = marchio or _normalizza_qualita(prodotto.get("nome")).split(" ")[0]
        if chiave_marchio in marchi_usati:
            continue
        marchi_usati.add(chiave_marchio)
        selezionati.append(prodotto)
        if len(selezionati) >= configurazione["quantita"]:
            break
    return selezionati, statistiche


def crea_collage_raccolta_casa(prodotti, tema):
    canvas = Image.new("RGB", (1080, 1080), "white")
    disegno = ImageDraw.Draw(canvas)
    disegno.rounded_rectangle((8, 8, 1072, 1072), radius=40, outline="#F20D18", width=18)
    disegno.rounded_rectangle((26, 26, 1054, 1054), radius=22, outline="#171717", width=3)
    # Numerazione grande e semplice, senza bollino o cerchio.
    font_numero = _font_terminata(35)

    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo = ImageOps.contain(logo, (155, 125), Image.Resampling.LANCZOS)
        # Stessa trasparenza dei post singoli: alpha 150 su 255.
        alpha_logo = logo.getchannel("A").point(
            lambda valore: valore * 150 // 255
        )
        logo.putalpha(alpha_logo)
        canvas.paste(logo, (1028 - logo.width, 30), logo)

    colonne = 3 if len(prodotti) > 4 else 2
    righe = 2 if len(prodotti) > 2 else 1
    # La griglia termina prima del logo Amazon, lasciando una fascia bianca.
    alto_griglia = 780
    larghezza_cella = 1000 // colonne
    altezza_cella = alto_griglia // righe
    for indice, prodotto in enumerate(prodotti):
        colonna = indice % colonne
        riga = indice // colonne
        x0 = 40 + colonna * larghezza_cella
        y0 = 155 + riga * altezza_cella
        x1 = x0 + larghezza_cella - 12
        y1 = y0 + altezza_cella - 12
        disegno.rounded_rectangle(
            (x0, y0, x1, y1), radius=25, fill="#FFFFFF", outline="#E5E5E5", width=3
        )
        try:
            risposta = requests.get(prodotto["immagine"], timeout=15)
            risposta.raise_for_status()
            foto = Image.open(BytesIO(risposta.content)).convert("RGB")
            foto = ImageOps.contain(
                foto,
                (larghezza_cella - 90, altezza_cella - 90),
                Image.Resampling.LANCZOS,
            )
            posizione = (
                x0 + (larghezza_cella - 12 - foto.width) // 2,
                y0 + (altezza_cella - 12 - foto.height) // 2,
            )
            canvas.paste(foto, posizione)
        except Exception as errore:
            print(f"Immagine raccolta non disponibile: {errore}")

        numero = f"#{indice + 1}"
        disegno.text(
            (x0 + 20, y0 + 16),
            numero,
            font=font_numero,
            fill="#171717",
            stroke_width=4,
            stroke_fill="white",
        )

    # Stesso logo Amazon dei post singoli, centrato nella fascia inferiore.
    if AMAZON_LOGO_PATH.exists():
        logo_amazon = Image.open(AMAZON_LOGO_PATH).convert("RGBA")
        pixel = []
        for rosso, verde, blu, alpha in logo_amazon.getdata():
            if rosso >= 245 and verde >= 245 and blu >= 245:
                pixel.append((rosso, verde, blu, 0))
            else:
                pixel.append((rosso, verde, blu, alpha))
        logo_amazon.putdata(pixel)
        logo_amazon = ImageOps.contain(
            logo_amazon,
            (220, 92),
            Image.Resampling.LANCZOS,
        )
        posizione_amazon = (
            (1080 - logo_amazon.width) // 2,
            1040 - logo_amazon.height,
        )
        canvas.paste(logo_amazon, posizione_amazon, logo_amazon)

    output = BytesIO()
    output.name = "raccolta_casa_bestprice24h.jpg"
    canvas.save(output, "JPEG", quality=92, optimize=True)
    output.seek(0)
    return output

def _prezzo_caption_raccolta(valore):
    testo = str(valore or "—").strip()
    return testo if testo == "—" or "€" in testo else f"{testo} €"


def crea_caption_raccolta_casa(prodotti, tema, anteprima=False):
    intestazione = "🧪 <b>ANTEPRIMA — " if anteprima else "🧺 <b>"
    righe = [intestazione + RACCOLTE_CASA_TEMI[tema]["titolo"] + "</b>"]
    for indice, prodotto in enumerate(prodotti, start=1):
        nome = accorcia_nome_articolo(prodotto["nome"])
        if len(nome) > 52:
            nome = nome[:49].rsplit(" ", 1)[0] + "…"
        link = html.escape(prodotto["link"], quote=True)
        if prodotto.get("stato") == "terminata":
            righe.append(
                f'#{indice} 🔴 <s><a href="{link}">{html.escape(nome)}</a></s>\n'
                "<b>OFFERTA TERMINATA</b>"
            )
            continue
        prima = _prezzo_caption_raccolta(prodotto.get("vecchio_prezzo"))
        ora = _prezzo_caption_raccolta(prodotto.get("prezzo"))
        righe.append(
            f'#{indice} <a href="{link}">{html.escape(nome)}</a>\n'
            f'❌ Prima: <s>{html.escape(prima)}</s>\n'
            f'✅ Ora: <b>{html.escape(ora)}</b>'
        )
    righe.append("⚡ Prezzi e disponibilità possono variare.")
    if anteprima:
        righe.append("Anteprima non pubblicata")
    return "\n\n".join(righe)


def tastiera_raccolta_casa():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 CLUB", url="https://t.me/BestPrice24h_bot"),
        InlineKeyboardButton("🏠 CANALE CASA", url=CASA_CHANNEL_URL),
    ]])


def salva_raccolta_casa(prodotti, tema, messaggio_telegram, foto_file_id):
    adesso = datetime.now(ROMA_TZ).isoformat(timespec="seconds")
    db = sqlite3.connect(DB_PATH)
    cursore = db.execute(
        """
        INSERT INTO raccolte_casa (
            tema, telegram_chat_id, telegram_message_id, telegram_photo_file_id,
            pubblicata_il, stato
        ) VALUES (?, ?, ?, ?, ?, 'pubblicata')
        """,
        (tema, str(CASA_CHANNEL_ID), messaggio_telegram.message_id, foto_file_id, adesso),
    )
    raccolta_id = cursore.lastrowid
    for posizione, prodotto in enumerate(prodotti, start=1):
        db.execute(
            """
            INSERT INTO raccolte_casa_prodotti (
                raccolta_id, posizione, asin, nome, link, prezzo, vecchio_prezzo,
                immagine_url, sconto, stato, ultima_verifica
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pubblicata', ?)
            """,
            (
                raccolta_id, posizione, prodotto["asin"], prodotto["nome"],
                prodotto["link"], prodotto.get("prezzo"), prodotto.get("vecchio_prezzo"),
                prodotto.get("immagine"), int(prodotto.get("sconto") or 0), adesso,
            ),
        )
    db.commit()
    db.close()
    for prodotto in prodotti:
        salva_offerta_recap(
            prodotto["nome"], prodotto["link"], prodotto.get("prezzo"),
            prodotto.get("vecchio_prezzo") or "NO", messaggio=crea_caption_raccolta_casa(prodotti, tema),
            foto_file_id=foto_file_id, template="raccolta", asin=prodotto.get("asin"),
            categoria=tema, telegram_chat_id=CASA_CHANNEL_ID, origine="raccolta",
            sconto=prodotto.get("sconto", 0), telegram_message_id=messaggio_telegram.message_id,
        )
    return raccolta_id


async def pubblica_raccolta_casa(bot, prodotti, tema):
    collage = await asyncio.to_thread(crea_collage_raccolta_casa, prodotti, tema)
    caption = crea_caption_raccolta_casa(prodotti, tema)
    messaggio = await bot.send_photo(
        chat_id=CASA_CHANNEL_ID,
        photo=collage,
        caption=caption,
        parse_mode="HTML",
        reply_markup=tastiera_raccolta_casa(),
    )
    foto_file_id = messaggio.photo[-1].file_id if messaggio.photo else None
    salva_raccolta_casa(prodotti, tema, messaggio, foto_file_id)
    return messaggio


async def testa_raccolta_casa(query, context):
    configurazione = leggi_config_raccolte_casa()
    tema = _tema_raccolta_successivo(configurazione)
    if not tema:
        await query.message.reply_text("❌ Seleziona almeno un tema.")
        return
    attesa = await query.message.reply_text(
        f"🔎 Cerco una raccolta {RACCOLTE_CASA_TEMI[tema]['etichetta']}…"
    )
    prodotti, statistiche = await cerca_prodotti_raccolta_casa(configurazione, tema)
    if len(prodotti) < 2:
        await attesa.edit_text(
            "ℹ️ Non ho trovato almeno 2 prodotti validi.\n\n"
            f"Ricerche: {statistiche['ricerche']} · analizzati: {statistiche['analizzati']}\n"
            f"Prezzo/sconto: {statistiche['prezzo_sconto']} · qualità: {statistiche['qualita']} "
            f"· duplicati: {statistiche['duplicati']}"
        )
        return
    await attesa.delete()
    collage = await asyncio.to_thread(crea_collage_raccolta_casa, prodotti, tema)
    await query.message.reply_photo(
        photo=collage,
        caption=crea_caption_raccolta_casa(prodotti, tema, anteprima=True),
        parse_mode="HTML",
    )


def raccolta_casa_pronta(configurazione):
    """La raccolta è pronta ogni N post CASA, senza alcun limite giornaliero."""
    db = sqlite3.connect(DB_PATH)
    ultima = db.execute(
        "SELECT pubblicata_il FROM raccolte_casa ORDER BY pubblicata_il DESC LIMIT 1"
    ).fetchone()
    condizioni = ["telegram_chat_id=?", "COALESCE(origine,'manuale')<>'raccolta'"]
    parametri = [str(CASA_CHANNEL_ID)]
    if ultima:
        condizioni.append("pubblicata_il>?")
        parametri.append(ultima[0])
    post_da_ultima = db.execute(
        f"SELECT COUNT(*) FROM recap_offerte WHERE {' AND '.join(condizioni)}", parametri
    ).fetchone()[0]
    db.close()
    return post_da_ultima >= configurazione["frequenza_post"]


async def tenta_pubblicazione_raccolta_casa(bot):
    """Tenta la raccolta dopo qualsiasi post CASA, senza avvii sovrapposti."""
    if RACCOLTA_CASA_LOCK.locked():
        return False
    async with RACCOLTA_CASA_LOCK:
        configurazione = leggi_config_raccolte_casa()
        if not configurazione["attive"] or not raccolta_casa_pronta(configurazione):
            return False
        tema = _tema_raccolta_successivo(configurazione)
        if not tema:
            return False
        salva_config_raccolta(
            "ultimo_tentativo",
            datetime.now(ROMA_TZ).isoformat(timespec="seconds"),
        )
        prodotti, statistiche = await cerca_prodotti_raccolta_casa(
            configurazione, tema
        )
        if len(prodotti) < 2:
            await _notifica_admin_automazione(
                bot,
                f"ℹ️ Raccolta CASA {RACCOLTE_CASA_TEMI[tema]['etichetta']} rimandata: "
                f"trovati {len(prodotti)} prodotti validi dopo "
                f"{statistiche['ricerche']} ricerche. "
                "Il conteggio resta valido e riproverò dopo il prossimo post CASA.",
            )
            return False
        await pubblica_raccolta_casa(bot, prodotti, tema)
        await _notifica_admin_automazione(
            bot,
            f"✅ Raccolta CASA pubblicata: {RACCOLTE_CASA_TEMI[tema]['titolo']} "
            f"({len(prodotti)} prodotti).",
        )
        return True


async def controlla_raccolta_dopo_post_casa(bot):
    """Il fallimento della raccolta non deve annullare il post singolo già inviato."""
    try:
        return await tenta_pubblicazione_raccolta_casa(bot)
    except Exception as errore:
        print(f"Errore controllo raccolta dopo post CASA: {errore}")
        await _notifica_admin_automazione(
            bot,
            f"⚠️ Il post CASA è stato pubblicato, ma il controllo della raccolta "
            f"non è riuscito: {str(errore)[:500]}",
        )
        return False

def _tema_raccolta_successivo_tech(configurazione):
    temi = [tema for tema in configurazione["temi"] if tema in RACCOLTE_TECH_TEMI]
    if not temi:
        return None
    indice = configurazione["indice_tema"] % len(temi)
    salva_config_raccolta_tech("indice_tema", (indice + 1) % len(temi))
    return temi[indice]


def _prodotto_valido_per_raccolta_tech(
    prodotto,
    tema,
    configurazione,
    parole_indesiderate=None,
    marchi_tech=None,
):
    if not prodotto or prodotto.get("prezzo_valore") is None:
        return False
    if float(prodotto["prezzo_valore"]) > configurazione["prezzo_massimo"]:
        return False
    if int(prodotto.get("sconto") or 0) < configurazione["sconto_minimo"]:
        return False
    titolo = _normalizza_qualita(prodotto.get("nome"))
    marchio = _normalizza_qualita(prodotto.get("marchio"))
    venditore = _normalizza_qualita(prodotto.get("venditore"))
    parole_indesiderate = (
        leggi_parole_indesiderate()
        if parole_indesiderate is None else parole_indesiderate
    )
    if any(_testo_contiene_termine(titolo, parola) for parola in parole_indesiderate):
        return False
    pertinente = any(
        _testo_contiene_termine(titolo, parola)
        for parola in RACCOLTE_TECH_TEMI[tema]["parole"]
    )
    if not pertinente:
        return False
    if configurazione["qualita"] == "standard":
        return True
    marchi_tech = (
        {
            _normalizza_qualita(x)
            for categoria in TECH_CATEGORIE
            for x in leggi_marchi_qualita(categoria)
        }
        if marchi_tech is None else marchi_tech
    )
    marchi_raccolte = {_normalizza_qualita(x) for x in MARCHI_RACCOLTE_TECH}
    marchio_noto = bool(marchio) and any(
        marchio == candidato or (len(candidato) >= 4 and candidato in marchio)
        for candidato in marchi_tech | marchi_raccolte
    )
    return marchio_noto or "amazon" in venditore


async def cerca_prodotti_raccolta_tech(configurazione, tema):
    trovati = {}
    giorni_blocco = leggi_config_automatica("tech")["giorni_blocco_duplicati"]
    statistiche = {"ricerche": 0, "analizzati": 0, "prezzo_sconto": 0, "qualita": 0, "duplicati": 0}
    parole_indesiderate = leggi_parole_indesiderate()
    marchi_tech = {
        _normalizza_qualita(x)
        for categoria in TECH_CATEGORIE
        for x in leggi_marchi_qualita(categoria)
    }
    for termine in RACCOLTE_TECH_TEMI[tema]["termini"]:
        statistiche["ricerche"] += 1
        try:
            items = await asyncio.to_thread(search_items, termine, "All", 10)
        except Exception as errore:
            print(f"Errore ricerca raccolta TECH ({tema} - {termine}): {errore}")
            continue
        for item in items:
            statistiche["analizzati"] += 1
            prodotto = estrai_prodotto_creators(item)
            if not prodotto:
                continue
            if (
                float(prodotto.get("prezzo_valore") or 0) > configurazione["prezzo_massimo"]
                or int(prodotto.get("sconto") or 0) < configurazione["sconto_minimo"]
            ):
                statistiche["prezzo_sconto"] += 1
                continue
            if _asin_gia_pubblicato(prodotto.get("asin"), giorni_blocco, "tech"):
                statistiche["duplicati"] += 1
                continue
            if not _prodotto_valido_per_raccolta_tech(
                prodotto,
                tema,
                configurazione,
                parole_indesiderate=parole_indesiderate,
                marchi_tech=marchi_tech,
            ):
                statistiche["qualita"] += 1
                continue
            prodotto["categoria"] = "tech"
            prodotto["tema_raccolta"] = tema
            trovati[prodotto["asin"]] = prodotto
        if len(trovati) >= configurazione["quantita"] * 2:
            break
        await asyncio.sleep(1.0)

    candidati = _raggruppa_varianti_prodotti(list(trovati.values()))
    candidati.sort(
        key=lambda p: (int(p.get("sconto") or 0), -float(p.get("prezzo_valore") or 0)),
        reverse=True,
    )
    selezionati = []
    marchi_usati = set()
    for prodotto in candidati:
        marchio = _normalizza_qualita(prodotto.get("marchio"))
        chiave_marchio = marchio or _normalizza_qualita(prodotto.get("nome")).split(" ")[0]
        if chiave_marchio in marchi_usati:
            continue
        marchi_usati.add(chiave_marchio)
        selezionati.append(prodotto)
        if len(selezionati) >= configurazione["quantita"]:
            break
    return selezionati, statistiche


def crea_collage_raccolta_tech(prodotti, tema):
    canvas = Image.new("RGB", (1080, 1080), "white")
    disegno = ImageDraw.Draw(canvas)
    disegno.rounded_rectangle((8, 8, 1072, 1072), radius=40, outline="#F20D18", width=18)
    disegno.rounded_rectangle((26, 26, 1054, 1054), radius=22, outline="#171717", width=3)
    # Numerazione grande e semplice, senza bollino o cerchio.
    font_numero = _font_terminata(35)

    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo = ImageOps.contain(logo, (155, 125), Image.Resampling.LANCZOS)
        # Stessa trasparenza dei post singoli: alpha 150 su 255.
        alpha_logo = logo.getchannel("A").point(
            lambda valore: valore * 150 // 255
        )
        logo.putalpha(alpha_logo)
        canvas.paste(logo, (1028 - logo.width, 30), logo)

    colonne = 3 if len(prodotti) > 4 else 2
    righe = 2 if len(prodotti) > 2 else 1
    # La griglia termina prima del logo Amazon, lasciando una fascia bianca.
    alto_griglia = 780
    larghezza_cella = 1000 // colonne
    altezza_cella = alto_griglia // righe
    for indice, prodotto in enumerate(prodotti):
        colonna = indice % colonne
        riga = indice // colonne
        x0 = 40 + colonna * larghezza_cella
        y0 = 155 + riga * altezza_cella
        x1 = x0 + larghezza_cella - 12
        y1 = y0 + altezza_cella - 12
        disegno.rounded_rectangle(
            (x0, y0, x1, y1), radius=25, fill="#FFFFFF", outline="#E5E5E5", width=3
        )
        try:
            risposta = requests.get(prodotto["immagine"], timeout=15)
            risposta.raise_for_status()
            foto = Image.open(BytesIO(risposta.content)).convert("RGB")
            foto = ImageOps.contain(
                foto,
                (larghezza_cella - 90, altezza_cella - 90),
                Image.Resampling.LANCZOS,
            )
            posizione = (
                x0 + (larghezza_cella - 12 - foto.width) // 2,
                y0 + (altezza_cella - 12 - foto.height) // 2,
            )
            canvas.paste(foto, posizione)
        except Exception as errore:
            print(f"Immagine raccolta non disponibile: {errore}")

        numero = f"#{indice + 1}"
        disegno.text(
            (x0 + 20, y0 + 16),
            numero,
            font=font_numero,
            fill="#171717",
            stroke_width=4,
            stroke_fill="white",
        )

    # Stesso logo Amazon dei post singoli, centrato nella fascia inferiore.
    if AMAZON_LOGO_PATH.exists():
        logo_amazon = Image.open(AMAZON_LOGO_PATH).convert("RGBA")
        pixel = []
        for rosso, verde, blu, alpha in logo_amazon.getdata():
            if rosso >= 245 and verde >= 245 and blu >= 245:
                pixel.append((rosso, verde, blu, 0))
            else:
                pixel.append((rosso, verde, blu, alpha))
        logo_amazon.putdata(pixel)
        logo_amazon = ImageOps.contain(
            logo_amazon,
            (220, 92),
            Image.Resampling.LANCZOS,
        )
        posizione_amazon = (
            (1080 - logo_amazon.width) // 2,
            1040 - logo_amazon.height,
        )
        canvas.paste(logo_amazon, posizione_amazon, logo_amazon)

    output = BytesIO()
    output.name = "raccolta_tech_bestprice24h.jpg"
    canvas.save(output, "JPEG", quality=92, optimize=True)
    output.seek(0)
    return output

def _prezzo_caption_raccolta_tech(valore):
    testo = str(valore or "—").strip()
    return testo if testo == "—" or "€" in testo else f"{testo} €"


def crea_caption_raccolta_tech(prodotti, tema, anteprima=False):
    intestazione = "🧪 <b>ANTEPRIMA — " if anteprima else "🧺 <b>"
    righe = [intestazione + RACCOLTE_TECH_TEMI[tema]["titolo"] + "</b>"]
    for indice, prodotto in enumerate(prodotti, start=1):
        nome = accorcia_nome_articolo(prodotto["nome"])
        if len(nome) > 52:
            nome = nome[:49].rsplit(" ", 1)[0] + "…"
        link = html.escape(prodotto["link"], quote=True)
        if prodotto.get("stato") == "terminata":
            righe.append(
                f'#{indice} 🔴 <s><a href="{link}">{html.escape(nome)}</a></s>\n'
                "<b>OFFERTA TERMINATA</b>"
            )
            continue
        prima = _prezzo_caption_raccolta_tech(prodotto.get("vecchio_prezzo"))
        ora = _prezzo_caption_raccolta_tech(prodotto.get("prezzo"))
        righe.append(
            f'#{indice} <a href="{link}">{html.escape(nome)}</a>\n'
            f'❌ Prima: <s>{html.escape(prima)}</s>\n'
            f'✅ Ora: <b>{html.escape(ora)}</b>'
        )
    righe.append("⚡ Prezzi e disponibilità possono variare.")
    if anteprima:
        righe.append("Anteprima non pubblicata")
    return "\n\n".join(righe)


def tastiera_raccolta_tech():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 CLUB", url="https://t.me/BestPrice24h_bot"),
        InlineKeyboardButton("📱 CANALE TECH", url=TECH_CHANNEL_URL),
    ]])


def salva_raccolta_tech(prodotti, tema, messaggio_telegram, foto_file_id):
    adesso = datetime.now(ROMA_TZ).isoformat(timespec="seconds")
    db = sqlite3.connect(DB_PATH)
    cursore = db.execute(
        """
        INSERT INTO raccolte_tech (
            tema, telegram_chat_id, telegram_message_id, telegram_photo_file_id,
            pubblicata_il, stato
        ) VALUES (?, ?, ?, ?, ?, 'pubblicata')
        """,
        (tema, str(CHANNEL_ID), messaggio_telegram.message_id, foto_file_id, adesso),
    )
    raccolta_id = cursore.lastrowid
    for posizione, prodotto in enumerate(prodotti, start=1):
        db.execute(
            """
            INSERT INTO raccolte_tech_prodotti (
                raccolta_id, posizione, asin, nome, link, prezzo, vecchio_prezzo,
                immagine_url, sconto, stato, ultima_verifica
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pubblicata', ?)
            """,
            (
                raccolta_id, posizione, prodotto["asin"], prodotto["nome"],
                prodotto["link"], prodotto.get("prezzo"), prodotto.get("vecchio_prezzo"),
                prodotto.get("immagine"), int(prodotto.get("sconto") or 0), adesso,
            ),
        )
    db.commit()
    db.close()
    for prodotto in prodotti:
        salva_offerta_recap(
            prodotto["nome"], prodotto["link"], prodotto.get("prezzo"),
            prodotto.get("vecchio_prezzo") or "NO", messaggio=crea_caption_raccolta_tech(prodotti, tema),
            foto_file_id=foto_file_id, template="raccolta", asin=prodotto.get("asin"),
            categoria=tema, telegram_chat_id=CHANNEL_ID, origine="raccolta",
            sconto=prodotto.get("sconto", 0), telegram_message_id=messaggio_telegram.message_id,
        )
    return raccolta_id


async def pubblica_raccolta_tech(bot, prodotti, tema):
    collage = await asyncio.to_thread(crea_collage_raccolta_tech, prodotti, tema)
    caption = crea_caption_raccolta_tech(prodotti, tema)
    messaggio = await bot.send_photo(
        chat_id=CHANNEL_ID,
        photo=collage,
        caption=caption,
        parse_mode="HTML",
        reply_markup=tastiera_raccolta_tech(),
    )
    foto_file_id = messaggio.photo[-1].file_id if messaggio.photo else None
    salva_raccolta_tech(prodotti, tema, messaggio, foto_file_id)
    return messaggio


async def testa_raccolta_tech(query, context):
    configurazione = leggi_config_raccolte_tech()
    tema = _tema_raccolta_successivo_tech(configurazione)
    if not tema:
        await query.message.reply_text("❌ Seleziona almeno un tema.")
        return
    attesa = await query.message.reply_text(
        f"🔎 Cerco una raccolta {RACCOLTE_TECH_TEMI[tema]['etichetta']}…"
    )
    prodotti, statistiche = await cerca_prodotti_raccolta_tech(configurazione, tema)
    if len(prodotti) < 2:
        await attesa.edit_text(
            "ℹ️ Non ho trovato almeno 2 prodotti validi.\n\n"
            f"Ricerche: {statistiche['ricerche']} · analizzati: {statistiche['analizzati']}\n"
            f"Prezzo/sconto: {statistiche['prezzo_sconto']} · qualità: {statistiche['qualita']} "
            f"· duplicati: {statistiche['duplicati']}"
        )
        return
    await attesa.delete()
    collage = await asyncio.to_thread(crea_collage_raccolta_tech, prodotti, tema)
    await query.message.reply_photo(
        photo=collage,
        caption=crea_caption_raccolta_tech(prodotti, tema, anteprima=True),
        parse_mode="HTML",
    )


def raccolta_tech_pronta(configurazione):
    """La raccolta è pronta ogni N post TECH, senza alcun limite giornaliero."""
    db = sqlite3.connect(DB_PATH)
    ultima = db.execute(
        "SELECT pubblicata_il FROM raccolte_tech ORDER BY pubblicata_il DESC LIMIT 1"
    ).fetchone()
    condizioni = ["telegram_chat_id=?", "COALESCE(origine,'manuale')<>'raccolta'"]
    parametri = [str(CHANNEL_ID)]
    if ultima:
        condizioni.append("pubblicata_il>?")
        parametri.append(ultima[0])
    post_da_ultima = db.execute(
        f"SELECT COUNT(*) FROM recap_offerte WHERE {' AND '.join(condizioni)}", parametri
    ).fetchone()[0]
    db.close()
    return post_da_ultima >= configurazione["frequenza_post"]


async def tenta_pubblicazione_raccolta_tech(bot):
    """Tenta la raccolta dopo qualsiasi post TECH, senza avvii sovrapposti."""
    if RACCOLTA_TECH_LOCK.locked():
        return False
    async with RACCOLTA_TECH_LOCK:
        configurazione = leggi_config_raccolte_tech()
        if not configurazione["attive"] or not raccolta_tech_pronta(configurazione):
            return False
        tema = _tema_raccolta_successivo_tech(configurazione)
        if not tema:
            return False
        salva_config_raccolta_tech(
            "ultimo_tentativo",
            datetime.now(ROMA_TZ).isoformat(timespec="seconds"),
        )
        prodotti, statistiche = await cerca_prodotti_raccolta_tech(
            configurazione, tema
        )
        if len(prodotti) < 2:
            await _notifica_admin_automazione(
                bot,
                f"ℹ️ Raccolta TECH {RACCOLTE_TECH_TEMI[tema]['etichetta']} rimandata: "
                f"trovati {len(prodotti)} prodotti validi dopo "
                f"{statistiche['ricerche']} ricerche. "
                "Il conteggio resta valido e riproverò dopo il prossimo post TECH.",
            )
            return False
        await pubblica_raccolta_tech(bot, prodotti, tema)
        await _notifica_admin_automazione(
            bot,
            f"✅ Raccolta TECH pubblicata: {RACCOLTE_TECH_TEMI[tema]['titolo']} "
            f"({len(prodotti)} prodotti).",
        )
        return True


async def controlla_raccolta_dopo_post_tech(bot):
    """Il fallimento della raccolta non deve annullare il post singolo già inviato."""
    try:
        return await tenta_pubblicazione_raccolta_tech(bot)
    except Exception as errore:
        print(f"Errore controllo raccolta dopo post TECH: {errore}")
        await _notifica_admin_automazione(
            bot,
            f"⚠️ Il post TECH è stato pubblicato, ma il controllo della raccolta "
            f"non è riuscito: {str(errore)[:500]}",
        )
        return False

def _font_terminata(dimensione):
    # Il font è incluso nel repository, quindi Railway mantiene la dimensione richiesta.
    percorsi = (
        str(FONT_BOLD_PATH),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    )
    for percorso in percorsi:
        try:
            return ImageFont.truetype(percorso, dimensione)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=dimensione)
    except TypeError:
        return ImageFont.load_default()

def crea_immagine_terminata(dati_immagine):
    """Crea la versione grigia della foto già pubblicata."""
    originale = Image.open(BytesIO(bytes(dati_immagine))).convert("RGBA")
    immagine = ImageOps.grayscale(originale).convert("RGBA")

    # Mantiene riconoscibile la cornice BestPrice24h.
    disegno = ImageDraw.Draw(immagine, "RGBA")
    disegno.rounded_rectangle(
        (8, 8, 1072, 1072), radius=40, outline="#F20D18", width=18
    )
    disegno.rounded_rectangle(
        (26, 26, 1054, 1054), radius=22, outline="#171717", width=3
    )

    # Ripristina a colori il logo BestPrice24h.
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        logo = ImageOps.contain(logo, (195, 170), Image.Resampling.LANCZOS)
        alpha_logo = logo.getchannel("A").point(lambda valore: valore * 150 // 255)
        logo.putalpha(alpha_logo)
        immagine.alpha_composite(logo, (1044 - logo.width, 36))

    # Fascia centrale molto alta: il testo resta leggibile anche nella miniatura Telegram.
    fascia = Image.new("RGBA", immagine.size, (0, 0, 0, 0))
    ImageDraw.Draw(fascia).rounded_rectangle(
        (30, 270, 1050, 810),
        radius=34,
        fill=(255, 255, 255, 232),
        outline=(227, 6, 19, 255),
        width=8,
    )
    immagine = Image.alpha_composite(immagine, fascia)
    disegno = ImageDraw.Draw(immagine)
    testo = "OFFERTA\nTERMINATA"
    dimensione = 190
    font = _font_terminata(dimensione)
    while (
        disegno.multiline_textbbox(
            (0, 0), testo, font=font, spacing=0, stroke_width=6, align="center"
        )[2] > 930
        and dimensione > 130
    ):
        dimensione -= 6
        font = _font_terminata(dimensione)
    riquadro = disegno.multiline_textbbox(
        (0, 0), testo, font=font, spacing=0, stroke_width=6, align="center"
    )
    larghezza = riquadro[2] - riquadro[0]
    altezza = riquadro[3] - riquadro[1]
    posizione = ((1080 - larghezza) // 2, (1080 - altezza) // 2 - riquadro[1])
    disegno.multiline_text(
        posizione,
        testo,
        font=font,
        fill="#E30613",
        spacing=0,
        align="center",
        stroke_width=6,
        stroke_fill="white",
    )

    output = BytesIO()
    output.name = "offerta_terminata.jpg"
    immagine.convert("RGB").save(output, "JPEG", quality=93, optimize=True)
    output.seek(0)
    return output


async def testa_ricerca_automatica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    canale = _auto_canale_corrente(context)
    configurazione = leggi_config_automatica(canale)
    if not configurazione["categorie"]:
        await query.message.reply_text("❌ Prima seleziona almeno una categoria.")
        return

    categorie_test = list(configurazione["categorie"])
    random.shuffle(categorie_test)
    tentativi = []
    for numero in range(3):
        categoria = categorie_test[numero % len(categorie_test)]
        etichetta, termini = AUTO_CATEGORIE[categoria]
        prioritari = termini_prioritari_categoria(categoria)
        termine = (
            random.choice(prioritari)
            if prioritari and numero < 2
            else random.choice(termini)
        )
        tentativi.append((categoria, etichetta, termine))
    snapshot_filtri = carica_snapshot_filtri(configurazione=configurazione)
    attesa = await query.message.reply_text(
        "🔎 Avvio fino a 3 ricerche di prova…\n"
        f"Sconto minimo richiesto: {configurazione['sconto_minimo']}%"
    )

    try:
        prodotti = []
        scartati_qualita = 0
        errori_ricerca = 0
        for numero, (categoria, etichetta, termine) in enumerate(tentativi, start=1):
            await attesa.edit_text(
                f"🔎 Ricerca di prova {numero}/3 in {etichetta}…\n"
                f"Sconto minimo: {configurazione['sconto_minimo']}%"
            )
            try:
                items = await asyncio.to_thread(search_items, termine, "All", 10)
            except Exception as errore:
                errori_ricerca += 1
                print(f"Errore test Creators API {numero}/3: {errore}")
                items = []
            for item in items:
                prodotto = estrai_prodotto_creators(item)
                if not prodotto or prodotto["sconto"] < configurazione["sconto_minimo"]:
                    continue
                prodotto["categoria"] = categoria
                bonus_priorita, nome_priorita = valuta_priorita_prodotto(
                    prodotto, categoria, snapshot_filtri
                )
                approvato, punteggio, motivi = valuta_qualita_prodotto(
                    prodotto,
                    categoria,
                    configurazione["qualita_prodotti"],
                    snapshot_filtri,
                    bonus_priorita,
                )
                prodotto["punteggio_qualita"] = punteggio
                prodotto["motivi_qualita"] = motivi
                if approvato:
                    prodotto["bonus_priorita"] = bonus_priorita
                    prodotto["nome_priorita"] = nome_priorita
                    prodotti.append(prodotto)
                else:
                    scartati_qualita += 1
            if numero < len(tentativi):
                await asyncio.sleep(1.0)

        if not prodotti:
            await attesa.edit_text(
                "ℹ️ Collegamento riuscito, ma la ricerca non ha trovato prodotti "
                f"con almeno il {configurazione['sconto_minimo']}% di sconto "
                f"approvati dalla modalità {configurazione['qualita_prodotti'].capitalize()}.\n"
                f"Prodotti scartati dal filtro qualità: {scartati_qualita}.\n\n"
                f"Ricerche non riuscite per errore tecnico: {errori_ricerca}.\n\n"
                "Nessun post è stato pubblicato."
            )
            return

        prodotto = max(
            prodotti,
            key=lambda x: (
                x.get("bonus_priorita", 0), x["punteggio_qualita"], x["sconto"]
            ),
        )
        await attesa.delete()
        tipo_offerta = "🚨 ERRORE PREZZO" if prodotto["sconto"] > 40 else "🔥 OFFERTA AMAZON"
        vecchio = (
            f"\n❌ Prima: <s>{html.escape(prodotto['vecchio_prezzo'])}</s>"
            if prodotto["vecchio_prezzo"] else ""
        )
        dettaglio_qualita = (
            f" — {prodotto['punteggio_qualita']} punti"
            if configurazione["qualita_prodotti"] != "standard"
            else ""
        )
        dettaglio_priorita = (
            f"\nPriorità: {html.escape(prodotto['nome_priorita'])} "
            f"(+{prodotto['bonus_priorita']})"
            if prodotto.get("bonus_priorita") else ""
        )
        testo = (
            f"🧪 <b>ANTEPRIMA TEST — {tipo_offerta}</b>\n\n"
            f"🛒 {html.escape(prodotto['nome'])}\n\n"
            f"💥 Sconto: <b>-{prodotto['sconto']}%</b>"
            f"{vecchio}\n"
            f"✅ Ora: <b>{html.escape(prodotto['prezzo'])}</b>\n\n"
            f"{riga_venditore_categoria(prodotto, prodotto['categoria'])}\n\n"
            f"Marchio: {html.escape(prodotto.get('marchio') or 'non disponibile')}\n"
            f"Qualità: {configurazione['qualita_prodotti'].capitalize()}"
            f"{dettaglio_qualita}{dettaglio_priorita}\n\n"
            f"👉 <a href=\"{html.escape(prodotto['link'], quote=True)}\">Scopri l’offerta su Amazon</a>\n\n"
            "Anteprima non pubblicata"
        )
        tastiera = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 APRI", url=prodotto["link"]),
        ]])
        foto = await prepara_foto_automatica(prodotto["immagine"])
        await query.message.reply_photo(
            photo=foto,
            caption=testo,
            parse_mode="HTML",
            reply_markup=tastiera,
        )
    except Exception as errore:
        print(f"Errore test Creators API: {errore}")
        await attesa.edit_text(
            "❌ Il test delle Creator API non è riuscito.\n\n"
            f"Dettaglio tecnico: {html.escape(str(errore))[:900]}\n\n"
            "Nessun post è stato pubblicato.",
            parse_mode="HTML",
        )


# =========================================================
# RICERCA MANUALE DI PIÙ OFFERTE
# =========================================================

def _pulisci_stato_ricerca_offerte(context, conserva_risultati=False):
    chiavi = (
        "ricerca_offerte_sconto",
        "ricerca_offerte_categoria",
        "ricerca_offerte_quantita",
        "ricerca_offerte_indice",
    )
    for chiave in chiavi:
        context.user_data.pop(chiave, None)
    if not conserva_risultati:
        context.user_data.pop("ricerca_offerte_risultati", None)


async def menu_ricerca_offerte(query, context, canale=None):
    _pulisci_stato_ricerca_offerte(context)
    context.user_data["ricerca_offerte_canale"] = canale
    indietro = "auto_menu" if canale else "menu_admin"
    await query.message.reply_text(
        "🔎 CERCA OFFERTE\n\n"
        "Seleziona lo sconto minimo. La ricerca non pubblicherà nulla automaticamente.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("10%", callback_data="os_disc_10"),
                InlineKeyboardButton("20%", callback_data="os_disc_20"),
                InlineKeyboardButton("30%", callback_data="os_disc_30"),
            ],
            [
                InlineKeyboardButton("40%", callback_data="os_disc_40"),
                InlineKeyboardButton("50%", callback_data="os_disc_50"),
            ],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data=indietro)],
        ]),
    )


async def menu_categoria_ricerca_offerte(query, context, sconto):
    context.user_data["ricerca_offerte_sconto"] = sconto
    canale = context.user_data.get("ricerca_offerte_canale")
    configurazione = leggi_config_automatica(canale or "tech")
    selezionate = set(configurazione["categorie"])
    consentite = (
        TECH_CATEGORIE if canale == "tech"
        else CASA_CATEGORIE if canale == "casa"
        else set(AUTO_CATEGORIE)
    )
    categorie = [
        codice for codice in AUTO_CATEGORIE
        if codice in consentite and (not selezionate or codice in selezionate)
    ]
    tastiera = [[InlineKeyboardButton(
        AUTO_CATEGORIE[codice][0].upper(),
        callback_data=f"os_cat_{codice}",
    )] for codice in categorie]
    tastiera.insert(0, [InlineKeyboardButton("🌐 TUTTE LE CATEGORIE", callback_data="os_cat_tutte")])
    ritorno = f"offer_search_{canale}" if canale else "offer_search"
    tastiera.append([InlineKeyboardButton("⬅️ INDIETRO", callback_data=ritorno)])
    await query.edit_message_text(
        f"🔎 Sconto selezionato: dal {sconto}%\n\nScegli dove cercare:",
        reply_markup=InlineKeyboardMarkup(tastiera),
    )


async def menu_quantita_ricerca_offerte(query, context, categoria):
    context.user_data["ricerca_offerte_categoria"] = categoria
    etichetta = (
        "Tutte le categorie" if categoria == "tutte"
        else AUTO_CATEGORIE[categoria][0]
    )
    await query.edit_message_text(
        f"🔎 Categoria: {etichetta}\n\nQuanti risultati vuoi visualizzare?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("5", callback_data="os_count_5"),
                InlineKeyboardButton("10", callback_data="os_count_10"),
                InlineKeyboardButton("20", callback_data="os_count_20"),
            ],
            [InlineKeyboardButton("⬅️ INDIETRO", callback_data=f"os_disc_{context.user_data['ricerca_offerte_sconto']}")],
        ]),
    )


def _piano_ricerca_offerte(categoria, configurazione, quantita, canale="tech"):
    if categoria != "tutte":
        prioritari = termini_prioritari_categoria(categoria)
        termini = prioritari[:2] + list(AUTO_CATEGORIE[categoria][1])
        unici = []
        for termine in termini:
            if termine.lower() not in {x.lower() for x in unici}:
                unici.append(termine)
        return [(categoria, termine) for termine in unici[:3]]

    categorie = list(configurazione["categorie"]) or list(AUTO_CATEGORIE)
    categorie = ruota_categorie_persistente(
        categorie, "indice_categoria_ricerca", canale or "tech"
    )
    massimo_chiamate = 4 if quantita <= 5 else 6 if quantita <= 10 else 8
    piano = []
    for indice_parola in range(3):
        for codice in categorie:
            prioritari = termini_prioritari_categoria(codice)
            if indice_parola == 0 and prioritari:
                termine = random.choice(prioritari)
            else:
                termine = AUTO_CATEGORIE[codice][1][indice_parola]
            piano.append((codice, termine))
            if len(piano) >= massimo_chiamate:
                return piano
    return piano


async def esegui_ricerca_offerte(query, context, quantita):
    canale = context.user_data.get("ricerca_offerte_canale")
    configurazione = leggi_config_automatica(canale or "tech")
    if not canale:
        configurazione = {**configurazione, "categorie": list(AUTO_CATEGORIE)}
    sconto = int(context.user_data.get("ricerca_offerte_sconto", 30))
    categoria_scelta = context.user_data.get("ricerca_offerte_categoria", "tutte")
    context.user_data["ricerca_offerte_quantita"] = quantita
    piano = _piano_ricerca_offerte(
        categoria_scelta, configurazione, quantita, canale or "tech"
    )
    snapshot_filtri = carica_snapshot_filtri(configurazione=configurazione)
    attesa = await query.message.reply_text(
        f"🔄 Cerco offerte con almeno il {sconto}% di sconto…\n"
        f"Ricerche previste: massimo {len(piano)}."
    )

    trovati = {}
    errori = 0
    for numero, (categoria, termine) in enumerate(piano, start=1):
        try:
            items = await asyncio.to_thread(search_items, termine, "All", 10)
            for item in items:
                prodotto = estrai_prodotto_creators(item)
                if not prodotto or prodotto["sconto"] < sconto:
                    continue
                canale_duplicati = canale or (
                    "casa" if categoria in CASA_CATEGORIE else "tech"
                )
                if prodotto["asin"] in trovati or _asin_gia_pubblicato(
                    prodotto["asin"],
                    configurazione["giorni_blocco_duplicati"],
                    canale_duplicati,
                ):
                    continue
                prodotto["categoria"] = categoria
                bonus_priorita, nome_priorita = valuta_priorita_prodotto(
                    prodotto, categoria, snapshot_filtri
                )
                approvato, punteggio, motivi = valuta_qualita_prodotto(
                    prodotto,
                    categoria,
                    configurazione["qualita_prodotti"],
                    snapshot_filtri,
                    bonus_priorita,
                )
                if not approvato:
                    continue
                prodotto["punteggio_qualita"] = punteggio
                prodotto["motivi_qualita"] = motivi
                prodotto["bonus_priorita"] = bonus_priorita
                prodotto["nome_priorita"] = nome_priorita
                trovati[prodotto["asin"]] = prodotto
        except Exception as errore:
            errori += 1
            print(f"Errore ricerca elenco {numero}/{len(piano)}: {errore}")
        if len(trovati) >= quantita:
            break
        if numero < len(piano):
            await asyncio.sleep(1.0)

    candidati = list(trovati.values())
    if configurazione.get("raggruppa_varianti", True):
        candidati = _raggruppa_varianti_prodotti(candidati)
    preferiti = [
        prodotto for prodotto in candidati
        if prodotto.get("punteggio_qualita", 0) >= configurazione["punteggio_minimo"]
    ]
    risultati = sorted(
        preferiti or candidati,
        key=lambda p: (
            p.get("bonus_priorita", 0),
            p.get("punteggio_qualita", 0),
            p["sconto"],
        ),
        reverse=True,
    )[:quantita]
    context.user_data["ricerca_offerte_risultati"] = risultati
    await attesa.delete()
    if not risultati:
        dettaglio = "" if not errori else f"\nRicerche non riuscite: {errori}."
        callback_ricerca = f"offer_search_{canale}" if canale else "offer_search"
        await query.message.reply_text(
            f"ℹ️ Nessun prodotto nuovo con almeno il {sconto}% ha superato i filtri."
            f"{dettaglio}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 CAMBIA RICERCA", callback_data=callback_ricerca)],
                [InlineKeyboardButton("⬅️ MENU AUTOMATICO", callback_data="auto_menu")],
            ]),
        )
        return
    await mostra_lista_ricerca_offerte(query.message, context)


async def mostra_lista_ricerca_offerte(messaggio, context):
    risultati = context.user_data.get("ricerca_offerte_risultati", [])
    sconto = context.user_data.get("ricerca_offerte_sconto", 30)
    righe = [f"🔎 OFFERTE TROVATE — DAL {sconto}%\n"]
    tastiera = []
    for indice, prodotto in enumerate(risultati):
        titolo = accorcia_nome_articolo(prodotto["nome"])
        if len(titolo) > 65:
            titolo = titolo[:62].rsplit(" ", 1)[0] + "…"
        righe.append(
            f"{indice + 1}. -{prodotto['sconto']}% · {titolo}\n"
            f"   {prodotto['prezzo']} · {AUTO_CATEGORIE[prodotto['categoria']][0]}"
        )
        tastiera.append([InlineKeyboardButton(
            f"{indice + 1}. -{prodotto['sconto']}% · {titolo[:35]}",
            callback_data=f"os_view_{indice}",
        )])
    canale = context.user_data.get("ricerca_offerte_canale")
    callback_ricerca = f"offer_search_{canale}" if canale else "offer_search"
    tastiera.extend([
        [InlineKeyboardButton("🔄 NUOVA RICERCA", callback_data=callback_ricerca)],
        [InlineKeyboardButton("⬅️ MENU AUTOMATICO", callback_data="auto_menu")],
    ])
    await messaggio.reply_text(
        "\n\n".join(righe) + "\n\nTocca un prodotto per gestirlo.",
        reply_markup=InlineKeyboardMarkup(tastiera),
    )


def _prodotto_risultato(context, indice):
    risultati = context.user_data.get("ricerca_offerte_risultati", [])
    if 0 <= indice < len(risultati):
        return risultati[indice]
    return None


async def mostra_prodotto_ricerca_offerte(query, context, indice):
    prodotto = _prodotto_risultato(context, indice)
    if not prodotto:
        await query.message.reply_text("❌ Risultato scaduto. Avvia una nuova ricerca.")
        return
    context.user_data["ricerca_offerte_indice"] = indice
    canale = context.user_data.get("ricerca_offerte_canale")
    configurazione = leggi_config_automatica(canale or "tech")
    tipo = "🚨 ERRORE PREZZO" if prodotto["sconto"] > 40 else "🔥 OFFERTA AMAZON"
    prima = (
        f"\n❌ Prima: <s>{html.escape(prodotto['vecchio_prezzo'])}</s>"
        if prodotto.get("vecchio_prezzo") else ""
    )
    dettaglio = (
        f" — {prodotto.get('punteggio_qualita', 0)} punti"
        if configurazione["qualita_prodotti"] != "standard" else ""
    )
    dettaglio_priorita = (
        f"\nPriorità: {html.escape(prodotto['nome_priorita'])} "
        f"(+{prodotto['bonus_priorita']})"
        if prodotto.get("bonus_priorita") else ""
    )
    testo = (
        f"👁 <b>ANTEPRIMA — {tipo}</b>\n\n"
        f"🛒 {html.escape(prodotto['nome'])}\n\n"
        f"💥 Sconto: <b>-{prodotto['sconto']}%</b>{prima}\n"
        f"✅ Ora: <b>{html.escape(prodotto['prezzo'])}</b>\n\n"
        f"{riga_venditore_categoria(prodotto, prodotto['categoria'])}\n\n"
        f"Marchio: {html.escape(prodotto.get('marchio') or 'non disponibile')}\n"
        f"Qualità: {configurazione['qualita_prodotti'].capitalize()}"
        f"{dettaglio}{dettaglio_priorita}\n\n"
        f"👉 <a href=\"{html.escape(prodotto['link'], quote=True)}\">Scopri l’offerta su Amazon</a>"
    )
    tastiera = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 PUBBLICA ORA", callback_data=f"os_publish_{indice}")],
        [InlineKeyboardButton("🕒 PROGRAMMA", callback_data=f"os_program_{indice}")],
        [InlineKeyboardButton("🛒 APRI SU AMAZON", url=prodotto["link"])],
        [InlineKeyboardButton("⬅️ TORNA ALLA LISTA", callback_data="os_back")],
    ])
    foto = await prepara_foto_automatica(prodotto["immagine"])
    inviato = await query.message.reply_photo(
        photo=foto, caption=testo, parse_mode="HTML", reply_markup=tastiera
    )
    if inviato.photo:
        prodotto["foto_file_id"] = inviato.photo[-1].file_id


def _registra_offerta_cercata(
    prodotto, message_id, foto_file_id, soglia, telegram_chat_id
):
    adesso = datetime.now(ROMA_TZ)
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        INSERT OR IGNORE INTO invii_automatici (
            asin, nome, link, categoria, sconto, slot_data, slot_ora, stato,
            creato_il, telegram_message_id, telegram_photo_file_id,
            soglia_sconto, deal_end_time, telegram_chat_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pubblicata', ?, ?, ?, ?, ?, ?)
        """,
        (
            prodotto.get("asin"), prodotto.get("nome"), prodotto.get("link"),
            prodotto.get("categoria"), prodotto.get("sconto"), adesso.date().isoformat(),
            "M" + adesso.strftime("%H%M%S"), adesso.isoformat(timespec="seconds"),
            message_id, foto_file_id, soglia, prodotto.get("deal_end_time"),
            telegram_chat_id,
        ),
    )
    db.commit()
    db.close()


async def pubblica_prodotto_ricerca_offerte(query, context, indice):
    prodotto = _prodotto_risultato(context, indice)
    if not prodotto:
        await query.message.reply_text("❌ Risultato scaduto. Avvia una nuova ricerca.")
        return
    attesa_minuti = minuti_rimanenti_prima_del_prossimo_invio()
    if attesa_minuti:
        await query.message.reply_text(
            f"⏳ Attendi ancora {attesa_minuti} minuto/i prima di pubblicare."
        )
        return
    try:
        canale = context.user_data.get("ricerca_offerte_canale")
        message_id, foto_file_id, telegram_chat_id = await pubblica_offerta_automatica(
            context.bot, prodotto, canale, origine="ricerca"
        )
        _registra_offerta_cercata(
            prodotto, message_id, foto_file_id,
            context.user_data.get("ricerca_offerte_sconto", prodotto["sconto"]),
            telegram_chat_id,
        )
        await query.message.reply_text(
            "✅ OFFERTA PUBBLICATA!",
            reply_markup=menu_dopo_pubblicazione(),
        )
    except OffertaDuplicataError:
        await query.message.reply_text(
            "⛔ Questo prodotto è già stato pubblicato recentemente in questo canale."
        )
    except Exception as errore:
        print(f"Errore pubblicazione risultato ricerca: {errore}")
        await query.message.reply_text(f"❌ Pubblicazione non riuscita: {str(errore)[:500]}")


async def gestisci_ricerca_offerte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    azione = query.data
    if azione == "offer_search":
        return await menu_ricerca_offerte(query, context)
    if azione.startswith("offer_search_"):
        canale = azione.rsplit("_", 1)[1]
        if canale not in {"tech", "casa"}:
            return
        return await menu_ricerca_offerte(query, context, canale)
    if azione.startswith("os_disc_"):
        return await menu_categoria_ricerca_offerte(query, context, int(azione.rsplit("_", 1)[1]))
    if azione.startswith("os_cat_"):
        categoria = azione.replace("os_cat_", "", 1)
        if categoria != "tutte" and categoria not in AUTO_CATEGORIE:
            return
        return await menu_quantita_ricerca_offerte(query, context, categoria)
    if azione.startswith("os_count_"):
        return await esegui_ricerca_offerte(query, context, int(azione.rsplit("_", 1)[1]))
    if azione.startswith("os_view_"):
        return await mostra_prodotto_ricerca_offerte(query, context, int(azione.rsplit("_", 1)[1]))
    if azione.startswith("os_publish_"):
        return await pubblica_prodotto_ricerca_offerte(query, context, int(azione.rsplit("_", 1)[1]))
    if azione == "os_back":
        return await mostra_lista_ricerca_offerte(query.message, context)


def _messaggio_programmato_da_prodotto(prodotto):
    tipo = "🚨 ERRORE PREZZO" if prodotto["sconto"] > 40 else "🔥 OFFERTA AMAZON"
    prima = (
        f"\n❌ Prima: <s>{html.escape(prodotto['vecchio_prezzo'])}</s>"
        if prodotto.get("vecchio_prezzo") else ""
    )
    return (
        "__RICERCA_HTML__"
        f"<b>{tipo}</b>\n\n"
        f"🛒 {html.escape(prodotto['nome'])}\n\n"
        f"💥 Sconto: <b>-{prodotto['sconto']}%</b>{prima}\n"
        f"✅ Ora: <b>{html.escape(prodotto['prezzo'])}</b>\n\n"
        f"{riga_venditore_categoria(prodotto, prodotto['categoria'])}"
    )


async def prepara_programmazione_ricerca_offerte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    indice = int(query.data.rsplit("_", 1)[1])
    prodotto = _prodotto_risultato(context, indice)
    if not prodotto:
        await query.message.reply_text("❌ Risultato scaduto. Avvia una nuova ricerca.")
        return ConversationHandler.END
    context.user_data["nome"] = prodotto["nome"]
    context.user_data["link"] = prodotto["link"]
    context.user_data["prezzo"] = _prezzo_italiano(prodotto["prezzo_valore"])
    context.user_data["vecchio_prezzo"] = (
        _prezzo_italiano(prodotto["vecchio_valore"])
        if prodotto.get("vecchio_valore") else "NO"
    )
    context.user_data["foto_file_id"] = prodotto.get("foto_file_id") or prodotto["immagine"]
    context.user_data["messaggio"] = _messaggio_programmato_da_prodotto(prodotto)
    canale = context.user_data.get("ricerca_offerte_canale")
    context.user_data["telegram_chat_id"] = (
        CASA_CHANNEL_ID if canale == "casa"
        else CHANNEL_ID if canale == "tech"
        else canale_pubblicazione_per_categoria(prodotto.get("categoria"))
    )
    await query.message.reply_text(
        "📅 PROGRAMMA INVIO\n\nScegli il giorno:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 OGGI", callback_data="prog_giorno_0")],
            [InlineKeyboardButton("📅 DOMANI", callback_data="prog_giorno_1")],
            [InlineKeyboardButton("📅 TRA 2 GIORNI", callback_data="prog_giorno_2")],
            [InlineKeyboardButton("❌ ANNULLA", callback_data="annulla")],
        ]),
    )
    return CONFERMA


# =========================================================
# INVIO AUTOMATICO - MOTORE
# =========================================================

def _slot_automatico_gia_gestito(data_slot, ora_slot):
    db = sqlite3.connect(DB_PATH)
    riga = db.execute(
        "SELECT stato FROM invii_automatici WHERE slot_data = ? AND slot_ora = ?",
        (data_slot, ora_slot),
    ).fetchone()
    db.close()
    return bool(riga)


def _prenota_slot_automatico(data_slot, ora_slot, categoria):
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute(
            """
            INSERT INTO invii_automatici (
                categoria, slot_data, slot_ora, stato, creato_il
            ) VALUES (?, ?, ?, 'ricerca', ?)
            """,
            (
                categoria,
                data_slot,
                ora_slot,
                datetime.now(ROMA_TZ).isoformat(timespec="seconds"),
            ),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        db.close()


def _aggiorna_slot_automatico(
    data_slot,
    ora_slot,
    stato,
    prodotto=None,
    telegram_message_id=None,
    telegram_photo_file_id=None,
    soglia_sconto=None,
    deal_end_time=None,
    telegram_chat_id=None,
):
    prodotto = prodotto or {}
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        UPDATE invii_automatici
        SET stato = ?, asin = ?, nome = ?, link = ?, sconto = ?,
            prezzo = ?, vecchio_prezzo = ?,
            telegram_message_id = COALESCE(?, telegram_message_id),
            telegram_photo_file_id = COALESCE(?, telegram_photo_file_id),
            soglia_sconto = COALESCE(?, soglia_sconto),
            deal_end_time = COALESCE(?, deal_end_time),
            telegram_chat_id = COALESCE(?, telegram_chat_id),
            ultima_verifica = CASE
                WHEN ? = 'pubblicata' THEN COALESCE(ultima_verifica, ?)
                ELSE ultima_verifica
            END
        WHERE slot_data = ? AND slot_ora = ?
        """,
        (
            stato,
            prodotto.get("asin"),
            prodotto.get("nome"),
            prodotto.get("link"),
            prodotto.get("sconto"),
            prodotto.get("prezzo"),
            prodotto.get("vecchio_prezzo"),
            telegram_message_id,
            telegram_photo_file_id,
            soglia_sconto,
            deal_end_time,
            telegram_chat_id,
            stato,
            datetime.now(ROMA_TZ).isoformat(timespec="seconds"),
            data_slot,
            ora_slot,
        ),
    )
    db.commit()
    db.close()


def _chat_id_per_canale(canale):
    return str(CASA_CHANNEL_ID if canale == "casa" else CHANNEL_ID)


def _data_sqlite(valore):
    if not valore:
        return None
    try:
        data = datetime.fromisoformat(valore)
        return data.replace(tzinfo=ROMA_TZ) if data.tzinfo is None else data
    except (TypeError, ValueError):
        return None


def _asin_gia_pubblicato(asin, giorni=10, canale="tech"):
    """Controlla i duplicati separatamente per TECH e CASA, in ogni modalità."""
    if not asin:
        return True
    canale = "casa" if canale == "casa" else "tech"
    adesso = datetime.now(ROMA_TZ)
    limite = adesso - timedelta(days=max(1, int(giorni)))
    chat_id = _chat_id_per_canale(canale)
    db = sqlite3.connect(DB_PATH)
    try:
        prenotazione = db.execute(
            """
            SELECT stato, prenotato_il, pubblicato_il
            FROM blocco_duplicati_canali
            WHERE canale = ? AND asin = ?
            """,
            (canale, asin),
        ).fetchone()
        if prenotazione:
            stato, prenotato_il, pubblicato_il = prenotazione
            data_pubblicazione = _data_sqlite(pubblicato_il)
            if data_pubblicazione and data_pubblicazione >= limite:
                return True
            data_prenotazione = _data_sqlite(prenotato_il)
            if (
                stato == "prenotata"
                and data_prenotazione
                and data_prenotazione >= adesso - timedelta(minutes=30)
            ):
                return True

        riga_automatica = db.execute(
            """
            SELECT creato_il FROM invii_automatici
            WHERE asin = ? AND stato IN ('pubblicata', 'terminata')
              AND CAST(telegram_chat_id AS TEXT) = ?
            ORDER BY creato_il DESC LIMIT 1
            """,
            (asin, chat_id),
        ).fetchone()
        riga_recap = db.execute(
            """
            SELECT pubblicata_il FROM recap_offerte
            WHERE asin = ?
              AND COALESCE(stato, 'pubblicata') IN ('pubblicata', 'terminata')
              AND CAST(telegram_chat_id AS TEXT) = ?
            ORDER BY pubblicata_il DESC LIMIT 1
            """,
            (asin, chat_id),
        ).fetchone()
        for riga in (riga_automatica, riga_recap):
            data_pubblicazione = _data_sqlite(riga[0] if riga else None)
            if data_pubblicazione and data_pubblicazione >= limite:
                return True
        return False
    finally:
        db.close()


def _prenota_asin_pubblicazione(asin, canale, giorni):
    """Prenota atomicamente un ASIN prima dell'invio a Telegram."""
    if not asin or _asin_gia_pubblicato(asin, giorni, canale):
        return False
    canale = "casa" if canale == "casa" else "tech"
    adesso = datetime.now(ROMA_TZ)
    limite = adesso - timedelta(days=max(1, int(giorni)))
    db = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    try:
        db.execute("BEGIN IMMEDIATE")
        riga = db.execute(
            """
            SELECT stato, prenotato_il, pubblicato_il
            FROM blocco_duplicati_canali
            WHERE canale = ? AND asin = ?
            """,
            (canale, asin),
        ).fetchone()
        if riga:
            stato, prenotato_il, pubblicato_il = riga
            data_pubblicazione = _data_sqlite(pubblicato_il)
            data_prenotazione = _data_sqlite(prenotato_il)
            occupato = (
                data_pubblicazione is not None and data_pubblicazione >= limite
            ) or (
                stato == "prenotata"
                and data_prenotazione is not None
                and data_prenotazione >= adesso - timedelta(minutes=30)
            )
            if occupato:
                db.execute("ROLLBACK")
                return False
        db.execute(
            """
            INSERT INTO blocco_duplicati_canali (
                canale, asin, stato, prenotato_il, pubblicato_il
            ) VALUES (?, ?, 'prenotata', ?, NULL)
            ON CONFLICT(canale, asin) DO UPDATE SET
                stato = 'prenotata',
                prenotato_il = excluded.prenotato_il,
                pubblicato_il = NULL
            """,
            (canale, asin, adesso.isoformat(timespec="seconds")),
        )
        db.execute("COMMIT")
        return True
    except Exception:
        try:
            db.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        db.close()


def _conferma_asin_pubblicato(asin, canale):
    if not asin:
        return
    canale = "casa" if canale == "casa" else "tech"
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute(
        """
        UPDATE blocco_duplicati_canali
        SET stato = 'pubblicata', pubblicato_il = ?
        WHERE canale = ? AND asin = ?
        """,
        (datetime.now(ROMA_TZ).isoformat(timespec="seconds"), canale, asin),
    )
    db.commit()
    db.close()


class OffertaDuplicataError(RuntimeError):
    pass

def _chiave_famiglia_prodotto(prodotto):
    """Raggruppa colori, capacità e confezioni dello stesso modello."""
    titolo = _normalizza_qualita(prodotto.get("nome"))
    titolo = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", titolo)
    titolo = re.sub(
        r"\b(?:\d+\s?(?:gb|tb|mb|ml|cl|l|w|mah|hz|pollici)|"
        r"nero|bianco|blu|rosso|verde|grigio|rosa|viola|silver|gold|"
        r"confezione|pack|pezzi|pz)\b",
        " ",
        titolo,
    )
    parole = [p for p in titolo.split() if len(p) > 1]
    return " ".join(parole[:12]) or prodotto.get("asin") or titolo


def _raggruppa_varianti_prodotti(prodotti):
    migliori = {}
    for prodotto in prodotti:
        chiave = _chiave_famiglia_prodotto(prodotto)
        valore = (
            prodotto.get("bonus_priorita", 0),
            prodotto.get("punteggio_qualita", 0),
            prodotto.get("sconto", 0),
        )
        precedente = migliori.get(chiave)
        if precedente is None or valore > precedente[0]:
            migliori[chiave] = (valore, prodotto)
    return [elemento[1] for elemento in migliori.values()]


def _numero_slot_del_giorno(data_slot):
    db = sqlite3.connect(DB_PATH)
    numero = db.execute(
        "SELECT COUNT(*) FROM invii_automatici WHERE slot_data = ?",
        (data_slot,),
    ).fetchone()[0]
    db.close()
    return numero


def _prezzo_italiano(valore):
    return f"{float(valore):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


async def _notifica_admin_automazione(bot, testo):
    if not ADMIN_ID:
        return
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=testo)
    except Exception as errore:
        print(f"Errore notifica automazione: {errore}")


async def cerca_offerta_automatica(configurazione, categoria_iniziale, canale="tech"):
    categorie = list(configurazione["categorie"])
    if categoria_iniziale in categorie:
        indice = categorie.index(categoria_iniziale)
        categorie = categorie[indice:] + categorie[:indice]

    snapshot_filtri = carica_snapshot_filtri(configurazione=configurazione)

    massimo = max(3, min(9, int(configurazione.get("tentativi_ricerca", 6))))
    tentativi = []
    visti = set()
    indice = 0
    while len(tentativi) < massimo:
        categoria = categorie[(indice // 2) % len(categorie)]
        generici = AUTO_CATEGORIE[categoria][1]
        prioritari = termini_prioritari_categoria(categoria)
        if indice % 2 == 0 and prioritari:
            termine = prioritari[(indice // 2) % len(prioritari)]
        else:
            termine = generici[(indice // 2) % len(generici)]
        chiave = (categoria, termine.lower())
        if chiave not in visti:
            tentativi.append((categoria, termine))
            visti.add(chiave)
        indice += 1
        if indice > massimo * 10:
            break

    statistiche = {
        "ricerche": 0, "prodotti": 0, "incompleti": 0,
        "sconto": 0, "duplicati": 0, "qualita": 0, "errori": 0,
        "varianti": 0, "riserva": False, "fallback_standard": False,
    }
    candidati = []
    candidati_standard = []
    for numero, (categoria, termine) in enumerate(tentativi, start=1):
        print(f"Ricerca automatica {numero}/{len(tentativi)}: {categoria} - {termine}")
        statistiche["ricerche"] += 1
        try:
            items = await asyncio.to_thread(search_items, termine, "All", 10)
            for item in items:
                statistiche["prodotti"] += 1
                prodotto = estrai_prodotto_creators(item)
                if not prodotto:
                    statistiche["incompleti"] += 1
                    continue
                if prodotto["sconto"] < configurazione["sconto_minimo"]:
                    statistiche["sconto"] += 1
                    continue
                if _asin_gia_pubblicato(
                    prodotto["asin"],
                    configurazione["giorni_blocco_duplicati"],
                    canale,
                ):
                    statistiche["duplicati"] += 1
                    continue
                prodotto["categoria"] = categoria
                bonus_priorita, nome_priorita = valuta_priorita_prodotto(
                    prodotto, categoria, snapshot_filtri
                )
                # Conserviamo subito ogni offerta tecnicamente valida. Se la
                # modalità selettiva non approva nulla, questa lista permette
                # il passaggio automatico alla modalità Standard senza
                # ripetere le stesse chiamate alle API.
                candidato_standard = dict(prodotto)
                candidato_standard["punteggio_qualita"] = 0
                candidato_standard["motivi_qualita"] = [
                    "Fallback automatico: modalità Standard"
                ]
                candidato_standard["bonus_priorita"] = bonus_priorita
                candidato_standard["nome_priorita"] = nome_priorita
                candidati_standard.append(candidato_standard)
                approvato, punteggio, motivi = valuta_qualita_prodotto(
                    prodotto,
                    categoria,
                    configurazione["qualita_prodotti"],
                    snapshot_filtri,
                    bonus_priorita,
                )
                if not approvato:
                    statistiche["qualita"] += 1
                    print(
                        f"Prodotto scartato dal filtro qualità ({punteggio} punti): "
                        f"{prodotto['nome']}"
                    )
                    continue
                prodotto["punteggio_qualita"] = punteggio
                prodotto["motivi_qualita"] = motivi
                prodotto["bonus_priorita"] = bonus_priorita
                prodotto["nome_priorita"] = nome_priorita
                candidati.append(prodotto)
        except Exception as errore:
            statistiche["errori"] += 1
            print(f"Errore tentativo automatico {numero}: {errore}")
        # Strategia 3+3: se i primi tre tentativi bastano, non consumiamo altre richieste.
        if numero == 3 and candidati:
            break
        if numero < len(tentativi):
            await asyncio.sleep(1.2)

    if not candidati and candidati_standard:
        statistiche["fallback_standard"] = True
        candidati = candidati_standard
        print(
            "Nessun prodotto approvato dal filtro qualità: "
            "attivato fallback automatico Standard."
        )
    if not candidati:
        return None, statistiche
    if configurazione.get("raggruppa_varianti", True):
        prima = len(candidati)
        candidati = _raggruppa_varianti_prodotti(candidati)
        statistiche["varianti"] = prima - len(candidati)
    if not statistiche["fallback_standard"]:
        preferiti = [
            prodotto for prodotto in candidati
            if prodotto.get("punteggio_qualita", 0) >= configurazione["punteggio_minimo"]
        ]
        if preferiti:
            candidati = preferiti
        else:
            statistiche["riserva"] = True
    candidati.sort(
        key=lambda x: (
            x.get("bonus_priorita", 0),
            x.get("punteggio_qualita", 0),
            x["sconto"],
        ),
        reverse=True,
    )
    return candidati[0], statistiche


def crea_corpo_offerta_automatica(prodotto, categoria=None):
    """Crea il testo riutilizzato sia alla pubblicazione sia negli aggiornamenti."""
    prima = (
        f"\n❌ Prima: <s>{html.escape(prodotto['vecchio_prezzo'])}</s>"
        if prodotto["vecchio_prezzo"] else ""
    )
    tipo_offerta = "🚨 ERRORE PREZZO" if prodotto["sconto"] > 40 else "🔥 OFFERTA AMAZON"
    categoria = categoria or prodotto.get("categoria")
    riga_venditore = riga_venditore_categoria(prodotto, categoria)
    return (
        f"<b>{tipo_offerta}</b>\n\n"
        f"🛒 {html.escape(prodotto['nome'])}\n\n"
        f"💥 Sconto: <b>-{prodotto['sconto']}%</b>"
        f"{prima}\n"
        f"✅ Ora: <b>{html.escape(prodotto['prezzo'])}</b>\n\n"
        f"{riga_venditore}"
    )


def tastiera_offerta_automatica(link):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 CLUB", url="https://t.me/BestPrice24h_bot"),
        InlineKeyboardButton("🛒 APRI", url=link),
    ]])


async def pubblica_offerta_automatica(bot, prodotto, canale=None, origine="automatico"):
    nome = prodotto["nome"]
    prezzo_numero = _prezzo_italiano(prodotto["prezzo_valore"])
    vecchio_numero = None
    if prodotto["vecchio_prezzo"]:
        base = prodotto.get("vecchio_valore")
        if base is not None:
            vecchio_numero = _prezzo_italiano(base)

    corpo_messaggio = crea_corpo_offerta_automatica(prodotto)
    messaggio = crea_caption_con_link(
        corpo_messaggio,
        prodotto["link"],
        messaggio_gia_html=True,
    )
    tastiera = tastiera_offerta_automatica(prodotto["link"])
    foto = await prepara_foto_automatica(prodotto["immagine"])
    canale_effettivo = (
        canale if canale in {"tech", "casa"}
        else "casa" if prodotto.get("categoria") in CASA_CATEGORIE
        else "tech"
    )
    telegram_chat_id = CASA_CHANNEL_ID if canale_effettivo == "casa" else CHANNEL_ID
    giorni_blocco = leggi_config_automatica(canale_effettivo)[
        "giorni_blocco_duplicati"
    ]
    if not _prenota_asin_pubblicazione(
        prodotto.get("asin"), canale_effettivo, giorni_blocco
    ):
        raise OffertaDuplicataError(
            f"ASIN {prodotto.get('asin')} già pubblicato o in pubblicazione "
            f"nel canale {canale_effettivo.upper()}."
        )
    messaggio_telegram = await bot.send_photo(
        chat_id=telegram_chat_id,
        photo=foto,
        caption=messaggio,
        parse_mode="HTML",
        reply_markup=tastiera,
    )
    ultime_offerte.appendleft({
        "nome": nome,
        "link": prodotto["link"],
        "prezzo": prezzo_numero,
    })
    foto_telegram = prodotto["immagine"]
    if messaggio_telegram.photo:
        foto_telegram = messaggio_telegram.photo[-1].file_id
    _conferma_asin_pubblicato(prodotto.get("asin"), canale_effettivo)
    salva_offerta_recap(
        nome,
        prodotto["link"],
        prezzo_numero,
        vecchio_numero or "NO",
        messaggio=corpo_messaggio,
        foto_file_id=foto_telegram,
        template="automatico",
        asin=prodotto.get("asin"),
        categoria=prodotto.get("categoria", "manuale"),
        telegram_chat_id=telegram_chat_id,
        origine=origine,
        sconto=prodotto.get("sconto", 0),
        telegram_message_id=messaggio_telegram.message_id,
    )
    if canale_effettivo == "casa":
        await controlla_raccolta_dopo_post_casa(bot)
    elif canale_effettivo == "tech":
        await controlla_raccolta_dopo_post_tech(bot)
    return messaggio_telegram.message_id, foto_telegram, telegram_chat_id


async def esegui_slot_automatico(app, configurazione, data_slot, ora_slot, canale="tech"):
    categorie = configurazione["categorie"]
    if not categorie:
        return
    categorie_ruotate = ruota_categorie_persistente(
        categorie,
        "indice_categoria_automatica",
        canale,
    )
    categoria = categorie_ruotate[0]
    slot_ora_db = f"{canale}:{ora_slot}"
    if not _prenota_slot_automatico(data_slot, slot_ora_db, categoria):
        return

    try:
        prodotto, statistiche = await cerca_offerta_automatica(
            configurazione, categoria, canale
        )
        if not prodotto:
            _aggiorna_slot_automatico(data_slot, slot_ora_db, "nessuna_offerta")
            await _notifica_admin_automazione(
                app.bot,
                f"ℹ️ Alle {ora_slot} non ho trovato offerte nuove con almeno "
                f"il {configurazione['sconto_minimo']}% di sconto.\n\n"
                f"🔎 Ricerche: {statistiche['ricerche']} · prodotti analizzati: {statistiche['prodotti']}\n"
                f"📉 Sotto sconto: {statistiche['sconto']} · duplicati: {statistiche['duplicati']}\n"
                f"🎯 Scartati qualità: {statistiche['qualita']} · dati incompleti: {statistiche['incompleti']}\n"
                f"⚠️ Errori API: {statistiche['errori']}\n"
                "↪️ Anche il fallback Standard non aveva prodotti validi.",
            )
            return

        message_id, foto_file_id, telegram_chat_id = await pubblica_offerta_automatica(
            app.bot, prodotto, canale
        )
        _aggiorna_slot_automatico(
            data_slot,
            slot_ora_db,
            "pubblicata",
            prodotto,
            telegram_message_id=message_id,
            telegram_photo_file_id=foto_file_id,
            soglia_sconto=configurazione["sconto_minimo"],
            deal_end_time=prodotto.get("deal_end_time"),
            telegram_chat_id=telegram_chat_id,
        )
        await _notifica_admin_automazione(
            app.bot,
            f"✅ Offerta automatica pubblicata alle {ora_slot}:\n"
            f"{prodotto['nome']}\nSconto: -{prodotto['sconto']}%\n"
            f"Ricerche eseguite: {statistiche['ricerche']}"
            + (
                " · usato fallback Standard"
                if statistiche["fallback_standard"]
                else " · usata riserva selettiva"
                if statistiche["riserva"]
                else ""
            ),
        )
    except OffertaDuplicataError as errore:
        _aggiorna_slot_automatico(data_slot, slot_ora_db, "duplicato")
        print(f"Invio automatico bloccato come duplicato: {errore}")
        await _notifica_admin_automazione(
            app.bot,
            f"🔁 Pubblicazione evitata nel canale {canale.upper()}: "
            "il prodotto era già presente o in pubblicazione.",
        )
    except Exception as errore:
        _aggiorna_slot_automatico(data_slot, slot_ora_db, "errore")
        print(f"Errore invio automatico: {errore}")
        await _notifica_admin_automazione(
            app.bot,
            f"❌ Errore invio automatico delle {ora_slot}:\n{str(errore)[:700]}",
        )


def _limiti_fascia_automatica(configurazione, giorno):
    inizio_ora = datetime.strptime(configurazione["ora_inizio"], "%H:%M").time()
    fine_ora = datetime.strptime(configurazione["ora_fine"], "%H:%M").time()
    return (
        datetime.combine(giorno, inizio_ora, tzinfo=ROMA_TZ),
        datetime.combine(giorno, fine_ora, tzinfo=ROMA_TZ),
    )


def _dentro_fascia_automatica(configurazione, adesso):
    inizio, fine = _limiti_fascia_automatica(configurazione, adesso.date())
    return inizio <= adesso < fine


def _prossimo_inizio_fascia(configurazione, adesso):
    inizio, fine = _limiti_fascia_automatica(configurazione, adesso.date())
    if adesso < inizio:
        return inizio
    if adesso >= fine:
        domani = adesso.date() + timedelta(days=1)
        return _limiti_fascia_automatica(configurazione, domani)[0]
    return adesso


def _calcola_prossimo_invio(configurazione, riferimento):
    candidato = riferimento + timedelta(minutes=configurazione["intervallo_minuti"])
    _, fine = _limiti_fascia_automatica(configurazione, riferimento.date())
    if candidato < fine:
        return candidato
    domani = riferimento.date() + timedelta(days=1)
    return _limiti_fascia_automatica(configurazione, domani)[0]


async def controlla_invii_automatici(app):
    while True:
        try:
            for canale in ("tech", "casa"):
                configurazione = leggi_config_automatica(canale)
                if not configurazione["attiva"]:
                    continue
                adesso = datetime.now(ROMA_TZ)
                prossimo_testo = configurazione.get("prossimo_invio")
                prossimo = None
                if prossimo_testo:
                    try:
                        prossimo = datetime.fromisoformat(prossimo_testo)
                        if prossimo.tzinfo is None:
                            prossimo = prossimo.replace(tzinfo=ROMA_TZ)
                        else:
                            prossimo = prossimo.astimezone(ROMA_TZ)
                    except ValueError:
                        prossimo = None

                if prossimo is None:
                    prossimo = _prossimo_inizio_fascia(configurazione, adesso)
                    salva_config_automatica("prossimo_invio", prossimo.isoformat(timespec="seconds"), canale)

                if adesso >= prossimo:
                    if not _dentro_fascia_automatica(configurazione, adesso):
                        prossimo = _prossimo_inizio_fascia(configurazione, adesso)
                        salva_config_automatica("prossimo_invio", prossimo.isoformat(timespec="seconds"), canale)
                    else:
                        successivo = _calcola_prossimo_invio(configurazione, adesso)
                        salva_config_automatica("prossimo_invio", successivo.isoformat(timespec="seconds"), canale)
                        data_slot = adesso.date().isoformat()
                        ora_slot = adesso.strftime("%H:%M")
                        slot_ora_db = f"{canale}:{ora_slot}"
                        if not _slot_automatico_gia_gestito(data_slot, slot_ora_db):
                            await esegui_slot_automatico(
                                app,
                                configurazione,
                                data_slot,
                                ora_slot,
                                canale,
                            )
        except Exception as errore:
            print(f"Errore controllo automazione: {errore}")
        await asyncio.sleep(20)


# =========================================================
# CONTROLLO OFFERTE TERMINATE
# =========================================================

def _offerte_da_verificare():
    adesso = datetime.now(ROMA_TZ)
    limite = adesso - timedelta(days=7)
    db = sqlite3.connect(DB_PATH)
    righe = db.execute(
        """
        SELECT id, asin, nome, categoria, telegram_message_id,
               COALESCE(soglia_sconto, 0), COALESCE(verifiche_fallite, 0),
               creato_il, deal_end_time, ultima_verifica,
               telegram_photo_file_id, COALESCE(sconto, 0),
               COALESCE(sconto_modificato_notificato, 0),
               telegram_chat_id, prezzo, vecchio_prezzo
        FROM invii_automatici
        WHERE stato = 'pubblicata'
          AND telegram_message_id IS NOT NULL
          AND creato_il >= ?
        ORDER BY creato_il DESC
        """,
        (limite.isoformat(timespec="seconds"),),
    ).fetchall()
    db.close()
    da_verificare = []
    for riga in righe:
        creato_il = _data_api(riga[7])
        ultima_verifica = _data_api(riga[9]) or creato_il
        if not creato_il:
            continue

        eta = adesso - creato_il
        fallimenti = riga[6]
        if fallimenti > 0:
            intervallo = timedelta(minutes=30)
        elif eta <= timedelta(hours=24):
            intervallo = timedelta(hours=2)
        elif eta <= timedelta(hours=72):
            intervallo = timedelta(hours=6)
        else:
            intervallo = timedelta(hours=24)

        if not ultima_verifica or adesso - ultima_verifica >= intervallo:
            da_verificare.append(
                riga[:7] + (riga[10], riga[11], riga[12], riga[13], riga[14], riga[15])
            )
    return da_verificare


def _data_api(valore):
    if not valore:
        return None
    try:
        testo = str(valore).strip().replace("Z", "+00:00")
        data = datetime.fromisoformat(testo)
        if data.tzinfo is None:
            data = data.replace(tzinfo=ROMA_TZ)
        return data.astimezone(ROMA_TZ)
    except (TypeError, ValueError):
        return None


def _aggiorna_verifica_offerta(invio_id, fallita):
    db = sqlite3.connect(DB_PATH)
    if fallita:
        db.execute(
            """
            UPDATE invii_automatici
            SET verifiche_fallite = COALESCE(verifiche_fallite, 0) + 1,
                ultima_verifica = ?
            WHERE id = ?
            """,
            (datetime.now(ROMA_TZ).isoformat(timespec="seconds"), invio_id),
        )
    else:
        db.execute(
            """
            UPDATE invii_automatici
            SET verifiche_fallite = 0, ultima_verifica = ?
            WHERE id = ?
            """,
            (datetime.now(ROMA_TZ).isoformat(timespec="seconds"), invio_id),
        )
    db.commit()
    valore = db.execute(
        "SELECT COALESCE(verifiche_fallite, 0) FROM invii_automatici WHERE id = ?",
        (invio_id,),
    ).fetchone()
    db.close()
    return valore[0] if valore else 0


def _segna_offerta_terminata(invio_id):
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        UPDATE invii_automatici
        SET stato = 'terminata', terminata_il = ?
        WHERE id = ?
        """,
        (datetime.now(ROMA_TZ).isoformat(timespec="seconds"), invio_id),
    )
    db.commit()
    db.close()


def _imposta_notifica_sconto_modificato(invio_id, notificato):
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        UPDATE invii_automatici
        SET sconto_modificato_notificato = ?
        WHERE id = ?
        """,
        (1 if notificato else 0, invio_id),
    )
    db.commit()
    db.close()


def _normalizza_valore_monitorato(valore):
    return re.sub(r"\s+", " ", str(valore or "").replace("\xa0", " ")).strip()


def _salva_aggiornamento_offerta(invio_id, prodotto, corpo_messaggio):
    """Allinea archivio e monitoraggio dopo la modifica del post Telegram."""
    prezzo_recap = _prezzo_italiano(prodotto["prezzo_valore"])
    vecchio_recap = "NO"
    if prodotto.get("vecchio_valore") is not None:
        vecchio_recap = _prezzo_italiano(prodotto["vecchio_valore"])
    db = sqlite3.connect(DB_PATH)
    dati_invio = db.execute(
        "SELECT asin, telegram_message_id, telegram_chat_id FROM invii_automatici WHERE id=?",
        (invio_id,),
    ).fetchone()
    db.execute(
        """
        UPDATE invii_automatici
        SET nome=?, link=?, prezzo=?, vecchio_prezzo=?, sconto=?,
            sconto_modificato_notificato=0
        WHERE id=?
        """,
        (
            prodotto["nome"], prodotto["link"], prodotto["prezzo"],
            prodotto.get("vecchio_prezzo"), int(prodotto.get("sconto") or 0), invio_id,
        ),
    )
    if dati_invio:
        asin, message_id, chat_id = dati_invio
        db.execute(
            """
            UPDATE recap_offerte
            SET nome=?, link=?, prezzo=?, vecchio_prezzo=?, messaggio=?, sconto=?
            WHERE asin=? AND telegram_message_id=? AND telegram_chat_id=?
            """,
            (
                prodotto["nome"], prodotto["link"], prezzo_recap, vecchio_recap,
                corpo_messaggio, int(prodotto.get("sconto") or 0), asin,
                message_id, chat_id,
            ),
        )
    db.commit()
    db.close()


async def _aggiorna_post_offerta_attiva(
    bot, invio_id, prodotto, categoria, message_id, telegram_chat_id=None
):
    prodotto["categoria"] = categoria
    corpo_messaggio = crea_corpo_offerta_automatica(prodotto, categoria)
    didascalia = crea_caption_con_link(
        corpo_messaggio,
        prodotto["link"],
        messaggio_gia_html=True,
    )
    await bot.edit_message_caption(
        chat_id=telegram_chat_id or CHANNEL_ID,
        message_id=message_id,
        caption=didascalia,
        parse_mode="HTML",
        reply_markup=tastiera_offerta_automatica(prodotto["link"]),
    )
    _salva_aggiornamento_offerta(invio_id, prodotto, corpo_messaggio)


async def _modifica_post_terminato(
    bot,
    invio_id,
    nome,
    categoria,
    message_id,
    foto_file_id=None,
    telegram_chat_id=None,
):
    destinazione = telegram_chat_id or CHANNEL_ID
    hashtag = AUTO_HASHTAG.get(categoria, "#OfferteAmazon")
    didascalia = (
        "🔴 ⛔ <b>OFFERTA TERMINATA</b>\n\n"
        f"🛒 {html.escape(nome)}\n\n"
        "Lo sconto non risulta più disponibile.\n\n"
        f"Categoria: {hashtag}\n\n"
        "Continua a seguirci per le prossime offerte."
    )
    immagine_aggiornata = False
    if foto_file_id:
        try:
            file_telegram = await bot.get_file(foto_file_id)
            dati = await file_telegram.download_as_bytearray()
            foto_terminata = await asyncio.to_thread(crea_immagine_terminata, dati)
            await bot.edit_message_media(
                chat_id=destinazione,
                message_id=message_id,
                media=InputMediaPhoto(
                    media=foto_terminata,
                    caption=didascalia,
                    parse_mode="HTML",
                ),
                reply_markup=None,
            )
            immagine_aggiornata = True
        except Exception as errore:
            print(f"Impossibile aggiornare la foto terminata: {errore}")

    # Fallback per vecchi post o errori nel download della foto Telegram.
    if not immagine_aggiornata:
        await bot.edit_message_caption(
            chat_id=destinazione,
            message_id=message_id,
            caption=didascalia,
            parse_mode="HTML",
        )
        await bot.edit_message_reply_markup(
            chat_id=destinazione,
            message_id=message_id,
            reply_markup=None,
        )
    _segna_offerta_terminata(invio_id)
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        UPDATE recap_offerte SET stato='terminata'
        WHERE asin = (SELECT asin FROM invii_automatici WHERE id = ?)
        """,
        (invio_id,),
    )
    db.commit()
    db.close()


def _prodotti_raccolta_da_verificare():
    """Restituisce i prodotti attivi delle raccolte con la stessa cadenza degli altri post."""
    adesso = datetime.now(ROMA_TZ)
    limite = adesso - timedelta(days=7)
    db = sqlite3.connect(DB_PATH)
    righe = db.execute(
        """
        SELECT p.id, p.raccolta_id, p.asin, p.nome,
               COALESCE(p.verifiche_fallite, 0), p.ultima_verifica,
               r.pubblicata_il, p.prezzo, p.vecchio_prezzo, COALESCE(p.sconto, 0)
        FROM raccolte_casa_prodotti p
        JOIN raccolte_casa r ON r.id = p.raccolta_id
        WHERE p.stato = 'pubblicata' AND r.pubblicata_il >= ?
        ORDER BY r.pubblicata_il DESC, p.posizione
        """,
        (limite.isoformat(timespec="seconds"),),
    ).fetchall()
    db.close()
    risultato = []
    for riga in righe:
        ultima = _data_api(riga[5])
        pubblicata = _data_api(riga[6])
        if not pubblicata:
            continue
        eta = adesso - pubblicata
        if riga[4] > 0:
            intervallo = timedelta(minutes=30)
        elif eta <= timedelta(hours=24):
            intervallo = timedelta(hours=2)
        elif eta <= timedelta(hours=72):
            intervallo = timedelta(hours=6)
        else:
            intervallo = timedelta(hours=24)
        if not ultima or adesso - ultima >= intervallo:
            risultato.append(riga[:5] + riga[7:10])
    return risultato


def _aggiorna_verifica_prodotto_raccolta(prodotto_id, fallita):
    db = sqlite3.connect(DB_PATH)
    adesso = datetime.now(ROMA_TZ).isoformat(timespec="seconds")
    if fallita:
        db.execute(
            """
            UPDATE raccolte_casa_prodotti
            SET verifiche_fallite=COALESCE(verifiche_fallite, 0)+1,
                ultima_verifica=? WHERE id=?
            """,
            (adesso, prodotto_id),
        )
    else:
        db.execute(
            """
            UPDATE raccolte_casa_prodotti
            SET verifiche_fallite=0, ultima_verifica=? WHERE id=?
            """,
            (adesso, prodotto_id),
        )
    db.commit()
    riga = db.execute(
        "SELECT COALESCE(verifiche_fallite, 0) FROM raccolte_casa_prodotti WHERE id=?",
        (prodotto_id,),
    ).fetchone()
    db.close()
    return riga[0] if riga else 0


def _segna_prodotto_raccolta_terminato(prodotto_id):
    db = sqlite3.connect(DB_PATH)
    riga = db.execute(
        "SELECT raccolta_id, asin FROM raccolte_casa_prodotti WHERE id=?",
        (prodotto_id,),
    ).fetchone()
    if not riga:
        db.close()
        return None
    raccolta_id, asin = riga
    db.execute(
        "UPDATE raccolte_casa_prodotti SET stato='terminata' WHERE id=?",
        (prodotto_id,),
    )
    db.execute(
        """
        UPDATE recap_offerte SET stato='terminata'
        WHERE asin=? AND template='raccolta'
          AND telegram_message_id=(
              SELECT telegram_message_id FROM raccolte_casa WHERE id=?
          )
        """,
        (asin, raccolta_id),
    )
    attivi = db.execute(
        "SELECT COUNT(*) FROM raccolte_casa_prodotti WHERE raccolta_id=? AND stato='pubblicata'",
        (raccolta_id,),
    ).fetchone()[0]
    if not attivi:
        db.execute("UPDATE raccolte_casa SET stato='terminata' WHERE id=?", (raccolta_id,))
    db.commit()
    db.close()
    return raccolta_id


def _aggiorna_prodotto_raccolta(prodotto_id, prodotto):
    db = sqlite3.connect(DB_PATH)
    riga = db.execute(
        "SELECT raccolta_id, asin FROM raccolte_casa_prodotti WHERE id=?",
        (prodotto_id,),
    ).fetchone()
    if not riga:
        db.close()
        return None
    raccolta_id, asin = riga
    db.execute(
        """
        UPDATE raccolte_casa_prodotti
        SET nome=?, link=?, prezzo=?, vecchio_prezzo=?, immagine_url=?, sconto=?
        WHERE id=?
        """,
        (
            prodotto["nome"], prodotto["link"], prodotto["prezzo"],
            prodotto.get("vecchio_prezzo"), prodotto.get("immagine"),
            int(prodotto.get("sconto") or 0), prodotto_id,
        ),
    )
    db.execute(
        """
        UPDATE recap_offerte
        SET nome=?, link=?, prezzo=?, vecchio_prezzo=?, sconto=?
        WHERE asin=? AND template='raccolta'
          AND telegram_message_id=(
              SELECT telegram_message_id FROM raccolte_casa WHERE id=?
          )
        """,
        (
            prodotto["nome"], prodotto["link"],
            _prezzo_italiano(prodotto["prezzo_valore"]),
            _prezzo_italiano(prodotto["vecchio_valore"])
            if prodotto.get("vecchio_valore") is not None else "NO",
            int(prodotto.get("sconto") or 0), asin, raccolta_id,
        ),
    )
    db.commit()
    db.close()
    return raccolta_id


def _dati_raccolta_casa(raccolta_id):
    db = sqlite3.connect(DB_PATH)
    raccolta = db.execute(
        """
        SELECT tema, telegram_chat_id, telegram_message_id
        FROM raccolte_casa WHERE id=?
        """,
        (raccolta_id,),
    ).fetchone()
    righe = db.execute(
        """
        SELECT asin, nome, link, prezzo, vecchio_prezzo, immagine_url, sconto, stato
        FROM raccolte_casa_prodotti WHERE raccolta_id=? ORDER BY posizione
        """,
        (raccolta_id,),
    ).fetchall()
    db.close()
    prodotti = [
        {
            "asin": r[0], "nome": r[1], "link": r[2], "prezzo": r[3],
            "vecchio_prezzo": r[4], "immagine": r[5], "sconto": r[6], "stato": r[7],
        }
        for r in righe
    ]
    return raccolta, prodotti


async def _aggiorna_caption_raccolta_casa(bot, raccolta_id):
    raccolta, prodotti = _dati_raccolta_casa(raccolta_id)
    if not raccolta or not prodotti:
        return
    tema, chat_id, message_id = raccolta
    caption = crea_caption_raccolta_casa(prodotti, tema)
    await bot.edit_message_caption(
        chat_id=chat_id or CASA_CHANNEL_ID,
        message_id=message_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=tastiera_raccolta_casa(),
    )
    db = sqlite3.connect(DB_PATH)
    db.execute(
        "UPDATE recap_offerte SET messaggio=? WHERE telegram_message_id=? AND telegram_chat_id=?",
        (caption, message_id, chat_id or str(CASA_CHANNEL_ID)),
    )
    db.commit()
    db.close()


async def controlla_raccolte_casa_terminate(app):
    """Controlla ogni articolo del collage e aggiorna una sola volta la didascalia."""
    righe = _prodotti_raccolta_da_verificare()
    raccolte_modificate = set()
    nomi_terminati = []
    for posizione in range(0, len(righe), 10):
        gruppo = righe[posizione:posizione + 10]
        asins = [riga[2] for riga in gruppo if riga[2]]
        if not asins:
            continue
        try:
            items = await asyncio.to_thread(get_items, asins)
        except Exception as errore:
            print(f"Errore verifica raccolte CASA: {errore}")
            continue
        prodotti_api = {
            getattr(item, "asin", None): estrai_prodotto_creators(item)
            for item in items if getattr(item, "asin", None)
        }
        for (
            prodotto_id, raccolta_id, asin, nome, _,
            prezzo_memorizzato, vecchio_memorizzato, sconto_memorizzato,
        ) in gruppo:
            prodotto = prodotti_api.get(asin)
            non_disponibile = not prodotto
            _aggiorna_verifica_prodotto_raccolta(prodotto_id, non_disponibile)
            if not prodotto:
                # Un risultato API mancante non dimostra che lo sconto sia finito.
                continue
            sconto_azzerato = bool(prodotto and int(prodotto.get("sconto") or 0) == 0)
            if sconto_azzerato:
                raccolta_modificata = _segna_prodotto_raccolta_terminato(prodotto_id)
                if raccolta_modificata:
                    raccolte_modificate.add(raccolta_modificata)
                    nomi_terminati.append(nome)
                continue
            valori_cambiati = (
                int(prodotto.get("sconto") or 0) != int(sconto_memorizzato or 0)
                or _normalizza_valore_monitorato(prodotto.get("prezzo"))
                != _normalizza_valore_monitorato(prezzo_memorizzato)
                or _normalizza_valore_monitorato(prodotto.get("vecchio_prezzo"))
                != _normalizza_valore_monitorato(vecchio_memorizzato)
            )
            if valori_cambiati:
                raccolta_modificata = _aggiorna_prodotto_raccolta(prodotto_id, prodotto)
                if raccolta_modificata:
                    raccolte_modificate.add(raccolta_modificata)
        await asyncio.sleep(1.2)

    for raccolta_id in raccolte_modificate:
        try:
            await _aggiorna_caption_raccolta_casa(app.bot, raccolta_id)
        except Exception as errore:
            print(f"Errore aggiornamento didascalia raccolta CASA: {errore}")
    if nomi_terminati:
        elenco = "\n".join(f"• {nome}" for nome in nomi_terminati[:8])
        await _notifica_admin_automazione(
            app.bot,
            f"🔴 Prodotti terminati nelle raccolte CASA:\n{elenco}",
        )


def _prodotti_raccolta_tech_da_verificare():
    """Restituisce i prodotti attivi delle raccolte con la stessa cadenza degli altri post."""
    adesso = datetime.now(ROMA_TZ)
    limite = adesso - timedelta(days=7)
    db = sqlite3.connect(DB_PATH)
    righe = db.execute(
        """
        SELECT p.id, p.raccolta_id, p.asin, p.nome,
               COALESCE(p.verifiche_fallite, 0), p.ultima_verifica,
               r.pubblicata_il, p.prezzo, p.vecchio_prezzo, COALESCE(p.sconto, 0)
        FROM raccolte_tech_prodotti p
        JOIN raccolte_tech r ON r.id = p.raccolta_id
        WHERE p.stato = 'pubblicata' AND r.pubblicata_il >= ?
        ORDER BY r.pubblicata_il DESC, p.posizione
        """,
        (limite.isoformat(timespec="seconds"),),
    ).fetchall()
    db.close()
    risultato = []
    for riga in righe:
        ultima = _data_api(riga[5])
        pubblicata = _data_api(riga[6])
        if not pubblicata:
            continue
        eta = adesso - pubblicata
        if riga[4] > 0:
            intervallo = timedelta(minutes=30)
        elif eta <= timedelta(hours=24):
            intervallo = timedelta(hours=2)
        elif eta <= timedelta(hours=72):
            intervallo = timedelta(hours=6)
        else:
            intervallo = timedelta(hours=24)
        if not ultima or adesso - ultima >= intervallo:
            risultato.append(riga[:5] + riga[7:10])
    return risultato


def _aggiorna_verifica_prodotto_raccolta_tech(prodotto_id, fallita):
    db = sqlite3.connect(DB_PATH)
    adesso = datetime.now(ROMA_TZ).isoformat(timespec="seconds")
    if fallita:
        db.execute(
            """
            UPDATE raccolte_tech_prodotti
            SET verifiche_fallite=COALESCE(verifiche_fallite, 0)+1,
                ultima_verifica=? WHERE id=?
            """,
            (adesso, prodotto_id),
        )
    else:
        db.execute(
            """
            UPDATE raccolte_tech_prodotti
            SET verifiche_fallite=0, ultima_verifica=? WHERE id=?
            """,
            (adesso, prodotto_id),
        )
    db.commit()
    riga = db.execute(
        "SELECT COALESCE(verifiche_fallite, 0) FROM raccolte_tech_prodotti WHERE id=?",
        (prodotto_id,),
    ).fetchone()
    db.close()
    return riga[0] if riga else 0


def _segna_prodotto_raccolta_tech_terminato(prodotto_id):
    db = sqlite3.connect(DB_PATH)
    riga = db.execute(
        "SELECT raccolta_id, asin FROM raccolte_tech_prodotti WHERE id=?",
        (prodotto_id,),
    ).fetchone()
    if not riga:
        db.close()
        return None
    raccolta_id, asin = riga
    db.execute(
        "UPDATE raccolte_tech_prodotti SET stato='terminata' WHERE id=?",
        (prodotto_id,),
    )
    db.execute(
        """
        UPDATE recap_offerte SET stato='terminata'
        WHERE asin=? AND template='raccolta'
          AND telegram_message_id=(
              SELECT telegram_message_id FROM raccolte_tech WHERE id=?
          )
        """,
        (asin, raccolta_id),
    )
    attivi = db.execute(
        "SELECT COUNT(*) FROM raccolte_tech_prodotti WHERE raccolta_id=? AND stato='pubblicata'",
        (raccolta_id,),
    ).fetchone()[0]
    if not attivi:
        db.execute("UPDATE raccolte_tech SET stato='terminata' WHERE id=?", (raccolta_id,))
    db.commit()
    db.close()
    return raccolta_id


def _aggiorna_prodotto_raccolta_tech(prodotto_id, prodotto):
    db = sqlite3.connect(DB_PATH)
    riga = db.execute(
        "SELECT raccolta_id, asin FROM raccolte_tech_prodotti WHERE id=?",
        (prodotto_id,),
    ).fetchone()
    if not riga:
        db.close()
        return None
    raccolta_id, asin = riga
    db.execute(
        """
        UPDATE raccolte_tech_prodotti
        SET nome=?, link=?, prezzo=?, vecchio_prezzo=?, immagine_url=?, sconto=?
        WHERE id=?
        """,
        (
            prodotto["nome"], prodotto["link"], prodotto["prezzo"],
            prodotto.get("vecchio_prezzo"), prodotto.get("immagine"),
            int(prodotto.get("sconto") or 0), prodotto_id,
        ),
    )
    db.execute(
        """
        UPDATE recap_offerte
        SET nome=?, link=?, prezzo=?, vecchio_prezzo=?, sconto=?
        WHERE asin=? AND template='raccolta'
          AND telegram_message_id=(
              SELECT telegram_message_id FROM raccolte_tech WHERE id=?
          )
        """,
        (
            prodotto["nome"], prodotto["link"],
            _prezzo_italiano(prodotto["prezzo_valore"]),
            _prezzo_italiano(prodotto["vecchio_valore"])
            if prodotto.get("vecchio_valore") is not None else "NO",
            int(prodotto.get("sconto") or 0), asin, raccolta_id,
        ),
    )
    db.commit()
    db.close()
    return raccolta_id


def _dati_raccolta_tech(raccolta_id):
    db = sqlite3.connect(DB_PATH)
    raccolta = db.execute(
        """
        SELECT tema, telegram_chat_id, telegram_message_id
        FROM raccolte_tech WHERE id=?
        """,
        (raccolta_id,),
    ).fetchone()
    righe = db.execute(
        """
        SELECT asin, nome, link, prezzo, vecchio_prezzo, immagine_url, sconto, stato
        FROM raccolte_tech_prodotti WHERE raccolta_id=? ORDER BY posizione
        """,
        (raccolta_id,),
    ).fetchall()
    db.close()
    prodotti = [
        {
            "asin": r[0], "nome": r[1], "link": r[2], "prezzo": r[3],
            "vecchio_prezzo": r[4], "immagine": r[5], "sconto": r[6], "stato": r[7],
        }
        for r in righe
    ]
    return raccolta, prodotti


async def _aggiorna_caption_raccolta_tech(bot, raccolta_id):
    raccolta, prodotti = _dati_raccolta_tech(raccolta_id)
    if not raccolta or not prodotti:
        return
    tema, chat_id, message_id = raccolta
    caption = crea_caption_raccolta_tech(prodotti, tema)
    await bot.edit_message_caption(
        chat_id=chat_id or CHANNEL_ID,
        message_id=message_id,
        caption=caption,
        parse_mode="HTML",
        reply_markup=tastiera_raccolta_tech(),
    )
    db = sqlite3.connect(DB_PATH)
    db.execute(
        "UPDATE recap_offerte SET messaggio=? WHERE telegram_message_id=? AND telegram_chat_id=?",
        (caption, message_id, chat_id or str(CHANNEL_ID)),
    )
    db.commit()
    db.close()


async def controlla_raccolte_tech_terminate(app):
    """Controlla ogni articolo del collage e aggiorna una sola volta la didascalia."""
    righe = _prodotti_raccolta_tech_da_verificare()
    raccolte_modificate = set()
    nomi_terminati = []
    for posizione in range(0, len(righe), 10):
        gruppo = righe[posizione:posizione + 10]
        asins = [riga[2] for riga in gruppo if riga[2]]
        if not asins:
            continue
        try:
            items = await asyncio.to_thread(get_items, asins)
        except Exception as errore:
            print(f"Errore verifica raccolte TECH: {errore}")
            continue
        prodotti_api = {
            getattr(item, "asin", None): estrai_prodotto_creators(item)
            for item in items if getattr(item, "asin", None)
        }
        for (
            prodotto_id, raccolta_id, asin, nome, _,
            prezzo_memorizzato, vecchio_memorizzato, sconto_memorizzato,
        ) in gruppo:
            prodotto = prodotti_api.get(asin)
            non_disponibile = not prodotto
            _aggiorna_verifica_prodotto_raccolta_tech(prodotto_id, non_disponibile)
            if not prodotto:
                # Un risultato API mancante non dimostra che lo sconto sia finito.
                continue
            sconto_azzerato = bool(prodotto and int(prodotto.get("sconto") or 0) == 0)
            if sconto_azzerato:
                raccolta_modificata = _segna_prodotto_raccolta_tech_terminato(prodotto_id)
                if raccolta_modificata:
                    raccolte_modificate.add(raccolta_modificata)
                    nomi_terminati.append(nome)
                continue
            valori_cambiati = (
                int(prodotto.get("sconto") or 0) != int(sconto_memorizzato or 0)
                or _normalizza_valore_monitorato(prodotto.get("prezzo"))
                != _normalizza_valore_monitorato(prezzo_memorizzato)
                or _normalizza_valore_monitorato(prodotto.get("vecchio_prezzo"))
                != _normalizza_valore_monitorato(vecchio_memorizzato)
            )
            if valori_cambiati:
                raccolta_modificata = _aggiorna_prodotto_raccolta_tech(prodotto_id, prodotto)
                if raccolta_modificata:
                    raccolte_modificate.add(raccolta_modificata)
        await asyncio.sleep(1.2)

    for raccolta_id in raccolte_modificate:
        try:
            await _aggiorna_caption_raccolta_tech(app.bot, raccolta_id)
        except Exception as errore:
            print(f"Errore aggiornamento didascalia raccolta TECH: {errore}")
    if nomi_terminati:
        elenco = "\n".join(f"• {nome}" for nome in nomi_terminati[:8])
        await _notifica_admin_automazione(
            app.bot,
            f"🔴 Prodotti terminati nelle raccolte TECH:\n{elenco}",
        )


async def controlla_offerte_terminate(app):
    while True:
        try:
            offerte = _offerte_da_verificare()
            for posizione in range(0, len(offerte), 10):
                gruppo = offerte[posizione:posizione + 10]
                asins = [riga[1] for riga in gruppo if riga[1]]
                if not asins:
                    continue
                try:
                    items = await asyncio.to_thread(get_items, asins)
                except Exception as errore:
                    print(f"Errore verifica disponibilità Creator API: {errore}")
                    continue

                prodotti = {}
                for item in items:
                    asin = getattr(item, "asin", None)
                    if asin:
                        prodotti[asin] = estrai_prodotto_creators(item)

                for (
                    invio_id,
                    asin,
                    nome,
                    categoria,
                    message_id,
                    soglia,
                    _,
                    foto_file_id,
                    sconto_iniziale,
                    sconto_notificato,
                    telegram_chat_id,
                    prezzo_memorizzato,
                    vecchio_memorizzato,
                ) in gruppo:
                    prodotto = prodotti.get(asin)
                    non_disponibile = not prodotto
                    _aggiorna_verifica_offerta(invio_id, non_disponibile)
                    if not prodotto:
                        # Le API possono omettere temporaneamente un ASIN:
                        # senza uno sconto certo allo 0% il post resta invariato.
                        continue

                    sconto_attuale = int(prodotto.get("sconto") or 0)
                    if sconto_attuale == 0:
                        try:
                            await _modifica_post_terminato(
                                app.bot,
                                invio_id,
                                nome,
                                categoria,
                                message_id,
                                foto_file_id,
                                telegram_chat_id,
                            )
                            await _notifica_admin_automazione(
                                app.bot,
                                "🔴 ⛔ OFFERTA TERMINATA\n\n"
                                f"{nome}\n"
                                "Motivo: lo sconto è sceso allo 0%.",
                            )
                        except Exception as errore:
                            print(f"Errore modifica post terminato: {errore}")
                        continue

                    valori_cambiati = (
                        sconto_attuale != int(sconto_iniziale or 0)
                        or _normalizza_valore_monitorato(prodotto.get("prezzo"))
                        != _normalizza_valore_monitorato(prezzo_memorizzato)
                        or _normalizza_valore_monitorato(prodotto.get("vecchio_prezzo"))
                        != _normalizza_valore_monitorato(vecchio_memorizzato)
                    )
                    if valori_cambiati:
                        try:
                            await _aggiorna_post_offerta_attiva(
                                app.bot,
                                invio_id,
                                prodotto,
                                categoria,
                                message_id,
                                telegram_chat_id,
                            )
                            await _notifica_admin_automazione(
                                app.bot,
                                "✏️ OFFERTA AGGIORNATA\n\n"
                                f"{prodotto['nome']}\n"
                                f"Prezzo precedente nel post: {prezzo_memorizzato or 'non registrato'}\n"
                                f"Nuovo prezzo: {prodotto['prezzo']}\n"
                                f"Sconto precedente: -{int(sconto_iniziale or 0)}%\n"
                                f"Nuovo sconto: -{sconto_attuale}%",
                            )
                        except Exception as errore:
                            print(f"Errore aggiornamento prezzo del post: {errore}")

                await asyncio.sleep(1.2)
            await controlla_raccolte_casa_terminate(app)
            await controlla_raccolte_tech_terminate(app)
        except Exception as errore:
            print(f"Errore controllo offerte terminate: {errore}")

        await asyncio.sleep(1800)


# =========================================================
# MENU ADMIN
# =========================================================

def menu_principale():

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎵 AUTOMAZIONE TIKTOK", callback_data="tiktok_menu")],
            [
                InlineKeyboardButton(
                    "📤 PUBBLICA OFFERTA",
                    callback_data="publish_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    "🤖 INVIO AUTOMATICO",
                    callback_data="auto_channels",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔎 CERCA OFFERTE",
                    callback_data="offer_search",
                )
            ],
            [
                InlineKeyboardButton(
                    "📅 POST PROGRAMMATI",
                    callback_data="programmati",
                )
            ],
            [
                InlineKeyboardButton(
                    "📚 STORICO E REINVIO",
                    callback_data="history_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 GESTIONE CLUB",
                    callback_data="admin_club",
                )
            ],
            [
                InlineKeyboardButton(
                    "⚙️ IMPOSTAZIONI",
                    callback_data="settings_menu",
                )
            ],
        ]
    )


def menu_pubblicazione():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 INSERIMENTO DA LINK", callback_data="nuova")],
        [InlineKeyboardButton("⚡ MODALITÀ RAPIDA", callback_data="rapido")],
        [InlineKeyboardButton("⬅️ TORNA AL MENU PRINCIPALE", callback_data="menu_admin")],
    ])


async def mostra_menu_pubblicazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📤 PUBBLICA OFFERTA\n\n"
        "Scegli come vuoi inserire il prodotto.\n\n"
        "Le offerte automatiche vengono inviate al canale corretto in base "
        "alla categoria del prodotto.",
        reply_markup=menu_pubblicazione(),
    )


def menu_storico():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗂 TUTTI I PRODOTTI", callback_data="archive_all")],
        [InlineKeyboardButton("🕒 ULTIME PUBBLICAZIONI", callback_data="ultime")],
        [InlineKeyboardButton("🔁 INVIA DI NUOVO", callback_data="reinvia_menu")],
        [InlineKeyboardButton("⬅️ TORNA AL MENU PRINCIPALE", callback_data="menu_admin")],
    ])


async def mostra_menu_storico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📚 STORICO E REINVIO\n\n"
        "Consulta l'archivio completo, le ultime pubblicazioni oppure scegli un post "
        "da pubblicare nuovamente.",
        reply_markup=menu_storico(),
    )


def menu_impostazioni():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 GESTIONE CANALI", callback_data="channels_manage")],
        [InlineKeyboardButton("🎨 GRAFICA E TEMPLATE", callback_data="template")],
        [InlineKeyboardButton("🎯 FILTRI E PRIORITÀ", callback_data="auto_filtri")],
        [InlineKeyboardButton("📊 STATO DEL BOT", callback_data="bot_status")],
        [InlineKeyboardButton("⬅️ TORNA AL MENU PRINCIPALE", callback_data="menu_admin")],
    ])


async def mostra_menu_impostazioni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚙️ IMPOSTAZIONI\n\n"
        "Gestisci canali, grafica, filtri e stato generale del bot.",
        reply_markup=menu_impostazioni(),
    )


async def mostra_gestione_canali(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📢 GESTIONE CANALI\n\n"
        "📱 TECH — ✅ COLLEGATO\n"
        "🏠 CASA — ✅ COLLEGATO\n\n"
        "Casa e cucina, Elettrodomestici, Fai da te, Giardino, Arredamento "
        "e Illuminazione vengono indirizzati a @BestPrice24hCasa.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 CANALE TECH", callback_data="channel_info_tech")],
            [InlineKeyboardButton("🏠 CANALE CASA", callback_data="channel_info_casa")],
            [InlineKeyboardButton("⬅️ TORNA ALLE IMPOSTAZIONI", callback_data="settings_menu")],
        ]),
    )


async def mostra_info_canale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    if query.data == "channel_info_tech":
        testo = (
            "📱 CANALE TECH\n\n"
            "Stato collegamento: ✅ COLLEGATO\n"
            "Pubblicazioni manuali: ATTIVE\n"
            "Automazione: CONFIGURABILE"
        )
    else:
        testo = (
            "🏠 CANALE CASA\n\n"
            "Stato collegamento: ✅ COLLEGATO\n"
            "Destinazione: @BestPrice24hCasa\n"
            "Automazione: CONFIGURABILE E INDIPENDENTE\n\n"
            "Categorie disponibili: Casa e cucina, Elettrodomestici, "
            "Fai da te, Giardino, Arredamento, Illuminazione."
        )
    await query.edit_message_text(
        testo,
        reply_markup=InlineKeyboardMarkup([
            *([[InlineKeyboardButton("🔗 APRI IL CANALE", url=CASA_CHANNEL_URL)]]
              if query.data == "channel_info_casa" else []),
            [InlineKeyboardButton("⬅️ TORNA AI CANALI", callback_data="channels_manage")]
        ]),
    )


def menu_dopo_pubblicazione():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ INVIA UN NUOVO POST",
                    callback_data="publish_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ TORNA AL MENU PRINCIPALE",
                    callback_data="menu_admin",
                )
            ],
        ]
    )


async def torna_menu_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🔥 AMAZON OFFERTE BOT\n\n"
        "🛠 Modalità amministratore\n\n"
        "Cosa vuoi fare?",
        reply_markup=menu_principale(),
    )



def menu_utente_principale():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📱 TECH & GAMING",
                    url="https://t.me/bestprice_2026",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 CASA & FAI DA TE",
                    url=CASA_CHANNEL_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "🎁 CLUB & PREMI",
                    callback_data="club_home",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 INVITA AMICI",
                    callback_data="club_invita",
                ),
                InlineKeyboardButton(
                    "⭐ I MIEI PUNTI",
                    callback_data="club_punti",
                ),
            ],
        ]
    )


async def torna_menu_utente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🔥 BESTPRICE24H\n\n"
        "Meno offerte. Più affari.\n\n"
        "Scegli cosa vuoi fare 👇",
        reply_markup=menu_utente_principale(),
    )


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return ConversationHandler.END

    # =====================================================
    # ADMIN
    # =====================================================
    if autorizzato(update):

        await update.message.reply_text(
            "🔥 AMAZON OFFERTE BOT\n\n"
            "🛠 Modalità amministratore\n\n"
            "Cosa vuoi fare?",
            reply_markup=menu_principale(),
        )

        return ConversationHandler.END

    # =====================================================
    # UTENTE NORMALE
    # =====================================================
    invitato_da = None

    if context.args:

        try:
            invitato_da = int(context.args[0])

        except (ValueError, TypeError):
            invitato_da = None

    registra_utente(
        user,
        invitato_da
    )

    testo = (
        "🔥 BENVENUTO SU BESTPRICE24H\n\n"
        "Meno offerte. Più affari.\n\n"
        "Qui trovi una selezione delle migliori offerte Amazon, "
        "organizzate per categoria, così puoi seguire solo quello "
        "che ti interessa.\n\n"
        "📲 Scegli i tuoi canali preferiti e non perderti "
        "le occasioni migliori.\n\n"
        "🎁 Con il Club BestPrice24h puoi invitare amici, "
        "accumulare punti e ottenere premi.\n\n"
        "👇 Da dove vuoi iniziare?"
    )

    await update.message.reply_text(
        testo,
        reply_markup=menu_utente_principale(),
    )

    return ConversationHandler.END


# =========================================================
# TELEGRAM ID
# =========================================================

async def mio_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🆔 Il tuo Telegram User ID è:\n\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# LETTURA AUTOMATICA AMAZON
# =========================================================

def leggi_prodotto_amazon(url):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
        "Accept-Language": (
            "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
    }

    try:

        risposta = requests.get(
            url,
            headers=headers,
            timeout=15,
            allow_redirects=True,
        )

        if risposta.status_code != 200:
            return None

        soup = BeautifulSoup(
            risposta.text,
            "html.parser",
        )

        titolo = None
        prezzo = None
        vecchio_prezzo = None
        immagine = None

        selettori_titolo = [
            "#productTitle",
            "#title",
            "h1 span",
        ]

        for selettore in selettori_titolo:

            elemento = soup.select_one(selettore)

            if elemento:

                valore = elemento.get_text(
                    " ",
                    strip=True,
                )

                if valore:
                    titolo = valore
                    break

        selettori_prezzo = [
            ".priceToPay .a-offscreen",
            ".apexPriceToPay .a-offscreen",
            "#corePrice_feature_div .a-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            ".a-price .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
        ]

        for selettore in selettori_prezzo:

            elemento = soup.select_one(selettore)

            if elemento:

                valore = elemento.get_text(
                    " ",
                    strip=True,
                )

                if valore:
                    prezzo = valore
                    break

        selettori_vecchio = [
            ".basisPrice .a-offscreen",
            ".a-price.a-text-price .a-offscreen",
            "#corePrice_feature_div .a-text-price .a-offscreen",
            ".savingPriceOverride .a-price.a-text-price .a-offscreen",
        ]

        for selettore in selettori_vecchio:

            elemento = soup.select_one(selettore)

            if elemento:

                valore = elemento.get_text(
                    " ",
                    strip=True,
                )

                if valore:

                    if prezzo and valore == prezzo:
                        continue

                    vecchio_prezzo = valore
                    break

        elemento_immagine = soup.select_one("#landingImage, #imgBlkFront, #main-image")
        if elemento_immagine:
            immagine = (
                elemento_immagine.get("data-old-hires")
                or elemento_immagine.get("data-a-dynamic-image")
                or elemento_immagine.get("src")
            )
            if immagine and str(immagine).startswith("{"):
                corrispondenza = re.search(r'"(https?://[^"]+)"', immagine)
                immagine = corrispondenza.group(1) if corrispondenza else None

        if not titolo and not prezzo:
            return None

        return {
            "nome": titolo,
            "prezzo": prezzo,
            "vecchio_prezzo": vecchio_prezzo,
            "immagine": immagine,
        }

    except requests.RequestException:
        return None

    except Exception as errore:

        print(
            f"Errore lettura Amazon: {errore}"
        )

        return None


def estrai_asin_da_link(link):
    testo = str(link or "")
    corrispondenza = re.search(
        r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)",
        testo,
        flags=re.IGNORECASE,
    )
    return corrispondenza.group(1).upper() if corrispondenza else None


def risolvi_asin_da_link(link):
    """Estrae l'ASIN anche dai collegamenti brevi amzn.to/amzn.eu."""
    asin = estrai_asin_da_link(link)
    if asin:
        return asin
    try:
        with requests.get(
            link,
            timeout=15,
            allow_redirects=True,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as risposta:
            return estrai_asin_da_link(risposta.url)
    except requests.RequestException:
        return None


def leggi_prodotto_creators_da_link(link):
    """Recupera dati e foto dalle Creator API partendo anche da un link corto."""
    asin = risolvi_asin_da_link(link)
    if not asin:
        return None
    items = get_items([asin])
    if not items:
        return None
    return estrai_prodotto_creators(items[0])


# =========================================================
# NUOVA OFFERTA
# =========================================================

async def nuova_da_comando(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data.clear()

    await update.message.reply_text(
        "🔗 Inviami il link Amazon del prodotto:"
    )

    return LINK


async def nuova_da_pulsante(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query

    await query.answer()

    context.user_data.clear()

    await query.message.reply_text(
        "🔗 Inviami il link Amazon del prodotto:"
    )

    return LINK


# =========================================================
# RICEZIONE LINK
# =========================================================

async def ricevi_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    link = update.message.text.strip()

    if (
        "amazon." not in link
        and "amzn." not in link
    ):

        await update.message.reply_text(
            "❌ Non sembra un link Amazon.\n\n"
            "Inviami un link Amazon valido:"
        )

        return LINK

    context.user_data["link"] = link

    messaggio_attesa = (
        await update.message.reply_text(
            "🔎 Sto provando a leggere automaticamente "
            "i dati del prodotto..."
        )
    )

    dati = None

    # Prima scelta: Creator API, che fornisce anche la foto ufficiale del prodotto.
    try:
        dati_creators = await asyncio.to_thread(leggi_prodotto_creators_da_link, link)
    except Exception as errore:
        print(f"Creator API non disponibile per inserimento manuale: {errore}")
        dati_creators = None

    if dati_creators:
        dati = dati_creators
        context.user_data["foto_url_automatica"] = dati_creators.get("immagine")
        context.user_data["asin"] = dati_creators.get("asin")

    # Se le Creator API non rispondono, prova fino a 3 volte dalla pagina Amazon.
    # Tra un tentativo e l'altro aspetta un attimo, utile quando Amazon
    # risponde in modo incompleto o temporaneamente blocca la richiesta.
    for tentativo in range(1, 4) if not dati else ():

        dati = await asyncio.to_thread(
            leggi_prodotto_amazon,
            link,
        )

        if dati:
            break

        if tentativo < 3:
            await messaggio_attesa.edit_text(
                f"🔎 Tentativo {tentativo}/3 non riuscito.\n"
                "Riprovo automaticamente..."
            )
            await asyncio.sleep(2)

    if dati and dati.get("immagine") and not context.user_data.get("foto_url_automatica"):
        context.user_data["foto_url_automatica"] = dati.get("immagine")

    if not dati:

        await messaggio_attesa.edit_text(
            "⚠️ Non sono riuscito a leggere "
            "automaticamente i dati.\n\n"
            "Nessun problema: continuiamo manualmente.\n\n"
            "📦 Scrivi il nome del prodotto:"
        )

        return NOME

    nome = dati.get("nome")
    prezzo = dati.get("prezzo")
    vecchio = dati.get("vecchio_prezzo")

    if not nome or not prezzo:

        await messaggio_attesa.edit_text(
            "⚠️ Ho trovato solo una parte dei dati.\n\n"
            "Continuiamo manualmente.\n\n"
            "📦 Scrivi il nome del prodotto:"
        )

        return NOME

    context.user_data["nome"] = " ".join(str(nome).split()).strip()
    context.user_data["prezzo"] = pulisci_prezzo(prezzo)

    if vecchio:
        context.user_data["vecchio_prezzo"] = pulisci_prezzo(vecchio)
    else:
        context.user_data["vecchio_prezzo"] = "NO"

    vecchio_testo = context.user_data["vecchio_prezzo"]

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ USA QUESTI DATI",
                    callback_data="dati_ok",
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ INSERISCI MANUALMENTE",
                    callback_data="dati_manual",
                )
            ],
        ]
    )

    await messaggio_attesa.edit_text(
        "✅ DATI TROVATI\n\n"
        f"📦 {context.user_data['nome']}\n\n"
        f"💰 Prezzo: {context.user_data['prezzo']} €\n"
        f"🏷️ Prima: {vecchio_testo}"
        f"{' €' if vecchio_testo != 'NO' else ''}\n\n"
        "Controlla che prezzo e prodotto siano corretti.",
        reply_markup=tastiera,
    )

    return DATI_AUTOMATICI


# =========================================================
# CONFERMA DATI AUTOMATICI
# =========================================================

async def conferma_dati_automatici(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query

    await query.answer()

    if query.data == "dati_ok":

        await query.edit_message_text(
            "✅ Dati confermati."
        )

        return await prova_foto_automatica_o_chiedi(update, context)

    if query.data == "dati_manual":

        link = context.user_data.get("link")
        foto_url_automatica = context.user_data.get("foto_url_automatica")
        asin = context.user_data.get("asin")

        context.user_data.clear()

        context.user_data["link"] = link
        if foto_url_automatica:
            context.user_data["foto_url_automatica"] = foto_url_automatica
        if asin:
            context.user_data["asin"] = asin

        await query.edit_message_text(
            "✏️ Inserimento manuale selezionato."
        )

        await query.message.reply_text(
            "📦 Scrivi il nome del prodotto:"
        )

        return NOME


# =========================================================
# INSERIMENTO MANUALE
# =========================================================

async def ricevi_nome(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data["nome"] = " ".join(
        update.message.text.strip().split()
    )

    await update.message.reply_text(
        "💰 Qual è il prezzo attuale?"
    )

    return PREZZO


async def ricevi_prezzo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data["prezzo"] = pulisci_prezzo(
        update.message.text.strip()
    )

    await update.message.reply_text(
        "🏷️ Qual era il prezzo precedente?\n\n"
        "Oppure scrivi: NO"
    )

    return VECCHIO_PREZZO


async def ricevi_vecchio_prezzo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    valore = update.message.text.strip()

    if valore.upper() == "NO":

        context.user_data["vecchio_prezzo"] = "NO"

    else:

        context.user_data["vecchio_prezzo"] = pulisci_prezzo(
            valore
        )

    return await prova_foto_automatica_o_chiedi(update, context)


# =========================================================
# PULIZIA PREZZO
# =========================================================

def accorcia_nome_articolo(nome):
    """Semplifica i titoli Amazon mantenendo le informazioni più utili."""
    if not nome:
        return ""

    nome = " ".join(str(nome).split()).strip()

    # Elimina ciò che segue separatori tipicamente usati per descrizioni secondarie.
    for separatore in [" | ", " – ", " — "]:
        if separatore in nome:
            parte = nome.split(separatore, 1)[0].strip()
            if len(parte.split()) >= 3:
                nome = parte
                break

    # Espressioni commerciali/accessorie che appesantiscono spesso i titoli Amazon.
    frasi_inutili = [
        r"\bideale per\b",
        r"\bperfetto per\b",
        r"\balta qualità\b",
        r"\bnuovo modello\b",
        r"\bcon tecnologia\b",
        r"\bcompatibile con\b",
        r"\bcompatibile per\b",
        r"\balexa integrata\b",
        r"\bassistente vocale\b",
    ]

    # Se una di queste frasi introduce la parte accessoria finale, la rimuove.
    for frase in frasi_inutili:
        m = re.search(frase, nome, flags=re.IGNORECASE)
        if m and m.start() > 20:
            nome = nome[:m.start()].rstrip(" ,;-")
            break

    # Divide sulle virgole: conserva il nucleo iniziale e solo specifiche brevi/utili.
    parti = [p.strip() for p in nome.split(",") if p.strip()]
    if len(parti) <= 1:
        return nome.rstrip(" ,;-")

    risultato = parti[0]
    parole_chiave = re.compile(
        r"(\b\d+\s?(?:GB|TB|MB|W|mAh|Hz|kHz|MP|L|ml|cm|mm)\b|"
        r"\b\d+(?:[.,]\d+)?[\"”″]\b|"
        r"\b\d+(?:[.,]\d+)?\s?(?:pollici|litri)\b|"
        r"\b4K\b|\b8K\b|\bUHD\b|\bOLED\b|\bQLED\b|\bAMOLED\b|"
        r"\b5G\b|\bWi-?Fi\b|\bBluetooth\b|\bWireless\b|\bUSB-C\b|"
        r"\bPro\b|\bMax\b|\bPlus\b|\bUltra\b|"
        r"\bNero\b|\bBianco\b|\bGrafite\b|\bNavy\b|\bBlu\b|\bRosso\b|\bVerde\b)",
        re.IGNORECASE
    )

    aggiunte = 0
    for parte in parti[1:]:
        if parole_chiave.search(parte):
            candidato = f"{risultato} {parte}".strip()
            if len(candidato) <= 100:
                risultato = candidato
                aggiunte += 1
        if aggiunte >= 2:
            break

    # Nessun puntino di sospensione: restituisce sempre un titolo completo.
    return re.sub(r"\s{2,}", " ", risultato).strip(" ,;-")



def pulisci_prezzo(prezzo):

    if not prezzo:
        return ""

    prezzo = str(prezzo)

    prezzo = prezzo.replace("\xa0", " ")
    prezzo = prezzo.replace("EUR", "")
    prezzo = prezzo.replace("€", "")

    return prezzo.strip()


# =========================================================
# MODALITÀ RAPIDA
# =========================================================

async def rapido_da_comando(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data.clear()

    await update.message.reply_text(
        "⚡ MODALITÀ RAPIDA\n\n"
        "Mandami tutto in una sola riga:\n\n"
        "LINK - NOME - PREZZO - PREZZO PRIMA\n\n"
        "https://www.amazon.it/dp/XXXX "
        "- AirPods Pro "
        "- 199,99 "
        "- 279,99\n\n"
        "Se non c'è il prezzo precedente usa NO."
    )

    return RAPIDO


async def rapido_da_pulsante(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query

    await query.answer()

    context.user_data.clear()

    await query.message.reply_text(
        "⚡ MODALITÀ RAPIDA\n\n"
        "Invia tutto in una sola riga:\n\n"
        "LINK - NOME - PREZZO - PREZZO PRIMA\n\n"
        "https://www.amazon.it/dp/XXXX "
        "- AirPods Pro "
        "- 199,99 "
        "- 279,99\n\n"
        "Senza prezzo precedente:\n"
        "https://www.amazon.it/dp/XXXX "
        "- AirPods Pro "
        "- 199,99 "
        "- NO"
    )

    return RAPIDO


async def ricevi_rapido(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    testo = update.message.text.strip()

    parti = [
        parte.strip()
        for parte in testo.split(
            " - ",
            3,
        )
    ]

    if len(parti) != 4:

        await update.message.reply_text(
            "❌ Formato non corretto.\n\n"
            "Usa esattamente:\n\n"
            "LINK - NOME - PREZZO - PREZZO PRIMA"
        )

        return RAPIDO

    link, nome, prezzo, vecchio = parti

    if (
        "amazon." not in link
        and "amzn." not in link
    ):

        await update.message.reply_text(
            "❌ Il primo campo deve essere un link Amazon."
        )

        return RAPIDO

    context.user_data["link"] = link
    context.user_data["nome"] = " ".join(str(nome).split()).strip()
    context.user_data["prezzo"] = pulisci_prezzo(prezzo)

    if vecchio.upper() == "NO":
        context.user_data["vecchio_prezzo"] = "NO"
    else:
        context.user_data["vecchio_prezzo"] = pulisci_prezzo(vecchio)

    return await prova_foto_automatica_o_chiedi(update, context)



# =========================================================
# RICEZIONE ORA PROGRAMMAZIONE
# =========================================================

async def ricevi_ora_programmazione(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    testo = update.message.text.strip()

    # Accettiamo anche 9:00 oltre a 09:00
    formati = [
        "%H:%M",
    ]

    ora_scelta = None

    for formato in formati:

        try:

            ora_scelta = datetime.strptime(
                testo,
                formato,
            ).time()

            break

        except ValueError:
            pass

    if ora_scelta is None:

        await update.message.reply_text(
            "❌ Orario non corretto.\n\n"
            "Inserisci l'orario nel formato HH:MM."
        )

        return PROGRAMMA_ORA

    data_iso = context.user_data.get(
        "data_programmata"
    )

    if not data_iso:

        await update.message.reply_text(
            "❌ Giorno non trovato.\n"
            "Riprova dalla programmazione."
        )

        return ConversationHandler.END

    data_scelta = datetime.fromisoformat(
        data_iso
    ).date()

    data_locale = datetime.combine(
        data_scelta,
        ora_scelta,
        tzinfo=ROMA_TZ,
    )

    adesso = datetime.now(
        ROMA_TZ
    )

    if data_locale <= adesso:

        await update.message.reply_text(
            "❌ Questo orario è già passato.\n\n"
            "Inserisci un orario futuro."
        )

        return PROGRAMMA_ORA

    conflitti = trova_conflitto(
        data_locale
    )

    if conflitti:

        vicino = conflitti[0]

        context.user_data[
            "data_ora_da_confermare"
        ] = data_locale.isoformat()

        tastiera = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ SÌ, PROGRAMMA",
                    callback_data="conferma_orario_vicino",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 CAMBIA ORARIO",
                    callback_data="cambia_orario",
                )
            ],
        ])

        await update.message.reply_text(
            "⚠️ POST TROPPO VICINO\n\n"
            f"Hai già un'offerta programmata "
            f"alle "
            f"{vicino['datetime'].strftime('%H:%M')}.\n\n"
            f"📦 {vicino['nome']}\n"
            f"💰 {vicino['prezzo']} €\n\n"
            f"Ti consiglio di lasciare almeno "
            f"{DISTANZA_MINIMA_MINUTI} minuti "
            "tra due offerte.\n\n"
            "Vuoi programmarla comunque?",
            reply_markup=tastiera,
        )

        return CONFERMA_ORARIO

    messaggio = context.user_data.get(
        "messaggio"
    )
    link = context.user_data.get(
        "link"
    )
    nome = context.user_data.get(
        "nome"
    )
    prezzo = context.user_data.get(
        "prezzo"
    )

    if not messaggio or not link:

        await update.message.reply_text(
            "❌ Dati dell'offerta mancanti."
        )

        return ConversationHandler.END

    (
        programmazione_id,
        invio_previsto,
    ) = salva_programmazione(
        nome,
        messaggio,
        link,
        prezzo,
        data_locale,
        context.user_data.get("telegram_chat_id", CHANNEL_ID),
    )

    salva_foto_programmazione(
        programmazione_id,
        context.user_data.get("foto_file_id"),
    )

    da_reinvio = context.user_data.get("programmazione_da_reinvio", False)
    context.user_data.clear()

    await update.message.reply_text(
        "✅ OFFERTA PROGRAMMATA!\n\n"
        f"📅 Data: "
        f"{invio_previsto.strftime('%d/%m/%Y')}\n"
        f"🕒 Ora: "
        f"{invio_previsto.strftime('%H:%M')}\n"
        f"📦 {nome}\n"
        f"💰 {prezzo} €\n\n"
        f"🆔 Programmazione: "
        f"#{programmazione_id}",
        reply_markup=menu_principale(),
    )

    if da_reinvio:
        await invia_lista_programmati(update.message)

    return ConversationHandler.END



# =========================================================
# CONTROLLO SLOT PROGRAMMAZIONE
# =========================================================

DISTANZA_MINIMA_MINUTI = 29


def programmazioni_del_giorno(data_locale):

    inizio_locale = datetime.combine(
        data_locale,
        datetime.min.time(),
        tzinfo=ROMA_TZ,
    )

    fine_locale = (
        inizio_locale
        + timedelta(days=1)
    )

    inizio_utc = (
        inizio_locale
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )

    fine_utc = (
        fine_locale
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            id,
            nome,
            prezzo,
            invio_previsto
        FROM programmazioni
        WHERE stato = 'attesa'
          AND invio_previsto >= ?
          AND invio_previsto < ?
        ORDER BY invio_previsto ASC
    """, (
        inizio_utc,
        fine_utc,
    ))

    dati = cur.fetchall()

    db.close()

    risultati = []

    for (
        programmazione_id,
        nome,
        prezzo,
        invio_previsto,
    ) in dati:

        data_utc = datetime.fromisoformat(
            invio_previsto
        )

        if data_utc.tzinfo is None:
            data_utc = data_utc.replace(
                tzinfo=timezone.utc
            )

        data_it = data_utc.astimezone(
            ROMA_TZ
        )

        risultati.append(
            {
                "id": programmazione_id,
                "nome": nome,
                "prezzo": prezzo,
                "datetime": data_it,
            }
        )

    return risultati


def trova_conflitto(
    data_locale,
):

    eventi = programmazioni_del_giorno(
        data_locale.date()
    )

    conflitti = []

    for evento in eventi:

        differenza = abs(
            (
                evento["datetime"]
                - data_locale
            ).total_seconds()
            / 60
        )

        if differenza < DISTANZA_MINIMA_MINUTI:

            conflitti.append(
                {
                    **evento,
                    "differenza": int(
                        differenza
                    ),
                }
            )

    conflitti.sort(
        key=lambda x: x["differenza"]
    )

    return conflitti


def suggerisci_prossimo_slot(
    data_giorno,
):

    eventi = programmazioni_del_giorno(
        data_giorno
    )

    # Orari consigliati di base
    slot_base = [
        "09:00",
        "11:00",
        "13:00",
        "15:30",
        "18:00",
        "20:00",
        "21:30",
    ]

    adesso = datetime.now(
        ROMA_TZ
    )

    for slot in slot_base:

        ora_slot = datetime.strptime(
            slot,
            "%H:%M",
        ).time()

        candidato = datetime.combine(
            data_giorno,
            ora_slot,
            tzinfo=ROMA_TZ,
        )

        if candidato <= adesso:
            continue

        conflitti = trova_conflitto(
            candidato
        )

        if not conflitti:
            return candidato

    # Se gli slot standard sono occupati,
    # cerca slot liberi dalle 09:00 alle 22:30.
    candidato = datetime.combine(
        data_giorno,
        datetime.strptime(
            "09:00",
            "%H:%M",
        ).time(),
        tzinfo=ROMA_TZ,
    )

    fine = datetime.combine(
        data_giorno,
        datetime.strptime(
            "22:30",
            "%H:%M",
        ).time(),
        tzinfo=ROMA_TZ,
    )

    if candidato <= adesso:
        candidato = adesso.replace(
            second=0,
            microsecond=0,
        )

        minuto = candidato.minute

        resto = minuto % 15

        if resto:
            candidato += timedelta(
                minutes=(15 - resto)
            )

    while candidato <= fine:

        conflitti = trova_conflitto(
            candidato
        )

        if not conflitti:
            return candidato

        candidato += timedelta(
            minutes=15
        )

    return None



# =========================================================
# CONFERMA ORARIO VICINO
# =========================================================

async def conferma_orario_vicino(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query

    await query.answer()

    if query.data == "cambia_orario":

        await query.message.reply_text(
            "🕒 Scrivi un nuovo orario."
        )

        return PROGRAMMA_ORA

    data_iso = context.user_data.get(
        "data_ora_da_confermare"
    )

    if not data_iso:

        await query.message.reply_text(
            "❌ Dati programmazione mancanti."
        )

        return ConversationHandler.END

    data_locale = datetime.fromisoformat(
        data_iso
    )

    messaggio = context.user_data.get(
        "messaggio"
    )
    link = context.user_data.get(
        "link"
    )
    nome = context.user_data.get(
        "nome"
    )
    prezzo = context.user_data.get(
        "prezzo"
    )

    if not messaggio or not link:

        await query.message.reply_text(
            "❌ Dati dell'offerta mancanti."
        )

        return ConversationHandler.END

    (
        programmazione_id,
        invio_previsto,
    ) = salva_programmazione(
        nome,
        messaggio,
        link,
        prezzo,
        data_locale,
        context.user_data.get("telegram_chat_id", CHANNEL_ID),
    )

    salva_foto_programmazione(
        programmazione_id,
        context.user_data.get("foto_file_id"),
    )

    da_reinvio = context.user_data.get("programmazione_da_reinvio", False)
    context.user_data.clear()

    await query.message.reply_text(
        "✅ OFFERTA PROGRAMMATA!\n\n"
        f"📅 Data: "
        f"{invio_previsto.strftime('%d/%m/%Y')}\n"
        f"🕒 Ora: "
        f"{invio_previsto.strftime('%H:%M')}\n"
        f"📦 {nome}\n"
        f"💰 {prezzo} €\n\n"
        f"🆔 Programmazione: "
        f"#{programmazione_id}",
        reply_markup=menu_principale(),
    )

    if da_reinvio:
        await invia_lista_programmati(query.message)

    return ConversationHandler.END


# =========================================================
# GESTIONE POST PROGRAMMATI
# =========================================================

def data_programmata_locale(invio_previsto):

    try:

        data_utc = datetime.fromisoformat(
            invio_previsto
        )

        if data_utc.tzinfo is None:
            data_utc = data_utc.replace(
                tzinfo=timezone.utc
            )

        return data_utc.astimezone(
            ROMA_TZ
        )

    except Exception:
        return None


def leggi_programmato(programmazione_id):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            id,
            nome,
            messaggio,
            link,
            prezzo,
            COALESCE(vecchio_prezzo, 'NO'),
            COALESCE(template, 'pulito'),
            foto_file_id,
            invio_previsto,
            stato
        FROM programmazioni
        WHERE id = ?
    """, (programmazione_id,))

    riga = cur.fetchone()

    db.close()

    if not riga:
        return None

    return {
        "id": riga[0],
        "nome": riga[1],
        "messaggio": riga[2],
        "link": riga[3],
        "prezzo": riga[4],
        "vecchio_prezzo": riga[5] or "NO",
        "template": riga[6] or "pulito",
        "foto_file_id": riga[7],
        "invio_previsto": riga[8],
        "stato": riga[9],
    }


def crea_messaggio_programmato(
    nome,
    prezzo,
    vecchio,
    template,
):

    vecchio = vecchio or "NO"
    template = template or "pulito"

    sconto = None

    if str(vecchio).upper() != "NO":

        sconto = calcola_sconto(
            prezzo,
            vecchio,
        )

    if template == "aggressivo":

        testo = (
            "🚨 SUPER OFFERTA AMAZON 🚨\n\n"
            f"🔥 {nome}\n\n"
        )

        if str(vecchio).upper() != "NO":
            testo += (
                f"❌ Prima: {vecchio} €\n"
            )

        testo += f"✅ ORA: {prezzo} €\n"

        if sconto is not None:
            testo += (
                f"\n💥 SCONTO {sconto}%"
            )

        testo += (
            "\n\n⚡ Approfittane prima "
            "che cambi il prezzo!"
        )

        return testo

    if template == "tech":

        testo = (
            "⚡ TECH DEAL\n\n"
            f"📱 {nome}\n\n"
        )

        if str(vecchio).upper() != "NO":
            testo += (
                f"🏷️ Listino: {vecchio} €\n"
            )

        testo += (
            f"💰 Offerta: {prezzo} €\n"
        )

        if sconto is not None:
            testo += f"📉 -{sconto}%"

        return testo

    testo = (
        "🔥 OFFERTA AMAZON\n\n"
        f"📦 {nome}\n\n"
    )

    if str(vecchio).upper() != "NO":
        testo += (
            f"❌ Prima: {vecchio} €\n"
        )

    testo += f"✅ Ora: {prezzo} €\n"

    if sconto is not None:
        testo += (
            f"\n🔥 Sconto: {sconto}%"
        )

    return testo


def aggiorna_messaggio_programmato(
    programmazione_id,
):

    post = leggi_programmato(
        programmazione_id
    )

    if not post:
        return False

    messaggio = crea_messaggio_programmato(
        post["nome"],
        post["prezzo"],
        post["vecchio_prezzo"],
        post["template"],
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET messaggio = ?
        WHERE id = ?
    """, (
        messaggio,
        programmazione_id,
    ))

    db.commit()
    db.close()

    return True


async def invia_lista_programmati(
    messaggio,
):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            id,
            nome,
            prezzo,
            invio_previsto
        FROM programmazioni
        WHERE stato = 'attesa'
        ORDER BY invio_previsto ASC
        LIMIT 100
    """)

    righe_db = cur.fetchall()

    db.close()

    if not righe_db:

        await messaggio.reply_text(
            "📅 POST PROGRAMMATI\n\n"
            "Non ci sono offerte programmate.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ TORNA AL MENU PRINCIPALE",
                            callback_data="prog_esci",
                        )
                    ]
                ]
            ),
        )

        return

    righe = [
        "📅 POST PROGRAMMATI\n"
    ]

    for (
        programmazione_id,
        nome,
        prezzo,
        invio_previsto,
    ) in righe_db:

        data_locale = data_programmata_locale(
            invio_previsto
        )

        if data_locale:
            quando = data_locale.strftime(
                "%d/%m • %H:%M"
            )
        else:
            quando = invio_previsto

        righe.append(
            f"#{programmazione_id} • {quando}\n"
            f"📦 {nome} — {prezzo} €\n"
        )

    righe.append(
        "\n🔢 Scrivi il numero # del post "
        "che vuoi gestire.\n\n"
    )

    await messaggio.reply_text(
        "\n".join(righe),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ TORNA AL MENU PRINCIPALE",
                        callback_data="prog_esci",
                    )
                ]
            ]
        ),
    )


async def mostra_programmati(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query

    if query:
        await query.answer()
        messaggio = query.message
    else:
        messaggio = update.message

    context.user_data.pop(
        "prog_id",
        None,
    )

    # Pulisce eventuali stati rimasti dal flusso "Invia di nuovo".
    # Così il numero digitato qui viene sempre interpretato come ID
    # del post programmato da gestire/modificare, mai come un orario.
    for chiave in (
        "attesa_ora_reinvio",
        "reinvia_data",
        "reinvia_edit_state",
        "reinvia_attesa_foto",
        "programmazione_da_reinvio",
    ):
        context.user_data.pop(chiave, None)

    await invia_lista_programmati(
        messaggio
    )

    return PROG_SELEZIONE


async def seleziona_programmato(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    testo = update.message.text.strip()

    testo = testo.replace("#", "").strip()

    if not testo.isdigit():

        await update.message.reply_text(
            "❌ Scrivi solo il numero del post.\n\n"
            )

        return PROG_SELEZIONE

    programmazione_id = int(testo)

    post = leggi_programmato(
        programmazione_id
    )

    if (
        not post
        or post["stato"] != "attesa"
    ):

        await update.message.reply_text(
            "❌ Non trovo un post programmato "
            f"attivo con ID #{programmazione_id}.\n\n"
            "Scrivi un altro numero."
        )

        return PROG_SELEZIONE

    context.user_data[
        "prog_id"
    ] = programmazione_id

    await invia_scheda_programmato(
        update.message,
        programmazione_id,
    )

    return PROG_GESTIONE


async def invia_scheda_programmato(
    messaggio,
    programmazione_id,
):

    post = leggi_programmato(
        programmazione_id
    )

    if not post:
        return

    data_locale = data_programmata_locale(
        post["invio_previsto"]
    )

    quando = (
        data_locale.strftime(
            "%d/%m/%Y • %H:%M"
        )
        if data_locale
        else post["invio_previsto"]
    )

    messaggio_post = post["messaggio"]
    messaggio_html = messaggio_post.startswith("__RICERCA_HTML__")
    if messaggio_html:
        messaggio_post = messaggio_post.replace("__RICERCA_HTML__", "", 1)
    testo = (
        f"📅 POST PROGRAMMATO #{post['id']}\n"
        f"🕒 {quando}\n\n"
        "👀 ANTEPRIMA\n\n"
        + crea_caption_con_link(
            messaggio_post,
            post["link"],
            messaggio_gia_html=messaggio_html,
        )
    )

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛒 APRI",
                    url=post["link"],
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ MODIFICA",
                    callback_data="prog_modifica",
                ),
                InlineKeyboardButton(
                    "🗑 ELIMINA",
                    callback_data="prog_elimina",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ TORNA AI PROGRAMMATI",
                    callback_data="prog_indietro",
                )
            ],
        ]
    )

    if post.get("foto_file_id"):
        await messaggio.reply_photo(
            photo=post["foto_file_id"],
            caption=testo,
            parse_mode="HTML",
            reply_markup=tastiera,
        )
    else:
        await messaggio.reply_text(
            testo,
            parse_mode="HTML",
            reply_markup=tastiera,
        )


async def gestisci_programmato(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:

        await query.message.reply_text(
            "❌ Post non selezionato."
        )

        return PROG_SELEZIONE

    if query.data == "prog_indietro":

        context.user_data.pop(
            "prog_id",
            None,
        )

        await invia_lista_programmati(
            query.message
        )

        return PROG_SELEZIONE

    if query.data == "prog_elimina":

        post = leggi_programmato(
            programmazione_id
        )

        if not post:
            return PROG_SELEZIONE

        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ SÌ, ELIMINA",
                        callback_data="prog_elimina_si",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ ANNULLA",
                        callback_data="prog_elimina_no",
                    )
                ],
            ]
        )

        await query.message.reply_text(
            "⚠️ ELIMINARE QUESTO POST?\n\n"
            f"#{programmazione_id}\n"
            f"📦 {post['nome']}\n"
            f"💰 {post['prezzo']} €",
            reply_markup=tastiera,
        )

        return PROG_GESTIONE

    if query.data == "prog_modifica":

        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📦 NOME",
                        callback_data="prog_edit_nome",
                    ),
                    InlineKeyboardButton(
                        "💰 PREZZO",
                        callback_data="prog_edit_prezzo",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🏷 PREZZO PRIMA",
                        callback_data="prog_edit_vecchio",
                    ),
                    InlineKeyboardButton(
                        "🔗 LINK",
                        callback_data="prog_edit_link",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🖼 IMMAGINE",
                        callback_data="prog_edit_immagine",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🕒 DATA E ORA",
                        callback_data="prog_edit_dataora",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🎨 TEMPLATE",
                        callback_data="prog_edit_template",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ INDIETRO",
                        callback_data="prog_torna_scheda",
                    )
                ],
            ]
        )

        await query.message.reply_text(
            "✏️ COSA VUOI MODIFICARE?",
            reply_markup=tastiera,
        )

        return PROG_MODIFICA_MENU

    if query.data == "prog_elimina_no":

        await invia_scheda_programmato(
            query.message,
            programmazione_id,
        )

        return PROG_GESTIONE

    if query.data == "prog_elimina_si":

        db = sqlite3.connect(DB_PATH)
        cur = db.cursor()

        cur.execute("""
            UPDATE programmazioni
            SET stato = 'annullata'
            WHERE id = ?
              AND stato = 'attesa'
        """, (
            programmazione_id,
        ))

        modificati = cur.rowcount

        db.commit()
        db.close()

        if modificati:

            await query.message.reply_text(
                f"🗑 Post #{programmazione_id} "
                "eliminato dalla programmazione."
            )

        else:

            await query.message.reply_text(
                "❌ Il post non è più disponibile."
            )

        context.user_data.pop(
            "prog_id",
            None,
        )

        await invia_lista_programmati(
            query.message
        )

        return PROG_SELEZIONE

    return PROG_GESTIONE


async def menu_modifica_programmato(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    if query.data == "prog_torna_scheda":

        await invia_scheda_programmato(
            query.message,
            programmazione_id,
        )

        return PROG_GESTIONE

    if query.data == "prog_edit_nome":

        await query.message.reply_text(
            "📦 Scrivi il nuovo nome del prodotto:"
        )

        return PROG_EDIT_NOME

    if query.data == "prog_edit_prezzo":

        await query.message.reply_text(
            "💰 Scrivi il nuovo prezzo attuale.\n\n"
        )

        return PROG_EDIT_PREZZO

    if query.data == "prog_edit_vecchio":

        await query.message.reply_text(
            "🏷 Scrivi il nuovo prezzo precedente.\n\n"
            "Oppure scrivi NO."
        )

        return PROG_EDIT_VECCHIO

    if query.data == "prog_edit_link":

        await query.message.reply_text(
            "🔗 Inviami il nuovo link Amazon:"
        )

        return PROG_EDIT_LINK

    if query.data == "prog_edit_immagine":

        post = leggi_programmato(
            programmazione_id
        )

        if not post:
            return PROG_GESTIONE

        if post.get("foto_file_id"):

            tastiera = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 SOSTITUISCI IMMAGINE",
                            callback_data="prog_img_sostituisci",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🗑 RIMUOVI IMMAGINE",
                            callback_data="prog_img_rimuovi",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ INDIETRO",
                            callback_data="prog_img_indietro",
                        )
                    ],
                ]
            )

        else:

            tastiera = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📷 AGGIUNGI IMMAGINE",
                            callback_data="prog_img_aggiungi",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ INDIETRO",
                            callback_data="prog_img_indietro",
                        )
                    ],
                ]
            )

        await query.message.reply_text(
            "🖼 GESTIONE IMMAGINE",
            reply_markup=tastiera,
        )

        return PROG_IMMAGINE_MENU

    if query.data == "prog_edit_dataora":

        await query.message.reply_text(
            "🕒 Scrivi nuova data e ora nel formato:\n\n"
            "25/08/2026 18:30"
        )

        return PROG_EDIT_DATA_ORA

    if query.data == "prog_edit_template":

        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✨ PULITO",
                        callback_data="prog_tpl_pulito",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🚨 AGGRESSIVO",
                        callback_data="prog_tpl_aggressivo",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⚡ TECH",
                        callback_data="prog_tpl_tech",
                    )
                ],
            ]
        )

        await query.message.reply_text(
            "🎨 Scegli il nuovo template:",
            reply_markup=tastiera,
        )

        return PROG_MODIFICA_MENU

    if query.data.startswith("prog_tpl_"):

        template = query.data.replace(
            "prog_tpl_",
            "",
        )

        db = sqlite3.connect(DB_PATH)
        cur = db.cursor()

        cur.execute("""
            UPDATE programmazioni
            SET template = ?
            WHERE id = ?
              AND stato = 'attesa'
        """, (
            template,
            programmazione_id,
        ))

        db.commit()
        db.close()

        aggiorna_messaggio_programmato(
            programmazione_id
        )

        await query.message.reply_text(
            "✅ Template aggiornato."
        )

        await invia_scheda_programmato(
            query.message,
            programmazione_id,
        )

        return PROG_GESTIONE

    return PROG_MODIFICA_MENU


async def salva_modifica_testuale_programmato(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    valore = update.message.text.strip()

    stato = context.user_data.get(
        "prog_edit_state"
    )

    # Lo stato viene impostato dai wrapper sotto.
    if stato == "nome":

        if not valore:

            await update.message.reply_text(
                "❌ Il nome non può essere vuoto."
            )

            return PROG_EDIT_NOME

        colonna = "nome"
        nuovo_valore = valore

    elif stato == "prezzo":

        nuovo_valore = pulisci_prezzo(
            valore
        )

        if not nuovo_valore:

            await update.message.reply_text(
                "❌ Prezzo non valido."
            )

            return PROG_EDIT_PREZZO

        colonna = "prezzo"

    elif stato == "vecchio":

        if valore.upper() == "NO":
            nuovo_valore = "NO"
        else:
            nuovo_valore = pulisci_prezzo(
                valore
            )

        colonna = "vecchio_prezzo"

    elif stato == "link":

        if (
            "amazon." not in valore
            and "amzn." not in valore
        ):

            await update.message.reply_text(
                "❌ Non sembra un link Amazon.\n"
                "Invia un link valido."
            )

            return PROG_EDIT_LINK

        colonna = "link"
        nuovo_valore = valore

    else:
        return PROG_GESTIONE

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute(
        f"""
        UPDATE programmazioni
        SET {colonna} = ?
        WHERE id = ?
          AND stato = 'attesa'
        """,
        (
            nuovo_valore,
            programmazione_id,
        ),
    )

    db.commit()
    db.close()

    if colonna in (
        "nome",
        "prezzo",
        "vecchio_prezzo",
    ):

        aggiorna_messaggio_programmato(
            programmazione_id
        )

    context.user_data.pop(
        "prog_edit_state",
        None,
    )

    await update.message.reply_text(
        "✅ Post programmato aggiornato."
    )

    await invia_scheda_programmato(
        update.message,
        programmazione_id,
    )

    return PROG_GESTIONE


async def edit_programmato_nome(
    update,
    context,
):

    context.user_data[
        "prog_edit_state"
    ] = "nome"

    return await salva_modifica_testuale_programmato(
        update,
        context,
    )


async def edit_programmato_prezzo(
    update,
    context,
):

    context.user_data[
        "prog_edit_state"
    ] = "prezzo"

    return await salva_modifica_testuale_programmato(
        update,
        context,
    )


async def edit_programmato_vecchio(
    update,
    context,
):

    context.user_data[
        "prog_edit_state"
    ] = "vecchio"

    return await salva_modifica_testuale_programmato(
        update,
        context,
    )


async def edit_programmato_link(
    update,
    context,
):

    context.user_data[
        "prog_edit_state"
    ] = "link"

    return await salva_modifica_testuale_programmato(
        update,
        context,
    )


async def edit_programmato_dataora(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    valore = update.message.text.strip()

    try:

        data_locale = datetime.strptime(
            valore,
            "%d/%m/%Y %H:%M",
        ).replace(
            tzinfo=ROMA_TZ
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Formato non valido.\n\n"
            "Usa: 25/08/2026 18:30"
        )

        return PROG_EDIT_DATA_ORA

    if data_locale <= datetime.now(
        ROMA_TZ
    ):

        await update.message.reply_text(
            "❌ La nuova data/ora deve "
            "essere nel futuro."
        )

        return PROG_EDIT_DATA_ORA

    conflitti = trova_conflitto(
        data_locale
    )

    conflitti = [
        evento
        for evento in conflitti
        if evento["id"] != programmazione_id
    ]

    if conflitti:

        vicino = conflitti[0]

        await update.message.reply_text(
            "⚠️ Attenzione: c'è già un post "
            "programmato vicino a questo orario.\n\n"
            f"📦 {vicino['nome']}\n"
            f"🕒 {vicino['datetime'].strftime('%H:%M')}\n\n"
            "La modifica viene comunque salvata."
        )

    data_utc = data_locale.astimezone(
        timezone.utc
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET invio_previsto = ?
        WHERE id = ?
          AND stato = 'attesa'
    """, (
        data_utc.isoformat(
            timespec="seconds"
        ),
        programmazione_id,
    ))

    db.commit()
    db.close()

    await update.message.reply_text(
        "✅ Data e ora aggiornate."
    )

    await invia_scheda_programmato(
        update.message,
        programmazione_id,
    )

    return PROG_GESTIONE



async def gestisci_immagine_programmata(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    if query.data == "prog_img_indietro":

        await query.message.reply_text(
            "✏️ Torna alla modifica del post.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ MODIFICA POST",
                            callback_data="prog_modifica",
                        )
                    ]
                ]
            ),
        )

        return PROG_GESTIONE

    if query.data in (
        "prog_img_aggiungi",
        "prog_img_sostituisci",
    ):

        await query.message.reply_text(
            "📷 Inviami la nuova immagine."
        )

        return PROG_IMMAGINE_ATTESA

    if query.data == "prog_img_rimuovi":

        db = sqlite3.connect(DB_PATH)
        cur = db.cursor()

        cur.execute("""
            UPDATE programmazioni
            SET foto_file_id = NULL
            WHERE id = ?
              AND stato = 'attesa'
        """, (
            programmazione_id,
        ))

        db.commit()
        db.close()

        await query.message.reply_text(
            "✅ Immagine rimossa."
        )

        await invia_scheda_programmato(
            query.message,
            programmazione_id,
        )

        return PROG_GESTIONE

    return PROG_IMMAGINE_MENU


async def ricevi_immagine_programmata(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(
        update
    ):
        return ConversationHandler.END

    if not update.message.photo:

        await update.message.reply_text(
            "❌ Inviami una foto valida."
        )

        return PROG_IMMAGINE_ATTESA

    programmazione_id = context.user_data.get(
        "prog_id"
    )

    if not programmazione_id:
        return PROG_SELEZIONE

    foto_file_id = (
        update.message.photo[-1].file_id
    )

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        UPDATE programmazioni
        SET foto_file_id = ?
        WHERE id = ?
          AND stato = 'attesa'
    """, (
        foto_file_id,
        programmazione_id,
    ))

    db.commit()
    db.close()

    await update.message.reply_text(
        "✅ Immagine aggiornata."
    )

    await invia_scheda_programmato(
        update.message,
        programmazione_id,
    )

    return PROG_GESTIONE


async def esci_programmati(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    context.user_data.pop(
        "prog_id",
        None,
    )
    context.user_data.pop(
        "prog_edit_state",
        None,
    )

    await query.message.reply_text(
        "🔥 AMAZON OFFERTE BOT\n\n"
        "🛠 Modalità amministratore\n\n"
        "Cosa vuoi fare?",
        reply_markup=menu_principale(),
    )

    return ConversationHandler.END


# =========================================================
# CALCOLO SCONTO
# =========================================================

def numero_da_prezzo(valore):

    if not valore:
        return None

    valore = (
        valore
        .replace("€", "")
        .replace("EUR", "")
        .replace(" ", "")
        .strip()
    )

    if "," in valore:

        valore = valore.replace(".", "")
        valore = valore.replace(",", ".")

    try:
        return float(valore)

    except ValueError:
        return None


def calcola_sconto(
    prezzo,
    vecchio,
):

    nuovo = numero_da_prezzo(prezzo)
    precedente = numero_da_prezzo(vecchio)

    if (
        nuovo is None
        or precedente is None
        or precedente <= 0
    ):
        return None

    return round(
        (1 - nuovo / precedente)
        * 100
    )


# =========================================================
# TEMPLATE MESSAGGI
# =========================================================

def crea_messaggio(context):

    nome = context.user_data["nome"]
    prezzo = context.user_data["prezzo"]
    vecchio = context.user_data["vecchio_prezzo"]

    template = context.user_data.get(
        "template",
        "pulito",
    )

    sconto = None

    if vecchio.upper() != "NO":

        sconto = calcola_sconto(
            prezzo,
            vecchio,
        )

    # AGGRESSIVO
    if template == "aggressivo":

        testo = (
            "🚨 SUPER OFFERTA AMAZON 🚨\n\n"
            f"🔥 {nome}\n\n"
        )

        if vecchio.upper() != "NO":
            testo += f"❌ Prima: {vecchio} €\n"

        testo += f"✅ ORA: {prezzo} €\n"

        if sconto is not None:
            testo += f"\n💥 SCONTO {sconto}%"

        testo += (
            "\n\n⚡ Approfittane prima che cambi il prezzo!"
        )

        return testo

    # TECH
    if template == "tech":

        testo = (
            "⚡ TECH DEAL\n\n"
            f"📱 {nome}\n\n"
        )

        if vecchio.upper() != "NO":
            testo += f"🏷️ Listino: {vecchio} €\n"

        testo += f"💰 Offerta: {prezzo} €\n"

        if sconto is not None:
            testo += f"📉 -{sconto}%"

        return testo

    # PULITO
    testo = (
        "🔥 OFFERTA AMAZON\n\n"
        f"📦 {nome}\n\n"
    )

    if vecchio.upper() != "NO":
        testo += f"❌ Prima: {vecchio} €\n"

    testo += f"✅ Ora: {prezzo} €\n"

    if sconto is not None:
        testo += f"\n🔥 Sconto: {sconto}%"

    return testo



async def prova_foto_automatica_o_chiedi(update, context):
    """Cerca e brandizza la foto; se non riesce passa alla scelta manuale."""
    messaggio = update.message if update.message else update.callback_query.message
    foto_url = context.user_data.get("foto_url_automatica")
    if not foto_url:
        link = context.user_data.get("link")
        try:
            prodotto = await asyncio.to_thread(leggi_prodotto_creators_da_link, link)
        except Exception as errore:
            print(f"Errore ricerca foto Creator API: {errore}")
            prodotto = None
        if prodotto:
            foto_url = prodotto.get("immagine")
            context.user_data["foto_url_automatica"] = foto_url

    if foto_url:
        attesa = await messaggio.reply_text(
            "🖼 Foto trovata. Creo automaticamente la locandina BestPrice24h…"
        )
        try:
            foto_brandizzata = await asyncio.to_thread(crea_immagine_brandizzata, foto_url)
            context.user_data["foto_file_id"] = foto_brandizzata
            await attesa.edit_text("✅ Foto trovata e locandina creata.")
            return await mostra_anteprima(update, context)
        except Exception as errore:
            print(f"Errore locandina automatica manuale: {errore}")
            context.user_data.pop("foto_file_id", None)
            await attesa.edit_text(
                "⚠️ Non sono riuscito a preparare automaticamente la foto."
            )

    return await chiedi_immagine(update, context)


async def chiedi_immagine(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📷 AGGIUNGI IMMAGINE",
                    callback_data="foto_aggiungi",
                )
            ],
            [
                InlineKeyboardButton(
                    "➡️ CONTINUA SENZA IMMAGINE",
                    callback_data="foto_salta",
                )
            ],
        ]
    )

    if update.message:
        await update.message.reply_text(
            "🖼 Vuoi aggiungere un'immagine al post?",
            reply_markup=tastiera,
        )
    else:
        await update.callback_query.message.reply_text(
            "🖼 Vuoi aggiungere un'immagine al post?",
            reply_markup=tastiera,
        )

    return FOTO_SCELTA


async def scelta_immagine(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    if query.data == "foto_salta":
        context.user_data.pop(
            "foto_file_id",
            None,
        )

        await query.edit_message_text(
            "➡️ Continuo senza immagine."
        )

        return await mostra_anteprima(
            update,
            context,
        )

    if query.data == "foto_aggiungi":
        await query.edit_message_text(
            "📷 Inviami la foto del prodotto."
        )
        return FOTO_ATTESA

    return FOTO_SCELTA


async def ricevi_immagine(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message.photo:
        await update.message.reply_text(
            "❌ Inviami una foto valida."
        )
        return FOTO_ATTESA

    foto = update.message.photo[-1]
    try:
        file_telegram = await foto.get_file()
        contenuto = await file_telegram.download_as_bytearray()
        foto_brandizzata = await asyncio.to_thread(
            crea_immagine_brandizzata_da_bytes,
            bytes(contenuto),
        )
        context.user_data["foto_file_id"] = foto_brandizzata
        await update.message.reply_text("✅ Immagine aggiunta e locandina creata.")
    except Exception as errore:
        print(f"Errore brandizzazione foto manuale: {errore}")
        context.user_data["foto_file_id"] = foto.file_id
        await update.message.reply_text(
            "⚠️ Ho aggiunto la foto originale perché non sono riuscito a creare la locandina."
        )

    return await mostra_anteprima(
        update,
        context,
    )


# =========================================================
# ANTEPRIMA
# =========================================================

async def mostra_anteprima(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    messaggio = crea_messaggio(
        context
    )

    context.user_data["messaggio"] = messaggio

    link = context.user_data.get(
        "link",
        "",
    )

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📤 PUBBLICA ORA",
                    callback_data="pubblica",
                )
            ],
            [
                InlineKeyboardButton(
                    "🕒 PROGRAMMA INVIO",
                    callback_data="programma",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎨 CAMBIA TEMPLATE",
                    callback_data="cambia_template",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ ANNULLA",
                    callback_data="annulla",
                )
            ],
        ]
    )

    testo = (
        "👀 ANTEPRIMA\n\n"
        "──────────────\n\n"
        + crea_caption_con_link(messaggio, link)
    )

    foto_file_id = context.user_data.get(
        "foto_file_id"
    )

    if update.message:

        if foto_file_id:
            inviato = await update.message.reply_photo(
                photo=foto_file_id,
                caption=testo,
                parse_mode="HTML",
                reply_markup=tastiera,
            )
            if inviato.photo:
                context.user_data["foto_file_id"] = inviato.photo[-1].file_id
        else:
            await update.message.reply_text(
                testo,
                parse_mode="HTML",
                reply_markup=tastiera,
            )

    else:

        if foto_file_id:
            inviato = await update.callback_query.message.reply_photo(
                photo=foto_file_id,
                caption=testo,
                parse_mode="HTML",
                reply_markup=tastiera,
            )
            if inviato.photo:
                context.user_data["foto_file_id"] = inviato.photo[-1].file_id
        else:
            await update.callback_query.message.reply_text(
                testo,
                parse_mode="HTML",
                reply_markup=tastiera,
            )

    return CONFERMA


# =========================================================
# CONTROLLO DISTANZA INVII MANUALI
# =========================================================

def minuti_rimanenti_prima_del_prossimo_invio():

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT pubblicata_il
        FROM recap_offerte
        ORDER BY pubblicata_il DESC
        LIMIT 1
    """)

    riga = cur.fetchone()
    db.close()

    if not riga or not riga[0]:
        return 0

    try:
        ultimo_invio = datetime.fromisoformat(riga[0])

        if ultimo_invio.tzinfo is None:
            ultimo_invio = ultimo_invio.replace(tzinfo=ROMA_TZ)
        else:
            ultimo_invio = ultimo_invio.astimezone(ROMA_TZ)

        trascorsi = (
            datetime.now(ROMA_TZ) - ultimo_invio
        ).total_seconds() / 60

        rimanenti = DISTANZA_MINIMA_MINUTI - trascorsi

        if rimanenti <= 0:
            return 0

        # Arrotondiamo per eccesso: a 30 minuti con limite 31 mostra 1 minuto.
        return max(1, int(rimanenti) + (0 if rimanenti.is_integer() else 1))

    except Exception:
        return 0


# =========================================================
# CONFERMA / PUBBLICAZIONE
# =========================================================

async def conferma(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query

    await query.answer()

    # PROGRAMMA INVIO
    if query.data == "programma":

        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📅 OGGI",
                        callback_data="prog_giorno_0",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📅 DOMANI",
                        callback_data="prog_giorno_1",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📅 TRA 2 GIORNI",
                        callback_data="prog_giorno_2",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ ANNULLA",
                        callback_data="annulla",
                    )
                ],
            ]
        )

        await query.message.reply_text(
            "📅 PROGRAMMA INVIO\n\n"
            "Scegli il giorno:",
            reply_markup=tastiera,
        )

        return CONFERMA

    # GIORNO SCELTO
    if query.data.startswith("prog_giorno_"):

        try:

            giorni = int(
                query.data.replace(
                    "prog_giorno_",
                    "",
                )
            )

        except ValueError:

            return CONFERMA

        data_scelta = (
            datetime.now(ROMA_TZ).date()
            + timedelta(days=giorni)
        )

        context.user_data[
            "data_programmata"
        ] = data_scelta.isoformat()

        etichetta = (
            "oggi"
            if giorni == 0
            else "domani"
            if giorni == 1
            else "tra 2 giorni"
        )

        eventi = programmazioni_del_giorno(
            data_scelta
        )

        if eventi:

            orari_occupati = ", ".join(
                evento["datetime"].strftime(
                    "%H:%M"
                )
                for evento in eventi
            )

        else:

            orari_occupati = "nessuno"

        suggerito = suggerisci_prossimo_slot(
            data_scelta
        )

        if suggerito:

            suggerimento_testo = (
                "💡 Prossimo spazio consigliato: "
                f"{suggerito.strftime('%H:%M')}\n\n"
            )

        else:

            suggerimento_testo = (
                "⚠️ Non trovo altri spazi "
                "consigliati oggi.\n\n"
            )

        await query.message.reply_text(
            f"🕒 Hai scelto {etichetta}.\n\n"
            f"📅 Orari già programmati: "
            f"{orari_occupati}\n\n"
            f"{suggerimento_testo}"
            "Ora scrivi solo l'orario."
        )

        return PROGRAMMA_ORA

    # ANNULLA
    if query.data == "annulla":
        return await annulla(update, context)

    # CAMBIA TEMPLATE
    if query.data == "cambia_template":

        tastiera = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✨ PULITO",
                        callback_data="tpl_pulito",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🚨 AGGRESSIVO",
                        callback_data="tpl_aggressivo",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⚡ TECH",
                        callback_data="tpl_tech",
                    )
                ],
            ]
        )

        await query.message.reply_text(
            "🎨 Scegli il template:",
            reply_markup=tastiera,
        )

        return CONFERMA

    # TEMPLATE SELEZIONATO
    if query.data.startswith("tpl_"):

        template = query.data.replace(
            "tpl_",
            "",
        )

        context.user_data["template"] = template

        await query.edit_message_text(
            f"✅ Template selezionato: {template}"
        )

        return await mostra_anteprima(
            update,
            context,
        )

    # PUBBLICA
    if query.data == "pubblica":

        minuti_rimanenti = minuti_rimanenti_prima_del_prossimo_invio()

        if minuti_rimanenti > 0:
            await query.message.reply_text(
                f"⏳ È ancora presto. Attendi ancora {minuti_rimanenti} minuto/i.\n\n"
                f"Tra un post e l'altro devono passare almeno "
                f"{DISTANZA_MINIMA_MINUTI} minuti."
            )
            return CONFERMA

        messaggio = context.user_data.get("messaggio")
        link = context.user_data.get("link")
        nome = context.user_data.get("nome")

        if not messaggio or not link:

            await query.edit_message_text(
                "❌ Dati dell'offerta mancanti."
            )

            return ConversationHandler.END

        messaggio_con_link = crea_caption_con_link(messaggio, link)

        bottone_offerta = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🎁 CLUB",
                        url="https://t.me/BestPrice24h_bot",
                    ),
                    InlineKeyboardButton(
                        "🛒 APRI",
                        url=link,
                    )
                ]
            ]
        )

        foto_file_id = context.user_data.get(
            "foto_file_id"
        )

        if foto_file_id:
            messaggio_telegram = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=foto_file_id,
                caption=messaggio_con_link,
                parse_mode="HTML",
                reply_markup=bottone_offerta,
            )
        else:
            messaggio_telegram = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=messaggio_con_link,
                parse_mode="HTML",
                reply_markup=bottone_offerta,
            )

        foto_monitoraggio = foto_file_id
        if getattr(messaggio_telegram, "photo", None):
            foto_monitoraggio = messaggio_telegram.photo[-1].file_id
        sconto_manuale = calcola_sconto(
            context.user_data.get("prezzo"),
            context.user_data.get("vecchio_prezzo", "NO"),
        ) or 0
        registra_pubblicazione_monitorata(
            nome=nome,
            link=link,
            message_id=messaggio_telegram.message_id,
            foto_file_id=foto_monitoraggio,
            sconto=sconto_manuale,
            soglia_sconto=sconto_manuale,
            asin=context.user_data.get("asin"),
        )

        ultime_offerte.appendleft(
            {
                "nome": nome,
                "link": link,
                "prezzo": context.user_data.get("prezzo"),
            }
        )

        salva_offerta_recap(
            nome,
            link,
            context.user_data.get("prezzo"),
            context.user_data.get("vecchio_prezzo", "NO"),
            messaggio=messaggio,
            foto_file_id=foto_file_id,
            template=context.user_data.get("template", "pulito"),
            asin=context.user_data.get("asin") or risolvi_asin_da_link(link),
            telegram_chat_id=CHANNEL_ID,
            origine="manuale",
            sconto=sconto_manuale,
            telegram_message_id=messaggio_telegram.message_id,
        )

        context.user_data.clear()

        chat_id = query.message.chat_id

        await query.message.delete()

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ OFFERTA PUBBLICATA!\n\n"
                "Cosa vuoi fare adesso?"
            ),
            reply_markup=menu_dopo_pubblicazione(),
        )

        return ConversationHandler.END

    return CONFERMA


# =========================================================
# ULTIME OFFERTE
# =========================================================

ARCHIVIO_PER_PAGINA = 10


def _condizioni_archivio(filtro="tutti", ricerca=""):
    condizioni, parametri = [], []
    if filtro == "tech":
        condizioni.append("telegram_chat_id = ?")
        parametri.append(str(CHANNEL_ID))
    elif filtro == "casa":
        condizioni.append("telegram_chat_id = ?")
        parametri.append(str(CASA_CHANNEL_ID))
    elif filtro == "manuale":
        condizioni.append("origine <> 'automatico'")
    elif filtro in {"automatico", "programmato", "reinvio", "ricerca"}:
        condizioni.append("origine = ?")
        parametri.append(filtro)
    if ricerca:
        condizioni.append("nome LIKE ? COLLATE NOCASE")
        parametri.append(f"%{ricerca}%")
    return (" WHERE " + " AND ".join(condizioni)) if condizioni else "", parametri


def conta_archivio(filtro="tutti", ricerca=""):
    where, parametri = _condizioni_archivio(filtro, ricerca)
    db = sqlite3.connect(DB_PATH)
    totale = db.execute(f"SELECT COUNT(*) FROM recap_offerte{where}", parametri).fetchone()[0]
    db.close()
    return totale


def leggi_archivio(pagina=0, filtro="tutti", ricerca=""):
    where, parametri = _condizioni_archivio(filtro, ricerca)
    db = sqlite3.connect(DB_PATH)
    righe = db.execute(
        f"""
        SELECT r.id, r.nome, r.link, r.prezzo, r.pubblicata_il,
               COALESCE(r.categoria, 'manuale'), COALESCE(r.telegram_chat_id, ''),
               COALESCE(r.origine, 'manuale'), COALESCE(r.sconto, 0),
               COALESCE((SELECT i.stato FROM invii_automatici i
                         WHERE i.asin = r.asin ORDER BY i.id DESC LIMIT 1), r.stato, 'pubblicata')
        FROM recap_offerte r{where}
        ORDER BY r.pubblicata_il DESC, r.id DESC LIMIT ? OFFSET ?
        """,
        (*parametri, ARCHIVIO_PER_PAGINA, pagina * ARCHIVIO_PER_PAGINA),
    ).fetchall()
    db.close()
    return righe


def _data_archivio(valore):
    try:
        data = datetime.fromisoformat(valore)
        if data.tzinfo is None:
            data = data.replace(tzinfo=ROMA_TZ)
        return data.astimezone(ROMA_TZ).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return "data non disponibile"


async def mostra_archivio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    azione = query.data
    if azione == "archive_all":
        context.user_data["archivio_filtro"] = "tutti"
        context.user_data.pop("archivio_ricerca", None)
        pagina = 0
    elif azione.startswith("archive_filter_"):
        context.user_data["archivio_filtro"] = azione.replace("archive_filter_", "", 1)
        pagina = 0
    else:
        try:
            pagina = int(azione.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            pagina = 0
    filtro = context.user_data.get("archivio_filtro", "tutti")
    ricerca = context.user_data.get("archivio_ricerca", "")
    totale = conta_archivio(filtro, ricerca)
    totale_pagine = max(1, (totale + ARCHIVIO_PER_PAGINA - 1) // ARCHIVIO_PER_PAGINA)
    pagina = max(0, min(pagina, totale_pagine - 1))
    context.user_data["archivio_pagina"] = pagina
    righe = leggi_archivio(pagina, filtro, ricerca)
    testo = [f"🗂 ARCHIVIO PRODOTTI — {totale} TOTALI"]
    if ricerca:
        testo.append(f"Ricerca: {ricerca}")
    tastiera = []
    for offerta_id, nome, _, prezzo, data, _, chat_id, origine, sconto, stato in righe:
        canale = "CASA" if str(chat_id) == str(CASA_CHANNEL_ID) else "TECH"
        icona = "⛔" if stato == "terminata" else "✅"
        breve = accorcia_nome_articolo(nome)
        if len(breve) > 58:
            breve = breve[:55].rsplit(" ", 1)[0] + "…"
        testo.append(
            f"\n#{offerta_id} {icona} {breve}\n"
            f"-{int(sconto or 0)}% · {prezzo} · {canale} · {origine} · {_data_archivio(data)}"
        )
        tastiera.append([InlineKeyboardButton(
            f"#{offerta_id} · {breve[:34]}", callback_data=f"archive_view_{offerta_id}"
        )])
    if not righe:
        testo.append("\nNessun prodotto corrisponde ai filtri.")
    nav = []
    if pagina > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"archive_page_{pagina - 1}"))
    nav.append(InlineKeyboardButton(f"📄 {pagina + 1}/{totale_pagine}", callback_data="archive_nop"))
    if pagina < totale_pagine - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"archive_page_{pagina + 1}"))
    tastiera.append(nav)
    tastiera.extend([
        [InlineKeyboardButton("📱 TECH", callback_data="archive_filter_tech"),
         InlineKeyboardButton("🏠 CASA", callback_data="archive_filter_casa")],
        [InlineKeyboardButton("🤖 AUTOMATICI", callback_data="archive_filter_automatico"),
         InlineKeyboardButton("✍️ MANUALI", callback_data="archive_filter_manuale")],
        [InlineKeyboardButton("🔎 CERCA PER NOME", callback_data="archive_search")],
        [InlineKeyboardButton("🗂 MOSTRA TUTTI", callback_data="archive_all")],
        [InlineKeyboardButton("⬅️ TORNA ALLO STORICO", callback_data="history_menu")],
    ])
    await query.edit_message_text(
        "\n".join(testo)[:4000], reply_markup=InlineKeyboardMarkup(tastiera)
    )


async def mostra_scheda_archivio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    offerta_id = int(query.data.rsplit("_", 1)[1])
    riga = leggi_offerta_da_reinviare(offerta_id)
    if not riga:
        return await query.message.reply_text("❌ Prodotto non trovato.")
    _, nome, link, prezzo, vecchio, data, *_ = riga
    pagina = context.user_data.get("archivio_pagina", 0)
    await query.edit_message_text(
        f"📦 {html.escape(nome)}\n\n"
        f"Prezzo: {html.escape(str(prezzo))}\n"
        f"Prima: {html.escape(str(vecchio))}\n"
        f"Pubblicato: {_data_archivio(data)}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 APRI SU AMAZON", url=link)],
            [InlineKeyboardButton("🔁 INVIA DI NUOVO", callback_data=f"reinvia_scegli_{offerta_id}_{offerta_id}")],
            [InlineKeyboardButton("⬅️ TORNA ALL'ARCHIVIO", callback_data=f"archive_page_{pagina}")],
        ]),
    )


async def richiedi_ricerca_archivio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔎 Scrivi una parte del nome del prodotto.\n\nPer annullare scrivi /annulla"
    )
    return ARCHIVIO_RICERCA


async def ricevi_ricerca_archivio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    ricerca = re.sub(r"\s+", " ", update.message.text.strip())[:80]
    if len(ricerca) < 2:
        await update.message.reply_text("❌ Scrivi almeno 2 caratteri.")
        return ARCHIVIO_RICERCA
    context.user_data["archivio_ricerca"] = ricerca
    context.user_data["archivio_filtro"] = "tutti"
    await update.message.reply_text(
        f"✅ Ricerca impostata: {ricerca}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🗂 MOSTRA RISULTATI", callback_data="archive_page_0")
        ]]),
    )
    return ConversationHandler.END

async def ultime(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return

    offerte = leggi_archivio(0, "tutti", "")[:10]
    if not offerte:
        testo = "📋 Nessuna offerta ancora registrata."
    else:
        righe = ["🕒 ULTIME PUBBLICAZIONI\n"]
        for numero, (_, nome, _, prezzo, data, _, chat_id, origine, sconto, stato) in enumerate(offerte, 1):
            canale = "CASA" if str(chat_id) == str(CASA_CHANNEL_ID) else "TECH"
            icona = "⛔" if stato == "terminata" else "✅"
            righe.append(
                f"{numero}. {icona} {accorcia_nome_articolo(nome)}\n"
                f"-{int(sconto or 0)}% · {prezzo} · {canale} · {origine} · {_data_archivio(data)}"
            )
        testo = "\n\n".join(righe)

    if update.message:

        await update.message.reply_text(
            testo
        )

    else:

        await update.callback_query.answer()

        await update.callback_query.message.reply_text(
            testo
        )


# =========================================================
# INVIA DI NUOVO - STORICO ULTIMI 3 GIORNI
# =========================================================

REINVIO_PER_PAGINA = 6


def leggi_offerte_da_reinviare():

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    limite = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat(timespec="seconds")

    cur.execute("""
        SELECT id, nome, link, prezzo,
               COALESCE(vecchio_prezzo, 'NO'),
               pubblicata_il, messaggio, foto_file_id,
               COALESCE(template, 'pulito')
        FROM recap_offerte
        WHERE pubblicata_il >= ?
        ORDER BY pubblicata_il DESC
    """, (limite,))

    righe = cur.fetchall()
    db.close()
    return righe


def leggi_offerta_da_reinviare(offerta_id):

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT id, nome, link, prezzo,
               COALESCE(vecchio_prezzo, 'NO'),
               pubblicata_il, messaggio, foto_file_id,
               COALESCE(template, 'pulito')
        FROM recap_offerte
        WHERE id = ?
    """, (offerta_id,))

    riga = cur.fetchone()
    db.close()
    return riga


async def mostra_reinvio_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query
    await query.answer()

    pagina = 0
    if query.data.startswith("reinvia_pagina_"):
        try:
            pagina = int(query.data.rsplit("_", 1)[1])
        except ValueError:
            pagina = 0

    offerte = leggi_offerte_da_reinviare()

    if not offerte:
        await query.message.reply_text(
            "📭 Non ci sono offerte pubblicate negli ultimi 3 giorni.",
            reply_markup=menu_principale(),
        )
        return

    totale_pagine = max(
        1,
        (len(offerte) + REINVIO_PER_PAGINA - 1) // REINVIO_PER_PAGINA,
    )
    pagina = max(0, min(pagina, totale_pagine - 1))

    inizio = pagina * REINVIO_PER_PAGINA
    offerte_pagina = offerte[inizio:inizio + REINVIO_PER_PAGINA]

    righe = []
    tastiera = []
    pulsanti_numerici = []

    for posizione, offerta in enumerate(offerte_pagina, start=1):
        numero = inizio + posizione
        offerta_id, nome, _, prezzo, _, pubblicata_il, *_ = offerta

        try:
            data = datetime.fromisoformat(pubblicata_il)
            if data.tzinfo is None:
                data = data.replace(tzinfo=timezone.utc)
            data = data.astimezone(ROMA_TZ)
            data_testo = data.strftime("%d/%m %H:%M")
        except Exception:
            data_testo = ""

        nome_breve = accorcia_nome_articolo(nome)

        righe.append(
            f"#{numero}  {nome_breve}\n"
            f"💰 {prezzo} € · 🕒 {data_testo}"
        )

        pulsanti_numerici.append(
            InlineKeyboardButton(
                f"#{numero}",
                callback_data=f"reinvia_scegli_{offerta_id}_{numero}",
            )
        )

    for i in range(0, len(pulsanti_numerici), 3):
        tastiera.append(pulsanti_numerici[i:i + 3])

    nav = []
    if pagina > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️",
                callback_data=f"reinvia_pagina_{pagina - 1}",
            )
        )

    nav.append(
        InlineKeyboardButton(
            f"📄 {pagina + 1}/{totale_pagine}",
            callback_data="reinvia_nop",
        )
    )

    if pagina < totale_pagine - 1:
        nav.append(
            InlineKeyboardButton(
                "➡️",
                callback_data=f"reinvia_pagina_{pagina + 1}",
            )
        )

    tastiera.append(nav)
    tastiera.append([
        InlineKeyboardButton("⬅️ TORNA AL MENU", callback_data="menu_admin")
    ])

    await query.message.reply_text(
        "🔁 INVIA DI NUOVO\n\n"
        "📅 Ultimi 3 giorni · 6 articoli per pagina\n\n"
        + "\n\n".join(righe)
        + "\n\n👇 Scegli il numero dell'articolo.",
        reply_markup=InlineKeyboardMarkup(tastiera),
    )


async def reinvia_nop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def _dati_reinvio(context):
    draft = context.user_data.get("reinvia_draft")
    if draft:
        return draft

    offerta_id = context.user_data.get("reinvia_offerta_id")
    riga = leggi_offerta_da_reinviare(offerta_id)
    if not riga:
        return None

    _, nome, link, prezzo, vecchio_prezzo, _, messaggio_salvato, foto_file_id, template = riga
    draft = {
        "nome": nome,
        "link": link,
        "prezzo": prezzo,
        "vecchio_prezzo": vecchio_prezzo,
        "messaggio_salvato": messaggio_salvato,
        "foto_file_id": foto_file_id,
        "template": template or "pulito",
        "modificato": False,
    }
    context.user_data["reinvia_draft"] = draft
    return draft


def _messaggio_reinvio(draft):
    if not draft:
        return ""
    if not draft.get("modificato") and draft.get("messaggio_salvato"):
        return rimuovi_link_finale_da_messaggio(draft["messaggio_salvato"])
    return crea_messaggio_programmato(
        draft.get("nome", ""),
        draft.get("prezzo", ""),
        draft.get("vecchio_prezzo", "NO"),
        draft.get("template", "pulito"),
    )


async def mostra_anteprima_reinvio(messaggio, context):
    draft = await _dati_reinvio(context)
    if not draft:
        await messaggio.reply_text("❌ Offerta non trovata.")
        return

    numero = context.user_data.get("reinvia_numero", "")
    testo_post = _messaggio_reinvio(draft)
    anteprima = (
        f"🔁 ANTEPRIMA ARTICOLO #{numero}\n\n"
        + crea_caption_con_link(
            testo_post,
            draft["link"],
            messaggio_gia_html=draft.get("template") == "automatico",
        )
    )

    tastiera = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 RIPUBBLICA ORA", callback_data="reinvia_ora"),
            InlineKeyboardButton("🕒 PROGRAMMA", callback_data="reinvia_programma"),
        ],
        [
            InlineKeyboardButton("✏️ MODIFICA", callback_data="reinvia_modifica"),
        ],
        [
            InlineKeyboardButton("⬅️ TORNA ALLO STORICO", callback_data="reinvia_pagina_0"),
        ],
    ])

    if draft.get("foto_file_id"):
        await messaggio.reply_photo(
            photo=draft["foto_file_id"],
            caption=anteprima,
            parse_mode="HTML",
            reply_markup=tastiera,
        )
    else:
        await messaggio.reply_text(
            anteprima,
            parse_mode="HTML",
            reply_markup=tastiera,
        )


async def scegli_offerta_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query
    await query.answer()

    try:
        _, _, offerta_id, numero = query.data.split("_")
        offerta_id = int(offerta_id)
        numero = int(numero)
    except Exception:
        return

    context.user_data["reinvia_offerta_id"] = offerta_id
    context.user_data["reinvia_numero"] = numero
    context.user_data.pop("reinvia_draft", None)
    context.user_data.pop("reinvia_edit_state", None)

    if not leggi_offerta_da_reinviare(offerta_id):
        await query.message.reply_text("❌ Offerta non trovata.")
        return

    await mostra_anteprima_reinvio(query.message, context)


async def menu_modifica_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "✏️ COSA VUOI MODIFICARE?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📦 NOME", callback_data="reinvia_edit_nome"),
                InlineKeyboardButton("💰 PREZZO", callback_data="reinvia_edit_prezzo"),
            ],
            [
                InlineKeyboardButton("🏷 PREZZO PRIMA", callback_data="reinvia_edit_vecchio"),
                InlineKeyboardButton("🔗 LINK", callback_data="reinvia_edit_link"),
            ],
            [InlineKeyboardButton("🖼 IMMAGINE", callback_data="reinvia_edit_immagine")],
            [InlineKeyboardButton("🎨 TEMPLATE", callback_data="reinvia_edit_template")],
            [InlineKeyboardButton("⬅️ TORNA ALL'ANTEPRIMA", callback_data="reinvia_anteprima")],
        ]),
    )


async def gestisci_modifica_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    draft = await _dati_reinvio(context)
    if not draft:
        return

    if data == "reinvia_anteprima":
        context.user_data.pop("reinvia_edit_state", None)
        await mostra_anteprima_reinvio(query.message, context)
        return

    if data == "reinvia_edit_nome":
        context.user_data["reinvia_edit_state"] = "nome"
        await query.message.reply_text("📦 Scrivi il nuovo nome del prodotto:")
        return

    if data == "reinvia_edit_prezzo":
        context.user_data["reinvia_edit_state"] = "prezzo"
        await query.message.reply_text("💰 Scrivi il nuovo prezzo attuale:")
        return

    if data == "reinvia_edit_vecchio":
        context.user_data["reinvia_edit_state"] = "vecchio"
        await query.message.reply_text("🏷 Scrivi il nuovo prezzo precedente oppure NO:")
        return

    if data == "reinvia_edit_link":
        context.user_data["reinvia_edit_state"] = "link"
        await query.message.reply_text("🔗 Inviami il nuovo link Amazon:")
        return

    if data == "reinvia_edit_immagine":
        if draft.get("foto_file_id"):
            kb = [
                [InlineKeyboardButton("🔄 SOSTITUISCI IMMAGINE", callback_data="reinvia_img_sostituisci")],
                [InlineKeyboardButton("🗑 RIMUOVI IMMAGINE", callback_data="reinvia_img_rimuovi")],
                [InlineKeyboardButton("⬅️ INDIETRO", callback_data="reinvia_modifica")],
            ]
        else:
            kb = [
                [InlineKeyboardButton("📷 AGGIUNGI IMMAGINE", callback_data="reinvia_img_aggiungi")],
                [InlineKeyboardButton("⬅️ INDIETRO", callback_data="reinvia_modifica")],
            ]
        await query.message.reply_text("🖼 GESTIONE IMMAGINE", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data in ("reinvia_img_aggiungi", "reinvia_img_sostituisci"):
        context.user_data["reinvia_attesa_foto"] = True
        await query.message.reply_text("📷 Inviami la nuova immagine.")
        return

    if data == "reinvia_img_rimuovi":
        draft["foto_file_id"] = None
        draft["modificato"] = True
        await query.message.reply_text("✅ Immagine rimossa.")
        await mostra_anteprima_reinvio(query.message, context)
        return

    if data == "reinvia_edit_template":
        await query.message.reply_text(
            "🎨 Scegli il nuovo template:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ PULITO", callback_data="reinvia_tpl_pulito")],
                [InlineKeyboardButton("🚨 AGGRESSIVO", callback_data="reinvia_tpl_aggressivo")],
                [InlineKeyboardButton("⚡ TECH", callback_data="reinvia_tpl_tech")],
            ]),
        )
        return

    if data.startswith("reinvia_tpl_"):
        draft["template"] = data.replace("reinvia_tpl_", "")
        draft["modificato"] = True
        await query.message.reply_text("✅ Template aggiornato.")
        await mostra_anteprima_reinvio(query.message, context)


async def ricevi_modifica_testo_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stato = context.user_data.get("reinvia_edit_state")
    if not stato:
        return

    if not await controlla_autorizzazione(update):
        return

    draft = await _dati_reinvio(context)
    if not draft:
        return

    valore = update.message.text.strip()
    if stato == "nome":
        if not valore:
            await update.message.reply_text("❌ Il nome non può essere vuoto.")
            return
        draft["nome"] = valore
    elif stato == "prezzo":
        draft["prezzo"] = pulisci_prezzo(valore)
    elif stato == "vecchio":
        draft["vecchio_prezzo"] = "NO" if valore.upper() == "NO" else pulisci_prezzo(valore)
    elif stato == "link":
        if "amazon." not in valore and "amzn." not in valore:
            await update.message.reply_text("❌ Mandami un link Amazon valido.")
            return
        draft["link"] = valore

    draft["modificato"] = True
    context.user_data.pop("reinvia_edit_state", None)
    await update.message.reply_text("✅ Modifica salvata.")
    await mostra_anteprima_reinvio(update.message, context)


async def ricevi_foto_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("reinvia_attesa_foto"):
        return
    if not await controlla_autorizzazione(update):
        return

    draft = await _dati_reinvio(context)
    if not draft:
        return

    draft["foto_file_id"] = update.message.photo[-1].file_id
    draft["modificato"] = True
    context.user_data.pop("reinvia_attesa_foto", None)
    await update.message.reply_text("✅ Immagine aggiornata.")
    await mostra_anteprima_reinvio(update.message, context)


async def reinvia_offerta_storica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query
    await query.answer()

    minuti_rimanenti = minuti_rimanenti_prima_del_prossimo_invio()
    if minuti_rimanenti > 0:
        await query.message.reply_text(
            f"⏳ Attendi ancora {minuti_rimanenti} minuto/i.\n\n"
            f"Tra un post e l'altro devono passare almeno {DISTANZA_MINIMA_MINUTI} minuti."
        )
        return

    draft = await _dati_reinvio(context)
    if not draft:
        await query.message.reply_text("❌ Offerta non trovata.")
        return

    messaggio = _messaggio_reinvio(draft)
    messaggio_con_link = crea_caption_con_link(
        messaggio,
        draft["link"],
        messaggio_gia_html=draft.get("template") == "automatico",
    )
    bottoni = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 CLUB", url="https://t.me/BestPrice24h_bot"),
        InlineKeyboardButton("🛒 APRI", url=draft["link"]),
    ]])

    if draft.get("foto_file_id"):
        messaggio_telegram = await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=draft["foto_file_id"],
            caption=messaggio_con_link,
            parse_mode="HTML",
            reply_markup=bottoni,
        )
    else:
        messaggio_telegram = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=messaggio_con_link,
            parse_mode="HTML",
            reply_markup=bottoni,
        )

    foto_monitoraggio = draft.get("foto_file_id")
    if getattr(messaggio_telegram, "photo", None):
        foto_monitoraggio = messaggio_telegram.photo[-1].file_id
    sconto_reinvio = calcola_sconto(
        draft.get("prezzo"),
        draft.get("vecchio_prezzo", "NO"),
    ) or 0
    registra_pubblicazione_monitorata(
        nome=draft["nome"],
        link=draft["link"],
        message_id=messaggio_telegram.message_id,
        foto_file_id=foto_monitoraggio,
        sconto=sconto_reinvio,
        soglia_sconto=sconto_reinvio,
    )

    salva_offerta_recap(
        draft["nome"], draft["link"], draft["prezzo"], draft.get("vecchio_prezzo", "NO"),
        messaggio=messaggio,
        foto_file_id=draft.get("foto_file_id"),
        template=draft.get("template", "pulito"),
        asin=risolvi_asin_da_link(draft["link"]),
        telegram_chat_id=CHANNEL_ID,
        origine="reinvio",
        sconto=sconto_reinvio,
        telegram_message_id=messaggio_telegram.message_id,
    )

    numero = context.user_data.get("reinvia_numero")
    for chiave in ("reinvia_offerta_id", "reinvia_numero", "reinvia_draft", "reinvia_edit_state", "reinvia_attesa_foto"):
        context.user_data.pop(chiave, None)

    await query.message.reply_text(
        f"✅ OFFERTA #{numero} INVIATA DI NUOVO!",
        reply_markup=menu_dopo_pubblicazione(),
    )


async def prepara_programmazione_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collega INVIA DI NUOVO allo stesso flusso calendario dei post normali."""
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    draft = await _dati_reinvio(context)
    if not draft:
        await query.message.reply_text("❌ Dati dell'offerta mancanti. Riprova.")
        return ConversationHandler.END

    # Copia il draft nei campi standard usati dalla programmazione normale.
    context.user_data["nome"] = draft["nome"]
    context.user_data["link"] = draft["link"]
    context.user_data["prezzo"] = draft["prezzo"]
    context.user_data["vecchio_prezzo"] = draft.get("vecchio_prezzo", "NO")
    context.user_data["template"] = draft.get("template", "pulito")
    context.user_data["foto_file_id"] = draft.get("foto_file_id")
    context.user_data["messaggio"] = _messaggio_reinvio(draft)
    context.user_data["programmazione_da_reinvio"] = True

    tastiera = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 OGGI", callback_data="prog_giorno_0")],
            [InlineKeyboardButton("📅 DOMANI", callback_data="prog_giorno_1")],
            [InlineKeyboardButton("📅 TRA 2 GIORNI", callback_data="prog_giorno_2")],
            [InlineKeyboardButton("❌ ANNULLA", callback_data="annulla")],
        ]
    )

    await query.message.reply_text(
        "📅 PROGRAMMA INVIO\n\n"
        "Stai usando lo stesso calendario dei POST PROGRAMMATI.\n"
        "Scegli il giorno:",
        reply_markup=tastiera,
    )

    # Da qui prosegue esattamente negli stati standard CONFERMA -> PROGRAMMA_ORA.
    return CONFERMA


async def scegli_giorno_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    giorni = int(query.data.rsplit("_", 1)[1])
    data = datetime.now(ROMA_TZ).date() + timedelta(days=giorni)
    context.user_data["reinvia_data"] = data.isoformat()
    context.user_data["attesa_ora_reinvio"] = True
    await query.message.reply_text(
        f"📅 {data.strftime('%d/%m/%Y')}\n\n🕒 Scrivi l'orario nel formato HH:MM."
    )


async def ricevi_ora_reinvio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Prima gestisce eventuali modifiche testuali dell'offerta storica.
    if context.user_data.get("reinvia_edit_state"):
        await ricevi_modifica_testo_reinvio(update, context)
        return

    if not context.user_data.get("attesa_ora_reinvio"):
        return

    # Se è stato selezionato un post programmato, questo handler non deve
    # mai interpretare il testo come orario.
    if context.user_data.get("prog_id"):
        return

    if not await controlla_autorizzazione(update):
        return

    try:
        ora = datetime.strptime(update.message.text.strip(), "%H:%M").time()
    except ValueError:
        await update.message.reply_text("❌ Orario non corretto. Scrivilo nel formato HH:MM.")
        return

    data_iso = context.user_data.get("reinvia_data")
    draft = await _dati_reinvio(context)
    if not draft or not data_iso:
        await update.message.reply_text("❌ Dati mancanti. Riprova.")
        return

    data = datetime.fromisoformat(data_iso).date()
    data_locale = datetime.combine(data, ora, tzinfo=ROMA_TZ)

    if data_locale <= datetime.now(ROMA_TZ):
        await update.message.reply_text("❌ Questo orario è già passato. Inserisci un orario futuro.")
        return

    conflitti = trova_conflitto(data_locale)
    if conflitti:
        vicino = conflitti[0]
        await update.message.reply_text(
            "⚠️ POST TROPPO VICINO\n\n"
            f"Hai già un'offerta alle {vicino['datetime'].strftime('%H:%M')}.\n"
            f"Scegli un orario distante almeno {DISTANZA_MINIMA_MINUTI} minuti."
        )
        return

    messaggio = _messaggio_reinvio(draft)
    programmazione_id, invio_previsto = salva_programmazione(
        draft["nome"], messaggio, draft["link"], draft["prezzo"], data_locale
    )
    salva_foto_programmazione(programmazione_id, draft.get("foto_file_id"))

    numero = context.user_data.get("reinvia_numero")
    for chiave in ("reinvia_offerta_id", "reinvia_numero", "reinvia_draft", "reinvia_data", "attesa_ora_reinvio", "reinvia_edit_state", "reinvia_attesa_foto"):
        context.user_data.pop(chiave, None)

    await update.message.reply_text(
        f"✅ OFFERTA #{numero} PROGRAMMATA!\n\n"
        f"📅 {invio_previsto.strftime('%d/%m/%Y')}\n"
        f"🕒 {invio_previsto.strftime('%H:%M')}\n"
        f"📦 {draft['nome']}\n"
        f"💰 {draft['prezzo']} €\n\n"
        f"🆔 Programmazione: #{programmazione_id}",
        reply_markup=menu_principale(),
    )


# =========================================================
# TEMPLATE DAL MENU ADMIN
# =========================================================

async def template_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query

    await query.answer()

    tastiera = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✨ PULITO",
                    callback_data="menu_tpl_pulito",
                )
            ],
            [
                InlineKeyboardButton(
                    "🚨 AGGRESSIVO",
                    callback_data="menu_tpl_aggressivo",
                )
            ],
            [
                InlineKeyboardButton(
                    "⚡ TECH",
                    callback_data="menu_tpl_tech",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ TORNA ALLE IMPOSTAZIONI",
                    callback_data="settings_menu",
                )
            ],
        ]
    )

    await query.message.reply_text(
        "🎨 Scegli il template predefinito:",
        reply_markup=tastiera,
    )


async def scegli_template_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return

    query = update.callback_query

    await query.answer()

    template = query.data.replace(
        "menu_tpl_",
        "",
    )

    context.user_data["template"] = template

    await query.edit_message_text(
        f"✅ Template impostato: {template.upper()}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ TORNA ALLE IMPOSTAZIONI", callback_data="settings_menu")
        ]]),
    )


# =========================================================
# ANNULLA
# =========================================================

async def annulla(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await controlla_autorizzazione(update):
        return ConversationHandler.END

    context.user_data.clear()

    # Funziona sia con /annulla sia con il pulsante inline ANNULLA.
    if update.callback_query:
        query = update.callback_query

        try:
            await query.edit_message_text(
                "❌ Operazione annullata.",
                reply_markup=menu_principale(),
            )
        except Exception:
            await query.message.reply_text(
                "❌ Operazione annullata.",
                reply_markup=menu_principale(),
            )

    elif update.message:
        await update.message.reply_text(
            "❌ Operazione annullata.",
            reply_markup=menu_principale(),
        )

    return ConversationHandler.END


# =========================================================
# AVVIO BOT
# =========================================================

def main():

    inizializza_database()
    inizializza_programmazioni()
    inizializza_recap()
    inizializza_automazione()
    inizializza_tiktok()
    avvia_api_offerte_web()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .post_init(avvia_programmazioni)
        .build()
    )

    conversazione = ConversationHandler(

        entry_points=[

            CommandHandler(
                "nuova",
                nuova_da_comando,
            ),

            CommandHandler(
                "rapido",
                rapido_da_comando,
            ),

            CallbackQueryHandler(
                nuova_da_pulsante,
                pattern="^nuova$",
            ),

            CallbackQueryHandler(
                rapido_da_pulsante,
                pattern="^rapido$",
            ),

            CallbackQueryHandler(
                prepara_programmazione_reinvio,
                pattern="^reinvia_programma$",
            ),

            CallbackQueryHandler(
                prepara_programmazione_ricerca_offerte,
                pattern=r"^os_program_[0-9]+$",
            ),
        ],

        states={

            LINK: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_link,
                )
            ],

            DATI_AUTOMATICI: [
                CallbackQueryHandler(
                    conferma_dati_automatici,
                    pattern="^(dati_ok|dati_manual)$",
                )
            ],

            PROGRAMMA_ORA: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_ora_programmazione,
                )
            ],

            CONFERMA_ORARIO: [
                CallbackQueryHandler(
                    conferma_orario_vicino,
                    pattern=(
                        "^(conferma_orario_vicino|"
                        "cambia_orario)$"
                    ),
                )
            ],

            NOME: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_nome,
                )
            ],

            PREZZO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_prezzo,
                )
            ],

            VECCHIO_PREZZO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_vecchio_prezzo,
                )
            ],

            RAPIDO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ricevi_rapido,
                )
            ],

            FOTO_SCELTA: [
                CallbackQueryHandler(
                    scelta_immagine,
                    pattern="^(foto_aggiungi|foto_salta)$",
                )
            ],

            FOTO_ATTESA: [
                MessageHandler(
                    filters.PHOTO,
                    ricevi_immagine,
                )
            ],

            CONFERMA: [
                CallbackQueryHandler(
                    conferma,
                    pattern=(
                        "^(pubblica|"
                        "programma|"
                        "prog_giorno_0|"
                        "prog_giorno_1|"
                        "prog_giorno_2|"
                        "annulla|"
                        "cambia_template|"
                        "tpl_pulito|"
                        "tpl_aggressivo|"
                        "tpl_tech)$"
                    ),
                )
            ],
        },

        fallbacks=[
            CommandHandler(
                "annulla",
                annulla,
            )
        ],

        allow_reentry=True,
    )


    # =====================================================
    # COMANDI GENERALI
    # =====================================================

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "id",
            mio_id,
        )
    )

    app.add_handler(
        CommandHandler(
            "tiktok_test",
            testa_tiktok,
        )
    )


    # =====================================================
    # ADMIN OFFERTE
    # =====================================================

    app.add_handler(
        CommandHandler(
            "ultime",
            ultime,
        )
    )

    app.add_handler(
        conversazione
    )

    configurazione_automatica = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                richiedi_intervallo_automatico,
                pattern="^auto_intervallo$",
            ),
            CallbackQueryHandler(
                richiedi_fascia_automatica,
                pattern="^auto_fascia$",
            ),
        ],
        states={
            AUTO_INTERVALLO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_intervallo_automatico,
                )
            ],
            AUTO_FASCIA: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ricevi_fascia_automatica,
                )
            ],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
        allow_reentry=True,
    )

    app.add_handler(configurazione_automatica)

    configurazione_filtri = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                _imposta_stato_filtro(FILTRO_MARCHIO_AGGIUNGI),
                pattern="^filter_brand_add$",
            ),
            CallbackQueryHandler(
                _imposta_stato_filtro(FILTRO_MARCHIO_RIMUOVI),
                pattern="^filter_brand_remove$",
            ),
            CallbackQueryHandler(
                _imposta_stato_filtro(FILTRO_PAROLA_AGGIUNGI),
                pattern="^filter_word_add$",
            ),
            CallbackQueryHandler(
                _imposta_stato_filtro(FILTRO_PAROLA_RIMUOVI),
                pattern="^filter_word_remove$",
            ),
        ],
        states={
            FILTRO_MARCHIO_AGGIUNGI: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_modifica_filtro)],
            FILTRO_MARCHIO_RIMUOVI: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_modifica_filtro)],
            FILTRO_PAROLA_AGGIUNGI: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_modifica_filtro)],
            FILTRO_PAROLA_RIMUOVI: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_modifica_filtro)],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
        allow_reentry=True,
    )
    app.add_handler(configurazione_filtri)

    configurazione_priorita = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(richiedi_modifica_priorita, pattern="^priority_add$"),
            CallbackQueryHandler(richiedi_modifica_priorita, pattern="^priority_remove$"),
            CallbackQueryHandler(richiedi_modifica_priorita, pattern="^priority_access_add$"),
            CallbackQueryHandler(richiedi_modifica_priorita, pattern="^priority_access_remove$"),
        ],
        states={
            PRIORITA_AGGIUNGI: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_modifica_priorita)],
            PRIORITA_RIMUOVI: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_modifica_priorita)],
            PRIORITA_ACCESSORIO_AGGIUNGI: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_modifica_priorita)],
            PRIORITA_ACCESSORIO_RIMUOVI: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_modifica_priorita)],
        },
        fallbacks=[CommandHandler("annulla", annulla)],
        allow_reentry=True,
    )
    app.add_handler(configurazione_priorita)

    ricerca_archivio = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(richiedi_ricerca_archivio, pattern="^archive_search$")
        ],
        states={
            ARCHIVIO_RICERCA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_ricerca_archivio)
            ]
        },
        fallbacks=[CommandHandler("annulla", annulla)],
        allow_reentry=True,
    )
    app.add_handler(ricerca_archivio)

    app.add_handler(CallbackQueryHandler(gestisci_tiktok, pattern=r"^tiktok_(menu|toggle|test|history|times|times_(1130_1930|1230_2030|1300_2100)|discount|discount_(10|20|30|40))$"))

    # Nuovi menu principali raggruppati.
    app.add_handler(
        CallbackQueryHandler(mostra_menu_pubblicazione, pattern="^publish_menu$")
    )
    app.add_handler(
        CallbackQueryHandler(mostra_menu_storico, pattern="^history_menu$")
    )
    app.add_handler(
        CallbackQueryHandler(mostra_menu_impostazioni, pattern="^settings_menu$")
    )
    app.add_handler(
        CallbackQueryHandler(mostra_gestione_canali, pattern="^channels_manage$")
    )
    app.add_handler(
        CallbackQueryHandler(
            mostra_info_canale,
            pattern=r"^channel_info_(tech|casa)$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(mostra_stato_bot, pattern="^bot_status$")
    )
    app.add_handler(
        CallbackQueryHandler(mostra_canali_automazione, pattern="^auto_channels$")
    )
    app.add_handler(
        CallbackQueryHandler(
            seleziona_canale_automazione,
            pattern=r"^auto_channel_(tech|casa)$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(mostra_stato_automazioni, pattern="^auto_status$")
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_ricerca_offerte,
            pattern=(
                r"^(offer_search|offer_search_(tech|casa)|os_disc_(10|20|30|40|50)|os_cat_[a-z]+|"
                r"os_count_(5|10|20)|os_view_[0-9]+|os_publish_[0-9]+|os_back)$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            menu_automazione,
            pattern="^auto_menu$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_selettiva,
            pattern=(
                r"^(selective_menu|selective_score|selective_score_[3-8]|"
                r"selective_bonus|selective_bonus_(20|25|30|35|40)|selective_amazon|"
                r"selective_searches|selective_searches_(3|6|9)|selective_variants|"
                r"selective_reset|selective_reset_yes)$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_priorita,
            pattern=(
                r"^(priority_menu|priority_categories|priority_cat_[a-z]+|"
                r"priority_accessories|priority_reset|priority_reset_yes)$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_filtri,
            pattern=(
                r"^(auto_filtri|filter_brands|filter_brandcat_[a-z]+|filter_words|"
                r"filter_score|filter_score_[3-8]|filter_bonus|filter_bonus_(20|25|30|35|40)|"
                r"filter_amazon|filter_summary|filter_reset|filter_reset_yes)$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_automazione,
            pattern=(
                r"^(auto_toggle|auto_sconto|auto_disc_[0-9]+|"
                r"auto_duplicates|auto_duplicates_(1|3|7|10|14|30)|"
                r"auto_categorie|auto_cat_[a-z]+|auto_qualita|"
                r"auto_quality_(standard|selettiva|marche))$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_raccolte_casa,
            pattern=(
                r"^(casa_collections|casa_bundle_toggle|casa_bundle_frequency|"
                r"casa_bundle_frequency_(2|4|6|8)|casa_bundle_quantity|"
                r"casa_bundle_quantity_(2|4|6)|casa_bundle_price|"
                r"casa_bundle_price_(15|25|40|60)|casa_bundle_discount|"
                r"casa_bundle_discount_(5|10|15|20)|casa_bundle_quality|"
                r"casa_bundle_quality_(standard|selettiva)|casa_bundle_themes|"
                r"casa_bundle_theme_[a-z]+|casa_bundle_test)$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_raccolte_tech,
            pattern=(
                r"^(tech_collections|tech_bundle_toggle|tech_bundle_frequency|"
                r"tech_bundle_frequency_(2|4|6|8)|tech_bundle_quantity|"
                r"tech_bundle_quantity_(2|4|6)|tech_bundle_price|"
                r"tech_bundle_price_(40|75|150|300)|tech_bundle_discount|"
                r"tech_bundle_discount_(5|10|15|20)|tech_bundle_quality|"
                r"tech_bundle_quality_(standard|selettiva)|tech_bundle_themes|"
                r"tech_bundle_theme_[a-z]+|tech_bundle_test)$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            testa_ricerca_automatica,
            pattern="^auto_test$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            ultime,
            pattern="^ultime$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            mostra_archivio,
            pattern=r"^(archive_all|archive_page_[0-9]+|archive_filter_(tech|casa|automatico|manuale))$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(mostra_scheda_archivio, pattern=r"^archive_view_[0-9]+$")
    )

    app.add_handler(CallbackQueryHandler(reinvia_nop, pattern="^archive_nop$"))

    app.add_handler(
        CallbackQueryHandler(
            mostra_reinvio_menu,
            pattern=r"^(reinvia_menu|reinvia_pagina_[0-9]+)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            reinvia_nop,
            pattern="^reinvia_nop$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            scegli_offerta_reinvio,
            pattern=r"^reinvia_scegli_[0-9]+_[0-9]+$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            reinvia_offerta_storica,
            pattern="^reinvia_ora$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            menu_modifica_reinvio,
            pattern="^reinvia_modifica$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_modifica_reinvio,
            pattern=(
                r"^(reinvia_anteprima|reinvia_edit_nome|reinvia_edit_prezzo|"
                r"reinvia_edit_vecchio|reinvia_edit_link|reinvia_edit_immagine|"
                r"reinvia_img_aggiungi|reinvia_img_sostituisci|reinvia_img_rimuovi|"
                r"reinvia_edit_template|reinvia_tpl_pulito|reinvia_tpl_aggressivo|reinvia_tpl_tech)$"
            ),
        )
    )


    gestione_programmati = ConversationHandler(

        entry_points=[
            CallbackQueryHandler(
                mostra_programmati,
                pattern="^programmati$",
            )
        ],

        states={

            PROG_SELEZIONE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    seleziona_programmato,
                ),
                CallbackQueryHandler(
                    esci_programmati,
                    pattern="^prog_esci$",
                ),
            ],

            PROG_GESTIONE: [
                CallbackQueryHandler(
                    gestisci_programmato,
                    pattern=(
                        "^(prog_modifica|"
                        "prog_elimina|"
                        "prog_elimina_si|"
                        "prog_elimina_no|"
                        "prog_indietro)$"
                    ),
                ),
            ],

            PROG_MODIFICA_MENU: [
                CallbackQueryHandler(
                    menu_modifica_programmato,
                    pattern=(
                        "^(prog_edit_nome|prog_edit_immagine|"
                        "prog_edit_prezzo|"
                        "prog_edit_vecchio|"
                        "prog_edit_link|"
                        "prog_edit_dataora|"
                        "prog_edit_template|"
                        "prog_tpl_pulito|"
                        "prog_tpl_aggressivo|"
                        "prog_tpl_tech|"
                        "prog_torna_scheda)$"
                    ),
                ),
            ],

            PROG_EDIT_NOME: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_nome,
                )
            ],

            PROG_EDIT_PREZZO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_prezzo,
                )
            ],

            PROG_EDIT_VECCHIO: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_vecchio,
                )
            ],

            PROG_EDIT_LINK: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_link,
                )
            ],

            PROG_EDIT_DATA_ORA: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_programmato_dataora,
                )
            ],

            PROG_IMMAGINE_MENU: [
                CallbackQueryHandler(
                    gestisci_immagine_programmata,
                    pattern=(
                        "^(prog_img_aggiungi|"
                        "prog_img_sostituisci|"
                        "prog_img_rimuovi|"
                        "prog_img_indietro)$"
                    ),
                )
            ],

            PROG_IMMAGINE_ATTESA: [
                MessageHandler(
                    filters.PHOTO,
                    ricevi_immagine_programmata,
                )
            ],

        },

        fallbacks=[
            CommandHandler(
                "annulla",
                annulla,
            )
        ],

        allow_reentry=True,
    )

    app.add_handler(
        gestione_programmati
    )

    # Deve stare dopo gestione_programmati: altrimenti intercetta
    # il numero digitato per modificare un post programmato.
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            ricevi_ora_reinvio,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            ricevi_foto_reinvio,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            template_menu,
            pattern="^template$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            scegli_template_menu,
            pattern="^menu_tpl_",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            torna_menu_admin,
            pattern="^menu_admin$",
        )
    )


    app.add_handler(
        CallbackQueryHandler(
            torna_menu_utente,
            pattern="^menu_utente$",
        )
    )


    # =====================================================
    # CLUB UTENTI
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            mostra_punti,
            pattern="^club_punti$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            invita_amici,
            pattern="^club_invita$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            mostra_premi,
            pattern="^club_premi$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            club_home,
            pattern="^club_home$",
        )
    )


    # =====================================================
    # PREMI
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            richiedi_premio,
            pattern="^premio_(5|10)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            gestisci_premio_admin,
            pattern=(
                "^(approva|rifiuta)"
                "_premio_[0-9]+$"
            ),
        )
    )


    # =====================================================
    # PANNELLO ADMIN CLUB
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            admin_club_menu,
            pattern="^admin_club$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_club_utenti,
            pattern="^adm_utenti$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_club_utente,
            pattern=r"^adm_user_[0-9]+$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_modifica_punti,
            pattern=r"^adm_pts_[0-9]+_(1|5|m1|m5)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_storico_utente,
            pattern=r"^adm_storico_[0-9]+$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_movimenti,
            pattern="^adm_movimenti$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_inviti,
            pattern="^adm_inviti$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_premi,
            pattern="^adm_premi$",
        )
    )


    print(
        "🤖 Amazon Offer Bot + Club V2 avviato"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
