import monitoraggio
from interfaccia_legacy import navigazione_coordinatore
import os
import asyncio
import sqlite3
import html
import json
import csv
import re
import random
import threading
import hmac
import hashlib
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO, StringIO
import sys
import logging
import traceback
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
from collections import deque
from urllib.parse import urlparse, parse_qs, urlencode

import requests
import filtri_canale
from link_amazon import link_amazon_valido
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

# Accesso Creators API temporaneamente disabilitato: nessuna chiamata remota.
# La ricerca automatica basata esclusivamente sull'API non puo' trovare nuovi candidati
# finche' non viene implementata una fonte alternativa autorizzata.
def get_items(*args, **kwargs):
    return []

def search_items(*args, **kwargs):
    return []

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)

from pulsanti import InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    TypeHandler,
    ApplicationHandlerStop,
)


# =========================================================
# LOG DIAGNOSTICI: cattura stdout/stderr e logging Python
# Solo gli eventi da questo avvio del processo; nessun accesso API Railway.
# =========================================================
_LOG_BUFFER = deque(maxlen=3000)
_LOG_LOCK = threading.RLock()
_LOG_STARTED = datetime.now(timezone.utc)


def _redact_log_line(line):
    line = str(line)
    secrets = [os.environ.get(k, "") for k in (
        "TELEGRAM_BOT_TOKEN", "AMAZON_ACCESS_KEY", "AMAZON_SECRET_KEY",
        "CREATORS_API_SECRET", "BUFFER_ACCESS_TOKEN", "RAILWAY_API_TOKEN",
    )]
    for secret in secrets:
        if secret and len(secret) >= 5:
            line = line.replace(secret, "[RISERVATO]")
    line = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+", r"\1[RISERVATO]", line)
    line = re.sub(r"(?i)((?:token|secret|password|api[_-]?key)\s*[:=]\s*)[^\s,;]+", r"\1[RISERVATO]", line)
    line = re.sub(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b", "[TOKEN_TELEGRAM_RISERVATO]", line)
    return line[:3000]


def _save_log_line(line, stream):
    if not line.strip():
        return
    stamp = datetime.now(ROMA_TZ).strftime("%d/%m %H:%M:%S")
    with _LOG_LOCK:
        _LOG_BUFFER.append((stamp, stream, _redact_log_line(line)))


class _LogTee:
    def __init__(self, original, label):
        self.original = original
        self.label = label
        self.pending = ""
        self.lock = threading.RLock()

    def write(self, text):
        with self.lock:
            self.original.write(text)
            self.pending += str(text)
            while "\n" in self.pending:
                line, self.pending = self.pending.split("\n", 1)
                _save_log_line(line, self.label)
        return len(text)

    def flush(self):
        with self.lock:
            if self.pending:
                _save_log_line(self.pending, self.label)
                self.pending = ""
            self.original.flush()

    def isatty(self):
        return self.original.isatty()

    def __getattr__(self, name):
        return getattr(self.original, name)


class _MemoryLogHandler(logging.Handler):
    def emit(self, record):
        try:
            _save_log_line(self.format(record), "PYTHON")
        except Exception:
            pass


def _install_log_capture():
    if not isinstance(sys.stdout, _LogTee):
        sys.stdout = _LogTee(sys.stdout, "STDOUT")
    if not isinstance(sys.stderr, _LogTee):
        sys.stderr = _LogTee(sys.stderr, "STDERR")
    root = logging.getLogger()
    if not any(isinstance(h, _MemoryLogHandler) for h in root.handlers):
        handler = _MemoryLogHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)


_install_log_capture()

# =========================================================
# CONFIGURAZIONE
# =========================================================

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHAT_ID"]
CASA_CHANNEL_ID = os.environ.get("TELEGRAM_CHAT_ID_CASA", "@BestPrice24hCasa")
CASA_CHANNEL_URL = "https://t.me/BestPrice24hCasa"
TECH_CHANNEL_URL = "https://t.me/bestprice_2026"
COMMUNITY_URL = os.environ.get("COMMUNITY_URL", "").strip()
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
        "prezzo_finale_pubblicato": "TEXT",
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

    dati_template=dati_template_da_corpo(messaggio)
    if dati_template:
        _,_,finale,_,sconto_finale=importi_template(dati_template)
        if finale is not None:
            cur.execute('UPDATE recap_offerte SET prezzo_finale_pubblicato=?,sconto=? WHERE id=?',(str(finale).replace('.',','),sconto_finale or 0,cur.lastrowid))

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


def hashtag_categoria_post(categoria):
    valore = str(categoria or '').strip()
    if valore.lower() in AUTO_HASHTAG:
        return AUTO_HASHTAG[valore.lower()]
    if not valore or valore.lower() in {'manuale', 'tutte'}:
        return '#OfferteAmazon'
    pulita = re.sub(r'[^\w]', '', valore.lstrip('#'), flags=re.UNICODE)[:60]
    return '#' + pulita if pulita else '#OfferteAmazon'


def corpo_pulito_post(nome, prezzo, vecchio='NO', categoria=None, coupon=None):
    prezzo = pulisci_prezzo(prezzo)
    precedente = pulisci_prezzo(vecchio) if vecchio and str(vecchio).upper() != 'NO' else 'NO'
    sconto = calcola_sconto(prezzo, precedente) if precedente != 'NO' else None
    righe = ['🔥 OFFERTA AMAZON', '', '🛒 ' + str(nome), '']
    if sconto is not None and sconto > 0:
        righe.append(f'💥 Sconto: -{sconto}%')
    if precedente != 'NO':
        righe.append(f'❌ Prima: {precedente} €')
    righe += [f'✅ Ora: {prezzo} €']
    if frase_coupon(coupon):
        righe += ['', frase_coupon(coupon)]
    righe += ['', 'Categoria: ' + hashtag_categoria_post(categoria)]
    return '\n'.join(righe)


def html_corpo_pulito(messaggio):
    # Escapa sempre il contenuto del prodotto prima di applicare i tag Telegram.
    righe = []
    for riga in str(messaggio).splitlines():
        if riga == '🔥 OFFERTA AMAZON':
            righe.append('<b>🔥 OFFERTA AMAZON</b>')
        elif riga.startswith('💥 Sconto: '):
            righe.append('💥 Sconto: <b>' + html.escape(riga[len('💥 Sconto: '):]) + '</b>')
        elif riga.startswith('❌ Prima: '):
            righe.append('❌ Prima: <s>' + html.escape(riga[len('❌ Prima: '):]) + '</s>')
        elif riga.startswith('✅ Applica il coupon '):
            righe.append('✅ <i>' + html.escape(riga[2:]) + '</i>')
        elif riga.startswith('✅ Ora: '):
            righe.append('✅ Ora: <b>' + html.escape(riga[len('✅ Ora: '):]) + '</b>')
        else:
            righe.append(html.escape(riga))
    return '\n'.join(righe)


def dati_template_da_corpo(messaggio, nome=None, prezzo=None, vecchio=None, categoria=None):
    """Adatta i vecchi corpi senza cambiare i prezzi base conservati nel database."""
    originale=str(messaggio or '').replace('__RICERCA_HTML__','',1)
    testo=BeautifulSoup(originale,'html.parser').get_text() if originale.lstrip().startswith('<') else originale
    righe=[r.strip() for r in testo.splitlines() if r.strip()]
    titoli=('🔥 OFFERTA AMAZON','🚨 SUPER OFFERTA AMAZON','⚡ TECH DEAL','🚨 ERRORE PREZZO',
            '🏷 OFFERTA AMAZON','🔥 SUPER OFFERTA AMAZON','🚨 SCONTO EXTRA AMAZON','🎟 OFFERTA CON COUPON')
    if not nome and (not righe or not righe[0].startswith(titoli)):
        return None
    if not nome:
        nome=re.sub(r'^[🛒📦📱🔥]\s*','',righe[1]) if len(righe)>1 else ''
    ora=re.search(r'(?:✅|💰)?\s*(?:ora(?P<coupon> con coupon)?|offerta)\s*:\s*([^\n]+)',testo,re.IGNORECASE)
    prima=re.search(r'(?:prima|listino)\s*:\s*([^\n]+)',testo,re.IGNORECASE)
    cat=re.search(r'Categoria:\s*(#[\w]+)',testo,re.IGNORECASE)
    coupon=re.search(r'Applica il coupon (?:del|da) (\d+(?:[.,]\d{1,2})?(?:%| €)) visibile',testo,re.IGNORECASE)
    return {'nome':str(nome or ''), 'prezzo':prezzo if prezzo is not None else ora.group(2).strip() if ora else None,
            'vecchio_prezzo':vecchio if vecchio is not None else prima.group(1).strip() if prima else None,
            'categoria':categoria if categoria and categoria != 'manuale' else cat.group(1) if cat else None,
            'coupon':coupon.group(1) if coupon else None, 'gia_finale':bool(ora and ora.group('coupon')), 'solo_coupon':bool(righe and righe[0].startswith('🎟'))}


def importi_template(dati):
    base_num=numero_da_prezzo(dati.get('prezzo'))
    prima_num=numero_da_prezzo(dati.get('vecchio_prezzo'))
    base=Decimal(str(base_num)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP) if base_num is not None else None
    prima=Decimal(str(prima_num)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP) if prima_num is not None else None
    finale=base
    coupon=dati.get('coupon')
    valido=False
    if base is not None and base >= 0 and coupon and frase_coupon(coupon):
        valore=Decimal(coupon.replace('€','').replace('%','').replace(',','.').strip())
        if coupon.endswith('%') and 0 < valore <= 100:
            finale=base if dati.get('gia_finale') else (base*(Decimal('1')-valore/Decimal('100'))).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
            valido=True
        elif coupon.endswith(' €') and valore>0 and (dati.get('gia_finale') or valore<=base):
            finale=base if dati.get('gia_finale') else base-valore
            valido=True
    sconto=None
    if prima is not None and prima>0 and finale is not None and prima>finale:
        sconto=int(((Decimal('1')-finale/prima)*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    return base,prima,finale,coupon if valido else None,sconto


def euro_template(valore):
    return f'{valore:.2f}'.replace('.',',')+' €'


def render_template_generale(dati):
    base,prima,finale,coupon,sconto=importi_template(dati)
    coupon_solo=bool(coupon and (dati.get('solo_coupon') or ((prima is None or prima<=base) and not dati.get('gia_finale'))))
    titolo=('🎟 OFFERTA CON COUPON' if coupon_solo else '🚨 SCONTO EXTRA AMAZON' if (sconto or 0)>=70
            else '🔥 SUPER OFFERTA AMAZON' if (sconto or 0)>=30 else '🏷 OFFERTA AMAZON')
    nome=' '.join(str(dati['nome']).split())
    if len(nome)>300:
        nome=nome[:297].rsplit(' ',1)[0]+'…'
    righe=['<b>'+titolo+'</b>','', '🛒 '+html.escape(nome), '']
    if sconto is not None and sconto>0:
        etichetta='Sconto totale con coupon' if coupon else 'Sconto'
        righe.append(f'💥 {etichetta}: <b>-{sconto}%</b>')
    if prima is not None and finale is not None and prima>finale:
        righe.append('❌ Prima: <s>'+euro_template(prima)+'</s>')
    if finale is not None:
        righe.append(('✅ Ora con coupon: ' if coupon else '✅ Ora: ')+'<b>'+euro_template(finale)+'</b>')
    else:
        righe.append('✅ Prezzo: non disponibile')
    if coupon:
        righe += ['', '✅ <i>'+html.escape(frase_coupon(coupon)[2:])+'</i>']
    righe += ['', 'Categoria: '+html.escape(hashtag_categoria_post(dati.get('categoria')))]
    return '\n'.join(righe)


# =========================================================
# TIPOLOGIA AMAZON: NUOVO / SECONDA MANO / RENEWED
# Modalita' prudente: se la tipologia non e' verificabile, salta.
# =========================================================

def riconosci_tipologia_amazon(link, dati=None):
    """Non deduce la condizione dall'ASIN o dal solo prezzo.

    La pagina e la Creator API possono riferirsi a offerte differenti:
    un link con offerListingID richiede una verifica dell'offerta specifica.
    """
    from urllib.parse import urlsplit, parse_qs
    dati = dati or {}
    titolo = str(dati.get('nome') or '').lower()
    link = str(link or '')
    parametri = parse_qs(urlsplit(link).query)
    condizioni = [str(v).strip().lower() for v in (dati.get('condizione'), dati.get('condition'), dati.get('item_condition')) if v]
    condizione = ' '.join(condizioni)
    # Un'offerta specifica non e' verificabile tramite i soli dati dell'ASIN.
    offerta_specifica = any(k.lower() in {'offeringid','offeringid.1','offerlistingid','smid','aod'} for k in parametri)
    if offerta_specifica and not dati.get('offerta_specifica_verificata'):
        return 'sconosciuto'
    if re.search(r'\b(?:amazon renewed|renewed|ricondizionato)\b', titolo) or re.search(r'\b(?:renewed|refurbished|ricondizionato)\b', condizione):
        return 'renewed'
    if re.search(r'\b(?:used|usato|seconda mano|warehouse)\b', condizione):
        return 'seconda_mano' if dati.get('prezzo_offerta_verificato') else 'sconosciuto'
    if re.search(r'\b(?:new|nuovo)\b', condizione):
        return 'nuovo'
    return 'sconosciuto'


def prezzi_offerta_validi(dati):
    """Fallback neutro soltanto con due prezzi numerici, coerenti e positivi."""
    if not isinstance(dati, dict):
        return False
    try:
        attuale = numero_da_prezzo(str(dati.get('prezzo') or dati.get('prezzo_valore') or ''))
        prima = numero_da_prezzo(str(dati.get('vecchio_prezzo') or dati.get('vecchio_valore') or ''))
        return bool(attuale and prima and 0 < attuale < prima)
    except (TypeError, ValueError, AttributeError):
        return False


def tipo_o_fallback(link, dati):
    """Un prezzo valido basta per leggere un articolo ordinario.

    'standard_neutro' NON certifica la condizione 'nuovo'. Per offerte
    specifiche e articoli usati restano obbligatorie verifiche dedicate.
    """
    from urllib.parse import urlsplit, parse_qs
    tipo = riconosci_tipologia_amazon(link, dati)
    if tipo != 'sconosciuto':
        return tipo
    if not isinstance(dati, dict):
        return tipo
    params = parse_qs(urlsplit(str(link or '')).query)
    if any(k.lower() in {'offeringid', 'offeringid.1', 'offerlistingid', 'smid', 'aod'} for k in params):
        return tipo
    condizione = ' '.join(str(dati.get(k) or '') for k in ('condizione', 'condition', 'item_condition')).lower()
    if re.search(r'\b(?:used|usato|seconda mano|warehouse|refurbished|ricondizionato)\b', condizione + ' ' + str(dati.get('nome') or '').lower()):
        return tipo
    if dati.get('disponibile') is False:
        return tipo
    prezzo = numero_da_prezzo(str(dati.get('prezzo') or dati.get('prezzo_valore') or ''))
    if dati.get('nome') and prezzo is not None and prezzo > 0:
        return 'standard_neutro'
    return tipo


def _diagnostica_lettura(dati, richiedi_immagine=False):
    if not isinstance(dati, dict) or not dati:
        return 'Amazon non ha restituito dati del prodotto'
    if dati.get('disponibile') is False:
        return 'prodotto non disponibile'
    if not dati.get('nome'):
        return 'nome prodotto non rilevato'
    prezzo = numero_da_prezzo(str(dati.get('prezzo') or dati.get('prezzo_valore') or ''))
    if prezzo is None or prezzo <= 0:
        return 'prezzo attuale non rilevato'
    if tipo_o_fallback(dati.get('_link_originale'), dati) == 'sconosciuto':
        return 'condizione o offerta specifica non verificabile'
    if richiedi_immagine and not dati.get('immagine'):
        return 'immagine non disponibile'
    return None


def _unisci_dati_lettura(base, nuovo):
    """Integra SOLO metadati. Prezzi/coupon/disponibilita' restano della singola fonte verificata."""
    risultato = dict(nuovo)
    for chiave in ('nome', 'immagine', 'categoria', 'asin'):
        if not risultato.get(chiave) and base.get(chiave):
            risultato[chiave] = base[chiave]
    return risultato


async def leggi_offerta_con_sei_tentativi(link, richiedi_immagine=False, callback=None):
    """Lettura diretta della pagina Amazon: non interroga Creators API.

    Tre tentativi massimi, senza mescolare dati economici di letture diverse.
    """
    asin = await asyncio.to_thread(risolvi_asin_da_link, link)
    if not asin:
        print('Lettura Amazon: ASIN non rilevato dal link (anche dopo redirect).')
        return None
    url_canonico = f'https://www.amazon.it/dp/{asin}'
    lettori = (('pagina Amazon', leggi_prodotto_amazon),) * 3
    metadati = {}
    motivi = []
    for indice, (fonte, lettore) in enumerate(lettori, 1):
        try:
            # La pagina originale puo' includere parametri di offerta specifica.
            url_lettura = url_canonico if fonte == 'pagina Amazon' and not re.search(
                r'[?&](?:offeringid|offerlistingid|smid|aod)=', str(link), re.I) else link
            risultato = await asyncio.to_thread(lettore, url_lettura)
            if risultato and risultato.get('disponibile') is False:
                print(f'Lettura Amazon ASIN {asin}: prodotto non disponibile ({fonte}).')
                motivo = 'disponibilita non confermata'
                motivi.append(f'{fonte}: {motivo}')
                if callback:
                    await callback(indice)
                if indice < 3:
                    await asyncio.sleep(3)
                continue
            if isinstance(risultato, dict) and risultato:
                dati = _unisci_dati_lettura(metadati, risultato)
                dati['_link_originale'] = link
                motivo = _diagnostica_lettura(dati, richiedi_immagine)
                if not motivo:
                    dati.pop('_link_originale', None)
                    dati['tipologia_amazon'] = tipo_o_fallback(link, dati)
                    dati['_lettura_offerta_completata'] = True
                    print(f'Lettura Amazon ASIN {asin}: completata al tentativo {indice} ({fonte}).')
                    return dati
                # Metadati sicuri possono essere riutilizzati, non i dati economici.
                for campo in ('nome', 'immagine', 'categoria', 'asin'):
                    if dati.get(campo):
                        metadati[campo] = dati[campo]
            else:
                motivo = 'nessuna risposta utilizzabile'
            motivi.append(f'{fonte}: {motivo}')
            print(f'Lettura Amazon ASIN {asin} tentativo {indice}/3 ({fonte}): {motivo}')
        except Exception as errore:
            motivi.append(f'{fonte}: {type(errore).__name__}')
            print(f'Lettura Amazon ASIN {asin} tentativo {indice}/3 ({fonte}): {type(errore).__name__}: {errore}')
        if callback:
            await callback(indice)
        if indice < 3:
            await asyncio.sleep(3)
    print(f'Lettura Amazon ASIN {asin}: fallita. Motivi: {"; ".join(motivi)}')
    return None


def dati_automatici_sufficienti(prodotto):
    """Non ripete chiamate quando search_items ha gia' restituito dati validi."""
    if not isinstance(prodotto, dict):
        return False
    try:
        prezzo = float(prodotto.get('prezzo_valore') or 0)
    except (ValueError, TypeError):
        return False
    return bool(prodotto.get('nome') and prodotto.get('immagine')
                and prodotto.get('link') and prezzo > 0
                and tipo_o_fallback(prodotto.get('link'), prodotto) != 'sconosciuto')


async def completa_candidato_automatico(prodotto):
    """Si usa in ricerca, non nella spedizione del post programmato."""
    if dati_automatici_sufficienti(prodotto):
        prodotto['tipologia_amazon'] = tipo_o_fallback(prodotto.get('link'), prodotto)
        prodotto['_lettura_offerta_completata'] = True
        return prodotto
    recuperato = await leggi_offerta_con_sei_tentativi(
        prodotto.get('link'), richiedi_immagine=True
    )
    if not recuperato:
        return None
    unito = dict(prodotto)
    unito.update({k: v for k, v in recuperato.items() if v is not None})
    if not dati_automatici_sufficienti(unito):
        return None
    unito['tipologia_amazon'] = tipo_o_fallback(unito.get('link'), unito)
    unito['_lettura_offerta_completata'] = True
    return unito


def render_template_condizione(dati):
    tipo = dati.get('tipologia_amazon')
    if tipo not in {'seconda_mano', 'renewed'}:
        return render_template_generale(dati)
    base, prima, finale, coupon, sconto = importi_template(dati)
    nome = html.escape(' '.join(str(dati.get('nome') or '').split())[:300])
    titolo = '♻️ AMAZON SECONDA MANO' if tipo == 'seconda_mano' else '🔄 AMAZON RENEWED'
    etichetta = 'Prezzo seconda mano' if tipo == 'seconda_mano' else 'Prezzo ricondizionato'
    righe = [f'<b>{titolo}</b>', '', '🛒 '+nome, '']
    condizione = str(dati.get('condizione') or '').strip()
    if condizione:
        righe.append('📦 Condizione: '+html.escape(condizione[:100]))
    if prima is not None and finale is not None and prima > finale and dati.get('prezzo_nuovo_verificato'):
        righe.append('❌ Prezzo nuovo: <s>'+euro_template(prima)+'</s>')
        righe.append(f'💰 Risparmio rispetto al nuovo: <b>{sconto}%</b>')
    righe.append('✅ '+etichetta+': <b>'+(euro_template(finale) if finale is not None else 'non disponibile')+'</b>')
    righe.extend(['', 'Categoria: '+html.escape(hashtag_categoria_post(dati.get('categoria')))])
    return '\n'.join(righe)


def crea_caption_con_link(messaggio, link, messaggio_gia_html=False):
    """Crea una didascalia uniforme senza mostrare l'URL completo."""
    dati=dati_template_da_corpo(messaggio)
    if dati is not None:
        corpo=render_template_condizione(dati)
    elif messaggio_gia_html:
        corpo=messaggio
    else:
        corpo=html.escape(str(messaggio or ''))
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

    messaggio=BeautifulSoup(str(messaggio),'html.parser').get_text() if str(messaggio).lstrip().startswith('<') else messaggio

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
    match = re.search(r"(?:sconto(?: totale con coupon)?\s*:?[ ]*|📉\s*)-?(\d{1,3})%", testo, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def offerte_recap_di_oggi(telegram_chat_id):
    """Recupera i post del canale con categoria e sconto per la TOP 5."""
    oggi = datetime.now(ROMA_TZ).date().isoformat()
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        righe = db.execute("""
            SELECT id, nome, link, prezzo, vecchio_prezzo, pubblicata_il,
                   asin, categoria, sconto, prezzo_finale_pubblicato, messaggio
            FROM recap_offerte
            WHERE substr(pubblicata_il, 1, 10) = ?
              AND telegram_chat_id = ?
              AND COALESCE(stato, 'pubblicata') = 'pubblicata'
            ORDER BY pubblicata_il DESC, id DESC
        """, (oggi, str(telegram_chat_id))).fetchall()
    return [dict(riga) for riga in righe]


def seleziona_top_recap(offerte, limite=5):
    """Prima il miglior sconto per categoria, poi completa per sconto."""
    def percentuale(offerta):
        try:
            valore = int(offerta.get('sconto') or 0)
        except (TypeError, ValueError):
            valore = 0
        if valore <= 0:
            valore = estrai_sconto_da_messaggio(offerta.get('messaggio'))
        return max(0, min(100, valore))

    uniche = {}
    for offerta in offerte:
        chiave = (str(offerta.get('asin') or '').strip().upper()
                  or str(offerta.get('link') or '').split('?', 1)[0].rstrip('/').lower())
        if not chiave:
            chiave = f"riga:{offerta['id']}"
        if chiave not in uniche or percentuale(offerta) > percentuale(uniche[chiave]):
            uniche[chiave] = offerta
    ordinate = sorted(uniche.values(), key=lambda r: (percentuale(r), r['id']), reverse=True)
    scelte, categorie = [], set()
    for offerta in ordinate:
        categoria = str(offerta.get('categoria') or 'altro').strip().lower()
        if categoria not in categorie:
            scelte.append(offerta)
            categorie.add(categoria)
            if len(scelte) == limite:
                return scelte
    selezionati = {r['id'] for r in scelte}
    for offerta in ordinate:
        if len(scelte) == limite:
            break
        if offerta['id'] not in selezionati:
            scelte.append(offerta)
    return scelte


def link_oroscopo_recap(giorno, canale, telegram_chat_id):
    """Secondo oroscopo se pubblicato, altrimenti il primo disponibile."""
    with sqlite3.connect(DB_PATH) as db:
        try:
            riga = db.execute("""
                SELECT message_id FROM oroscopo_uscite
                WHERE giorno=? AND canale=? AND stato='inviato'
                  AND message_id IS NOT NULL
                ORDER BY slot DESC LIMIT 1
            """, (giorno, str(telegram_chat_id))).fetchone()
        except sqlite3.OperationalError:
            return None
    if not riga:
        return None
    base = TECH_CHANNEL_URL if canale == 'tech' else CASA_CHANNEL_URL
    return f"{base.rstrip('/')}/{int(riga[0])}"



def link_quiz_recap(giorno, telegram_chat_id):
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        row = db.execute("SELECT message_id FROM quiz_uscite_canali WHERE giorno=? AND canale=? AND stato='inviato' AND message_id IS NOT NULL", (giorno,str(telegram_chat_id))).fetchone()
    return link_post_telegram(chat_id=telegram_chat_id,message_id=row[0]) if row else None


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
    medaglie = ('🥇', '🥈', '🥉', '4️⃣', '5️⃣')
    righe = []
    for indice, offerta in enumerate(offerte):
        nome_html = html.escape(str(accorcia_nome_articolo(offerta['nome'])))
        link_html = html.escape(str(offerta['link']), quote=True)
        prezzo = offerta.get('prezzo_finale_pubblicato') or offerta.get('prezzo') or '—'
        prezzo = str(prezzo).strip()
        if prezzo != '—' and '€' not in prezzo:
            prezzo += ' €'
        vecchio = str(offerta.get('vecchio_prezzo') or '—').strip()
        if vecchio.upper() == 'NO':
            vecchio = '—'
        elif vecchio != '—' and '€' not in vecchio:
            vecchio += ' €'
        try:
            sconto = int(offerta.get('sconto') or 0)
        except (ValueError, TypeError):
            sconto = 0
        if sconto <= 0:
            sconto = estrai_sconto_da_messaggio(offerta.get('messaggio'))
        etichetta = f' — Sconto {sconto}%' if sconto > 0 else ''
        righe.append(
            f'{medaglie[indice] if indice < len(medaglie) else str(indice + 1) + "."} '
            f'<b>{nome_html}{etichetta}</b>\n'
            f'❌ Prima: <s>{html.escape(vecchio)}</s>\n'
            f'✅ Ora: <b>{html.escape(prezzo)}</b>\n'
            f'🔗 <a href="{link_html}">Vedi offerta</a>'
        )
    return righe


async def invia_recap_giornaliero(bot, canale, telegram_chat_id):
    offerte = offerte_recap_di_oggi(telegram_chat_id)
    if not offerte:
        return False
    top = seleziona_top_recap(offerte, limite=5)
    righe = crea_righe_recap(top)
    oggi = datetime.now(ROMA_TZ).date().isoformat()
    testo = (
        f'🌙 <b>BESTPRICE24H {canale.upper()} | IL MEGLIO DI OGGI</b>\n\n'
        f'📦 <b>{len(offerte)} offerte pubblicate oggi!</b>\n\n'
        f'🏆 <b>LE {len(top)} MIGLIORI OFFERTE</b>\n\n'
        + '\n\n'.join(righe)
        + '\n\n☕ <b>HAI GIÀ LETTO IL TUO OROSCOPO DI OGGI?</b>\n'
          '✨ Scopri cosa ti riservano le stelle!\n\n'
          ''
    )
    url_oroscopo = link_oroscopo_recap(oggi, canale, telegram_chat_id)
    url_quiz = link_quiz_recap(oggi, telegram_chat_id) if canale == 'tech' else None
    pulsanti = []
    if url_oroscopo:
        pulsanti.append([InlineKeyboardButton('🔮 Scopri il tuo oroscopo', url=url_oroscopo)])
    if url_quiz:
        pulsanti.append([InlineKeyboardButton('🧠 Partecipa al quiz di oggi', url=url_quiz)])
        testo += ('\n🧠 <b>NON HAI ANCORA FATTO IL QUIZ DI OGGI?</b>\n'
                  '🎯 Mettiti alla prova: puoi ancora partecipare!\n')
    tastiera = InlineKeyboardMarkup(pulsanti) if pulsanti else None
    if not url_oroscopo:
        testo = testo.replace(
            '☕ <b>HAI GIÀ LETTO IL TUO OROSCOPO DI OGGI?</b>\n'
            '✨ Scopri cosa ti riservano le stelle!\n\n', ''
        )
    await bot.send_message(
        chat_id=telegram_chat_id, text=testo, parse_mode='HTML',
        disable_web_page_preview=True, reply_markup=tastiera,
    )
    return True


def orario_recap_configurato():
    """Un solo orario persistente per TECH e CASA, letto a ogni ciclo."""
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute("CREATE TABLE IF NOT EXISTS recap_config (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL)")
        row = db.execute("SELECT valore FROM recap_config WHERE chiave='orario'").fetchone()
    valore = row[0] if row else '22:01'
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', valore):
        return '22:01'
    return valore


def imposta_orario_recap(valore):
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', valore):
        raise ValueError('Orario non valido')
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute("CREATE TABLE IF NOT EXISTS recap_config (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO recap_config(chiave, valore) VALUES ('orario', ?)", (valore,))


RECAP_ORARIO_ATTESA = 905


def tastiera_orario_recap():
    ora = orario_recap_configurato()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('21:45', callback_data='recap_time_2145'),
         InlineKeyboardButton('22:01', callback_data='recap_time_2201')],
        [InlineKeyboardButton('22:30', callback_data='recap_time_2230'),
         InlineKeyboardButton('23:00', callback_data='recap_time_2300')],
        [InlineKeyboardButton('✏️ INSERISCI UN ORARIO', callback_data='recap_time_custom')],
        [InlineKeyboardButton('⬅️ IMPOSTAZIONI', callback_data='settings_menu')],
    ])


async def menu_orario_recap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f'🌙 ORARIO RECAP SERALE\n\nOrario attuale: {orario_recap_configurato()} (Italia)\n'
        'Valido per entrambi i canali TECH e CASA.\n'
        'Il recap viene inviato una sola volta al giorno per canale, se ci sono offerte.\n\n'
        'Seleziona un orario oppure inseriscilo manualmente.',
        reply_markup=tastiera_orario_recap(),
    )
    return ConversationHandler.END


async def seleziona_orario_recap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    valore = query.data.removeprefix('recap_time_')
    if valore == 'custom':
        await query.edit_message_text(
            '✏️ Scrivi il nuovo orario del recap in formato HH:MM (esempio: 22:15).\n'
            'L’orario sarà uguale per TECH e CASA. /annulla per uscire.'
        )
        return RECAP_ORARIO_ATTESA
    imposta_orario_recap(valore[:2] + ':' + valore[2:])
    await query.edit_message_text(
        f'✅ Recap serale programmato alle {orario_recap_configurato()} per TECH e CASA.',
        reply_markup=tastiera_orario_recap(),
    )
    return ConversationHandler.END


async def ricevi_orario_recap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    valore = (update.message.text or '').strip()
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', valore):
        await update.message.reply_text('⚠️ Formato non valido. Scrivi HH:MM, ad esempio 22:15.')
        return RECAP_ORARIO_ATTESA
    imposta_orario_recap(valore)
    await update.message.reply_text(
        f'✅ Nuovo orario recap: {valore} (Italia), valido per TECH e CASA.',
        reply_markup=tastiera_orario_recap(),
    )
    return ConversationHandler.END


async def controlla_recap(app):

    while True:

        try:
            adesso = datetime.now(ROMA_TZ)
            oggi = adesso.date().isoformat()

            ora_recap, minuto_recap = map(int, orario_recap_configurato().split(':'))
            orario_recap_raggiunto = (adesso.hour, adesso.minute) >= (ora_recap, minuto_recap)

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


def config_fascia_manuale(chiave=None, valore=None, canale=None):
    if canale is not None:
        if chiave is not None:
            ARCHIVIO.salva(str(canale), chiave, valore)
        return ARCHIVIO.impostazioni(str(canale))
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute("CREATE TABLE IF NOT EXISTS fascia_manuale (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL)")
        if chiave is not None:
            db.execute("INSERT OR REPLACE INTO fascia_manuale VALUES (?,?)", (chiave, str(valore)))
        valori = dict(db.execute("SELECT chiave,valore FROM fascia_manuale").fetchall())
    return {'attiva': valori.get('attiva', '1') == '1', 'inizio': valori.get('inizio', '08:30'), 'fine': valori.get('fine', '21:30')}


def prossimo_orario_manuale(data, config=None):
    config = config if config is not None else config_fascia_manuale()
    locale = data.astimezone(ROMA_TZ)
    if not config['attiva']:
        return locale
    h, m = map(int, config['inizio'].split(':'))
    inizio = locale.replace(hour=h, minute=m, second=0, microsecond=0)
    h, m = map(int, config['fine'].split(':'))
    fine = locale.replace(hour=h, minute=m, second=59, microsecond=999999)
    if locale < inizio:
        return inizio
    if locale > fine:
        return (inizio + timedelta(days=1)).replace(second=0, microsecond=0)
    return locale


# Pausa Caffè: finestre previste + invii effettivi, separate per canale.
PAUSA_CAFFE_MINUTI = 30


def finestre_pausa_caffe(canale, giorno):
    """Finestre effettive persistenti + finestre future della configurazione corrente.

    Cambiare gli orari non elimina una pausa gia' avviata; una pubblicazione
    registrata non genera una seconda finestra soltanto perche' cambia l'orario.
    """
    cfg = configurazione_oroscopo()
    nome = next((c.chiave for c in CANALI.values() if c.chat_id == str(canale)), None)
    giorno_iso = giorno.isoformat() if hasattr(giorno, 'isoformat') else str(giorno)
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        pubblicazioni = db.execute(
            'SELECT slot,pubblicato_il FROM pausa_caffe_pubblicazioni WHERE giorno=? AND canale=?',
            (giorno_iso, str(canale))).fetchall()
        stati = dict(db.execute(
            'SELECT slot,stato FROM oroscopo_uscite WHERE giorno=? AND canale=?',
            (giorno_iso, str(canale))).fetchall())
    finestre = []
    registrati = set()
    for slot, pubblicato_il in pubblicazioni:
        try:
            inizio = datetime.fromisoformat(pubblicato_il).astimezone(ROMA_TZ)
        except (ValueError, TypeError):
            continue
        registrati.add(slot)
        finestre.append((inizio, inizio + timedelta(minutes=PAUSA_CAFFE_MINUTI)))
    if cfg.get('attivo') and nome in cfg.get('canali', []):
        for slot, ora in orari_oroscopo(cfg):
            if slot in registrati or stati.get(slot) in ('inviato', 'da_verificare', 'in_invio'):
                continue
            previsto = datetime.fromisoformat(f'{giorno_iso}T{ora}').replace(tzinfo=ROMA_TZ)
            finestre.append((previsto, previsto + timedelta(minutes=PAUSA_CAFFE_MINUTI)))
    if nome in CANALI:
        qcfg = configurazione_quiz()
        if qcfg['attivo']:
            with sqlite3.connect(DB_PATH, timeout=30) as db:
                row = db.execute("SELECT stato,pubblicato_il FROM quiz_uscite_canali WHERE giorno=? AND canale=?", (giorno_iso,str(canale))).fetchone()
            if row and row[1]:
                inizio = datetime.fromisoformat(row[1]).astimezone(ROMA_TZ)
                finestre.append((inizio, inizio + timedelta(minutes=PAUSA_CAFFE_MINUTI)))
            elif not row:
                previsto = datetime.fromisoformat(f"{giorno_iso}T{qcfg['ora']}").replace(tzinfo=ROMA_TZ)
                finestre.append((previsto, previsto + timedelta(minutes=PAUSA_CAFFE_MINUTI)))
    return sorted(finestre, key=lambda item: item[0])


def prossimo_fuori_pausa(data, canale):
    locale = data.astimezone(ROMA_TZ)
    for _ in range(8):
        finestre = []
        for offset in (-1, 0, 1):
            finestre.extend(finestre_pausa_caffe(canale, (locale + timedelta(days=offset)).date()))
        conflitti = [fine for inizio, fine in finestre if inizio <= locale < fine]
        if not conflitti:
            return locale
        locale = max(conflitti)
    return locale


async def attendi_finestra_offerte(canale, automazione=None):
    """Rilegge la configurazione prima di ogni invio programmato/automatico."""
    while True:
        adesso = datetime.now(ROMA_TZ)
        ripresa = prossimo_fuori_pausa(adesso, canale)
        if automazione is not None:
            config = leggi_config_automatica(automazione)
            if not config['attiva']:
                raise ValueError('Automazione disattivata per questo canale.')
            fascia = {'attiva': True, 'inizio': config['ora_inizio'], 'fine': config['ora_fine']}
        else:
            fascia = config_fascia_manuale(canale=canale)
        ripresa = prossimo_orario_manuale(ripresa, fascia)
        if ripresa <= adesso:
            return
        await asyncio.sleep(min(30, max(1, (ripresa - adesso).total_seconds())))


def inizializza_pause_caffe():
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS pausa_caffe_pubblicazioni (
            giorno TEXT NOT NULL, canale TEXT NOT NULL, slot INTEGER NOT NULL,
            pubblicato_il TEXT NOT NULL, PRIMARY KEY(giorno, canale, slot))''')


def descrizione_pause_programmate(canale, giorni):
    eventi = []
    for giorno in sorted(set(giorni)):
        for indice, (inizio, fine) in enumerate(finestre_pausa_caffe(canale, giorno)):
            titolo = ('🧠 Quiz del Caffè' if configurazione_quiz()['attivo'] and inizio.strftime('%H:%M') == configurazione_quiz()['ora'] else ('☀️ Prima Pausa Caffè' if inizio.strftime('%H:%M') == configurazione_oroscopo()['ora'] else '🌙 Seconda Pausa Caffè'))
            eventi.append((inizio, f'{inizio:%d/%m • %H:%M}\n{titolo}\n⏸ Pausa offerte fino alle {fine:%H:%M}'))
    return eventi


def slot_manuale_libero(data, occupati, minuti, config):
    passo = timedelta(minutes=max(1, int(minuti)))
    candidato = prossimo_orario_manuale(data, config)
    while True:
        candidato = prossimo_orario_manuale(prossimo_fuori_pausa(candidato, config.get('_canale', CHANNEL_ID)), config)
        conflitti = [t for t in occupati if abs((t-candidato).total_seconds()) < passo.total_seconds()]
        if not conflitti:
            return candidato
        candidato = prossimo_orario_manuale(max(conflitti) + passo, config)


def riallinea_programmati_fascia():
    """Riposiziona fuori fascia e arretrati, preservando ordine e intervalli."""
    ora = datetime.now(timezone.utc).replace(microsecond=0)
    modificati = 0
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute('BEGIN IMMEDIATE')
        righe = db.execute("SELECT id,invio_previsto,telegram_chat_id,intervallo_minuti FROM programmazioni WHERE stato='attesa' ORDER BY invio_previsto,id").fetchall()
        occupati = {}
        for pid, data, chat, minuti in righe:
            precedente = _data_sqlite(data)
            if precedente is None:
                continue
            precedente = precedente.astimezone(timezone.utc)
            base = max(precedente, ora) if precedente < ora-timedelta(seconds=30) else precedente
            canale = str(chat or CHANNEL_ID)
            cfg = config_fascia_manuale(canale=canale)
            nuovo = slot_manuale_libero(base, occupati.setdefault(canale, []), minuti or DISTANZA_MINIMA_MINUTI, dict(cfg, _canale=canale))
            occupati[canale].append(nuovo)
            if nuovo.astimezone(timezone.utc) != precedente:
                db.execute('UPDATE programmazioni SET invio_previsto=? WHERE id=?', (nuovo.astimezone(timezone.utc).isoformat(timespec='seconds'),pid))
                modificati += 1
    return modificati


async def menu_fascia_manuale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    cfg = config_fascia_manuale()
    if q.data == 'mf_toggle':
        cfg = config_fascia_manuale('attiva', 0 if cfg['attiva'] else 1)
        riallinea_programmati_fascia()
    elif q.data in ('mf_inizio','mf_fine'):
        context.user_data['fascia_campo'] = q.data.replace('mf_', '')
        await q.message.reply_text('Scrivi l’orario italiano nel formato HH:MM, ad esempio 08:30. La fine deve essere successiva all’inizio. Per uscire: /annulla.')
        return 'FASCIA_ORARIO'
    context.user_data.pop('fascia_campo', None)
    await q.message.reply_text(
        f"🕒 FASCIA MANUALE E MULTIPLO\n\nStato: {'🟢 ATTIVA' if cfg['attiva'] else '🔴 DISATTIVATA'}\nInizio: {cfg['inizio']}\nFine: {cfg['fine']}\nOra italiana. Fuori fascia gli invii passano al primo spazio consentito. La fascia automatica resta nel suo menu.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('🟢/🔴 Attiva/disattiva',callback_data='mf_toggle')],
            [InlineKeyboardButton('🌅 Inizio: '+cfg['inizio'],callback_data='mf_inizio'),InlineKeyboardButton('🌙 Fine: '+cfg['fine'],callback_data='mf_fine')],
            [InlineKeyboardButton('⬅️ Pubblica offerta',callback_data='publish_menu')]
        ]))
    return ConversationHandler.END


async def ricevi_fascia_manuale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    valore = update.message.text.strip()
    campo = context.user_data.get('fascia_campo')
    cfg = config_fascia_manuale()
    if campo not in ('inizio','fine'):
        return ConversationHandler.END
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', valore):
        await update.message.reply_text('❌ Usa HH:MM, da 00:00 a 23:59.')
        return 'FASCIA_ORARIO'
    cfg[campo] = valore
    if cfg['inizio'] >= cfg['fine']:
        await update.message.reply_text('❌ La fine deve essere successiva all’inizio. Inserisci un altro orario.')
        return 'FASCIA_ORARIO'
    config_fascia_manuale(campo, valore)
    numero = riallinea_programmati_fascia()
    context.user_data.pop('fascia_campo', None)
    await update.message.reply_text(f"✅ Fascia salvata: {cfg['inizio']}–{cfg['fine']} (ora italiana).\nPost riposizionati: {numero}.",reply_markup=menu_pubblicazione())
    return ConversationHandler.END


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

    if "intervallo_minuti" not in colonne:
        cur.execute("ALTER TABLE programmazioni ADD COLUMN intervallo_minuti INTEGER DEFAULT 30")

    if "origine" not in colonne:
        cur.execute("ALTER TABLE programmazioni ADD COLUMN origine TEXT DEFAULT 'manuale'")

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
    origine="manuale",
):

    # Salviamo in UTC per evitare problemi
    # con ora legale/solare.
    invio_previsto_utc = (
        invio_previsto_locale
        .astimezone(timezone.utc)
    )

    cfg = dict(config_fascia_manuale(canale=telegram_chat_id or CHANNEL_ID), _canale=str(telegram_chat_id or CHANNEL_ID))
    primo_consentito = datetime.now(ROMA_TZ) + timedelta(minutes=minuti_rimanenti_prima_del_prossimo_invio(telegram_chat_id or CHANNEL_ID))
    invio_previsto_locale = max(invio_previsto_locale, primo_consentito)
    db = sqlite3.connect(DB_PATH, timeout=30)
    cur = db.cursor()
    cur.execute('BEGIN IMMEDIATE')
    righe = cur.execute("SELECT invio_previsto FROM programmazioni WHERE stato IN ('attesa','in_invio','da_verificare') AND CAST(COALESCE(telegram_chat_id,?) AS TEXT)=?", (str(CHANNEL_ID),str(telegram_chat_id or CHANNEL_ID))).fetchall()
    occupati = [_data_sqlite(r[0]) for r in righe if _data_sqlite(r[0])]
    invio_previsto_locale = slot_manuale_libero(invio_previsto_locale, occupati, DISTANZA_MINIMA_MINUTI, cfg)
    invio_previsto_utc = invio_previsto_locale.astimezone(timezone.utc)

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
    cur.execute("UPDATE programmazioni SET intervallo_minuti=?,origine=? WHERE id=?", (DISTANZA_MINIMA_MINUTI,origine, programmazione_id))

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
    with sqlite3.connect(DB_PATH) as db_stato:
        row = db_stato.execute("SELECT stato FROM programmazioni WHERE id=? AND CAST(telegram_chat_id AS TEXT)=?", (programmazione_id, str(destinazione))).fetchone()
    if not row or row[0] != 'attesa':
        return

    with sqlite3.connect(DB_PATH) as db_duplicati:
        origine_riga = db_duplicati.execute(
            "SELECT origine FROM programmazioni WHERE id=?", (programmazione_id,)
        ).fetchone()
    if origine_riga and origine_riga[0] in ('multiplo','repost','cronologia'):
        asin_multiplo = estrai_asin_da_link(link)
        if prodotto_inviato_ultime_24h(asin_multiplo, destinazione):
            with sqlite3.connect(DB_PATH) as db_duplicati:
                db_duplicati.execute("UPDATE programmazioni SET stato='scartata' WHERE id=?", (programmazione_id,))
            await _notifica_admin_automazione(
                bot, f"⏭ Invio multiplo scartato: {nome}\n{link}\nGià pubblicato nelle ultime 24 ore nel canale di destinazione."
            )
            return

    # Il post programmato e' stato preparato durante l'acquisizione del link.
    # Nessuna seconda lettura Amazon immediatamente prima della pubblicazione.

    messaggio_html = messaggio.startswith("__RICERCA_HTML__")
    if messaggio_html:
        messaggio = messaggio.replace("__RICERCA_HTML__", "", 1)
    messaggio_con_link = crea_caption_con_link(
        messaggio,
        link,
        messaggio_gia_html=messaggio_html,
    )

    bottone_offerta = tastiera_offerta_automatica(link)

    # Ricontrolla la pausa anche se la coda e' stata preparata ore prima.
    await attendi_finestra_offerte(destinazione)
    with sqlite3.connect(DB_PATH) as db_stato:
        acquisita = db_stato.execute("UPDATE programmazioni SET stato='in_invio' WHERE id=? AND CAST(telegram_chat_id AS TEXT)=? AND stato='attesa'", (programmazione_id, str(destinazione))).rowcount
    if not acquisita:
        return
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

    await aggiorna_pulsanti_offerta(bot, messaggio_telegram, link, chat_id=destinazione)

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
    # L'invio multiplo pubblica esclusivamente i link forniti dall'utente.
    with sqlite3.connect(DB_PATH) as db_origine:
        origine_riga = db_origine.execute(
            "SELECT origine FROM programmazioni WHERE id=?", (programmazione_id,)
        ).fetchone()
    if not origine_riga or origine_riga[0] not in ("multiplo","repost","cronologia"):
        if str(destinazione) == str(CASA_CHANNEL_ID):
            await controlla_raccolta_dopo_post_casa(bot)



async def controlla_programmazioni(app):

    while True:

        try:

            riallinea_programmati_fascia()
            adesso_locale = datetime.now(ROMA_TZ)

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
                ora_controllo = datetime.now(ROMA_TZ)
                if prossimo_orario_manuale(ora_controllo, config_fascia_manuale(canale=programmazione[6] or CHANNEL_ID)) != ora_controllo:
                    continue
                if prossimo_fuori_pausa(ora_controllo, programmazione[6]) > ora_controllo:
                    riallinea_programmati_fascia()
                    continue

                try:

                    await invia_offerta_programmata(
                        app.bot,
                        programmazione,
                    )

                except Exception as errore:

                    with sqlite3.connect(DB_PATH) as db_stato:
                        db_stato.execute("UPDATE programmazioni SET stato='da_verificare' WHERE id=? AND stato='in_invio'", (programmazione[0],))
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

    app.create_task(controlla_oroscopi(app))
    app.create_task(controlla_quiz(app))

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

    if not ADMIN_ID and not os.environ.get('ADMIN_TELEGRAM_IDS'):
        return False

    user = update.effective_user

    if not user:
        return False

    return str(user.id) in {x.strip() for x in (str(ADMIN_ID or '') + ',' + os.environ.get('ADMIN_TELEGRAM_IDS', '')).split(',') if x.strip()}


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
        "tentativi_ricerca": "3",
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
    if canale not in CANALI:
        raise ValueError("Canale non configurato.")
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
    categorie_consentite = categorie_consentite_canale(canale)
    categorie = [
        riga[0] for riga in cur.fetchall() if riga[0] in categorie_consentite
    ]
    db.close()
    return {
        "_canale": canale,
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
        "tentativi_ricerca": 3,
        "giorni_blocco_duplicati": int(valori.get("giorni_blocco_duplicati", "10")),
        "raggruppa_varianti": valori.get("raggruppa_varianti", "1") == "1",
        "categorie": categorie,
    }


def salva_config_automatica(chiave, valore, canale="tech"):
    if canale not in CANALI:
        raise ValueError("Canale non configurato.")
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
    data = FILTRI.leggi()['marchi']
    if categoria:
        return sorted(data.get(categoria, []), key=str.casefold)
    return [(category, brand) for category in sorted(data) for brand in sorted(data[category], key=str.casefold)]


def leggi_parole_indesiderate():
    return sorted(FILTRI.leggi()['parole'], key=str.casefold)


def leggi_prodotti_prioritari(categoria=None):
    rows = [tuple(r) for r in FILTRI.leggi()['priorita'] if categoria is None or r[1] == categoria]
    return sorted(rows, key=lambda r: (r[1], -r[4], r[2].casefold()))


def leggi_parole_accessori_priorita():
    return sorted(FILTRI.leggi()['accessori'], key=str.casefold)


def termini_prioritari_categoria(categoria):
    termini = []
    for _, _, parola, _, _ in leggi_prodotti_prioritari(categoria):
        if parola.lower() not in {termine.lower() for termine in termini}:
            termini.append(parola)
    return termini


def _testo_elenco(valori, vuoto="nessuno"):
    return ", ".join(valori) if valori else vuoto


async def mostra_menu_filtri(query):
    configurazione = leggi_config_automatica(filtri_canale.corrente())
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
    return categorie_consentite_canale(_auto_canale_corrente(context))


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
        FILTRI.ripristina_filtri(MARCHI_AUTORIZZATI, PAROLE_INDESIDERATE)
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


async def ricevi_modifica_filtro(update, context):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    valore = _pulisci_valore_filtro(update.message.text)
    stato = context.user_data.get('stato_filtro_corrente')
    if len(valore) < 2:
        await update.message.reply_text('❌ Inserisci almeno 2 caratteri.')
        return stato
    categoria = context.user_data.get('filtro_categoria')
    if stato in (FILTRO_MARCHIO_AGGIUNGI, FILTRO_MARCHIO_RIMUOVI):
        if categoria not in AUTO_CATEGORIE:
            return ConversationHandler.END
        trovato = FILTRI.marchio(categoria, valore, stato == FILTRO_MARCHIO_AGGIUNGI)
        messaggio = f'✅ Marchio aggiunto: {valore}' if stato == FILTRO_MARCHIO_AGGIUNGI else '✅ Marchio rimosso.' if trovato else 'ℹ️ Marchio non trovato.'
    elif stato in (FILTRO_PAROLA_AGGIUNGI, FILTRO_PAROLA_RIMUOVI):
        trovato = FILTRI.parola('parole', valore, stato == FILTRO_PAROLA_AGGIUNGI)
        messaggio = f'✅ Parola esclusa aggiunta: {valore}' if stato == FILTRO_PAROLA_AGGIUNGI else '✅ Parola rimossa.' if trovato else 'ℹ️ Parola non trovata.'
    else:
        return ConversationHandler.END
    channel = _auto_canale_corrente(context)
    salva_config_automatica('attiva', 0, channel)
    await update.message.reply_text(messaggio+'\n\nAutomazione disattivata solo per questo canale.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⚙️ TORNA AI FILTRI',callback_data=_callback_ritorno_filtri(context))]]))
    context.user_data.pop('stato_filtro_corrente',None)
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
        FILTRI.ripristina_priorita(PRODOTTI_PRIORITARI_DEFAULT, PAROLE_ACCESSORI_PRIORITA_DEFAULT)
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


async def ricevi_modifica_priorita(update, context):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    stato = context.user_data.get('stato_priorita_corrente')
    testo = _pulisci_valore_filtro(update.message.text)
    categoria = context.user_data.get('priorita_categoria')
    try:
        if stato == PRIORITA_AGGIUNGI:
            parts = [p.strip() for p in testo.split('|')]
            if len(parts) != 3 or categoria not in AUTO_CATEGORIE:
                raise ValueError
            parola,marchio,bonus = parts[0],parts[1],int(parts[2])
            if not parola or not marchio or not 1 <= bonus <= 10:
                raise ValueError
            FILTRI.priorita(categoria,parola,marchio,bonus)
            messaggio = f'✅ Priorità salvata: {parola} · {marchio} · +{bonus}'
        elif stato == PRIORITA_RIMUOVI:
            trovato = FILTRI.rimuovi_priorita(int(testo.lstrip('#')),categoria)
            messaggio = '✅ Priorità rimossa.' if trovato else 'ℹ️ Regola non trovata.'
        elif stato in (PRIORITA_ACCESSORIO_AGGIUNGI, PRIORITA_ACCESSORIO_RIMUOVI):
            if len(testo) < 2:
                raise ValueError
            trovato = FILTRI.parola('accessori',testo,stato == PRIORITA_ACCESSORIO_AGGIUNGI)
            messaggio = '✅ Parola anti-accessorio salvata.' if stato == PRIORITA_ACCESSORIO_AGGIUNGI else '✅ Parola rimossa.' if trovato else 'ℹ️ Parola non trovata.'
        else:
            raise ValueError
    except (TypeError,ValueError):
        await update.message.reply_text('❌ Valore non valido. Per le priorità usa PRODOTTO | MARCHIO | BONUS, con bonus da 1 a 10.')
        return stato
    salva_config_automatica('attiva',0,_auto_canale_corrente(context))
    context.user_data.pop('stato_priorita_corrente',None)
    await update.message.reply_text(messaggio+'\n\nAutomazione disattivata solo per questo canale.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🚀 MENU PRIORITÀ',callback_data='priority_menu')]]))
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
    elif canale == "tech":
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
    channel = canale_corrente(context)
    if channel is None:
        raise ValueError('Seleziona prima il canale.')
    return channel.chiave


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
    nome_canale = CANALI[canale].nome
    amazon = "ATTIVA" if configurazione["priorita_amazon"] else "DISATTIVATA"
    varianti = "ATTIVO" if configurazione["raggruppa_varianti"] else "DISATTIVO"
    await query.edit_message_text(
        f"⚙️ MODALITÀ SELETTIVA — {nome_canale}\n\n"
        "Marchi, parole escluse e regole di priorità sono indipendenti per questo canale.\n"
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
            "tentativi_ricerca": 3,
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
    intestazione = CANALI[canale].nome
    return (
        f"🤖 INVIO AUTOMATICO — {intestazione}\n\n"
        "⚠️ Sorgente ricerca Creators API disabilitata nel legacy.\n"
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
    consentite = categorie_consentite_canale(canale)
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
        consentite = categorie_consentite_canale(canale)
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
        condizione_api = getattr(offerta, 'condition', None)
        condizione_api = (getattr(condizione_api, 'value', None) or getattr(condizione_api, 'display_value', None) or str(condizione_api or '')).strip()
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
            "condizione": condizione_api,
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
            "categoria": categoria_da_item_creators(item),
        }
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def categoria_da_item_creators(item):
    info = getattr(item, 'browse_node_info', None)
    nodi = getattr(info, 'browse_nodes', None) or []
    for nodo in nodi:
        nome = getattr(nodo, 'display_name', None) or getattr(nodo, 'context_free_name', None)
        if nome:
            return str(nome)
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
    configurazione = configurazione or leggi_config_automatica(filtri_canale.corrente())
    with filtri_canale.ambito(configurazione.get('_canale', filtri_canale.corrente())):
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


@filtri_canale.fisso('casa')
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
    # La raccolta contiene più prodotti: i link APRI sono già nei singoli articoli.
    return None


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


@filtri_canale.fisso('casa')
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


@filtri_canale.fisso('tech')
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
    # La raccolta contiene più prodotti: i link APRI sono già nei singoli articoli.
    return None


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
    condizioni = ["telegram_chat_id=?", "origine='automatico'"]
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


@filtri_canale.fisso('tech')
async def controlla_raccolta_dopo_post_tech(bot, origine=None):
    """Solo una pubblicazione della ricerca automatica può avviare le raccolte."""
    if origine != "automatico" or not leggi_config_automatica("tech")["attiva"]:
        return False
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
        tastiera = tastiera_offerta_automatica(prodotto["link"], asin=prodotto.get("asin"))
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
    testo = '👁 <b>ANTEPRIMA</b>\n\n' + crea_caption_con_link(crea_corpo_offerta_automatica(prodotto),prodotto['link'])
    tastiera = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 PUBBLICA ORA", callback_data=f"os_publish_{indice}")],
        [InlineKeyboardButton("🕒 PROGRAMMA", callback_data=f"os_program_{indice}")],
        *tastiera_offerta_automatica(prodotto["link"], asin=prodotto.get("asin")).inline_keyboard,
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
        canale = azione.removeprefix("offer_search_")
        if canale not in CANALI:
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
    return '__RICERCA_HTML__' + crea_corpo_offerta_automatica(prodotto)


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
        _chat_id_per_canale(canale) if canale in CANALI
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
    return canali.chat_per_chiave(CANALI, canale)


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
    if canale not in CANALI:
        raise ValueError("Canale non configurato.")
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
    if canale not in CANALI:
        raise ValueError("Canale non configurato.")
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
    if canale not in CANALI:
        raise ValueError("Canale non configurato.")
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


@filtri_canale.per_parametro('canale')
async def cerca_offerta_automatica(configurazione, categoria_iniziale, canale="tech"):
    categorie = list(configurazione["categorie"])
    if categoria_iniziale in categorie:
        indice = categorie.index(categoria_iniziale)
        categorie = categorie[indice:] + categorie[:indice]

    snapshot_filtri = carica_snapshot_filtri(configurazione=configurazione)

    massimo = 3  # Limite fisso per ciclo di ricerca automatica
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
        # Ricerca automatica limitata a tre tentativi per ciclo.
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
    # La ricerca e i filtri rimangono invariati. Completiamo soltanto i
    # candidati con dati insufficienti, PRIMA della fase di pubblicazione.
    for candidato in candidati:
        pronto = await completa_candidato_automatico(candidato)
        if pronto is not None:
            return pronto, statistiche
        statistiche['incompleti'] += 1
        print(f"Offerta automatica saltata dopo recupero: {candidato.get('asin')}")
    return None, statistiche


def crea_corpo_offerta_automatica(prodotto, categoria=None):
    if prodotto.get('tipologia_amazon') in ('seconda_mano', 'renewed'):
        return render_template_condizione(prodotto)
    return corpo_pulito_post(prodotto['nome'],prodotto['prezzo'],prodotto.get('vecchio_prezzo'),categoria or prodotto.get('categoria'),prodotto.get('coupon'))


TIKTOK_PROFILO_URL = "https://www.tiktok.com/@amazontechdeal5"


def link_post_telegram(messaggio=None, chat_id=None, message_id=None):
    """Usa il canale realmente restituito da Telegram, anche per ID numerici."""
    if messaggio is not None:
        try:
            collegamento = messaggio.link
            if isinstance(collegamento, str) and collegamento.startswith("https://t.me/"):
                return collegamento
        except (AttributeError, TypeError, ValueError):
            pass
        chat = getattr(messaggio, "chat", None)
        username = getattr(chat, "username", None)
        chat_id = (
            "@" + username if isinstance(username, str) and username
            else getattr(messaggio, "chat_id", None) or chat_id
        )
        message_id = getattr(messaggio, "message_id", None) or message_id
    if not message_id:
        return None
    identita = str(chat_id or "")
    if identita.startswith("@"):
        return f"https://t.me/{identita[1:]}/{message_id}"
    if identita.startswith("-100") and identita[4:].isdigit():
        return f"https://t.me/c/{identita[4:]}/{message_id}"
    return None


def tastiera_offerta_automatica(link, link_post=None, asin=None):
    """Tastiera unica 2x2 per tutti i percorsi di pubblicazione delle offerte."""
    asin = str(asin or estrai_asin_da_link(link) or "").upper()
    condivisione = "https://t.me/share/url?" + urlencode({
        "url": link_post or link,
        "text": "🔥 Guarda questa offerta su BestPrice24h!",
    })
    storico = (
        InlineKeyboardButton("📈 Prezzi", url=f"https://keepa.com/#!product/8-{asin}")
        if re.fullmatch(r"[A-Z0-9]{10}", asin)
        else InlineKeyboardButton("📈 Prezzi", callback_data="offer_price_unavailable")
    )
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Condividi", url=condivisione),
         InlineKeyboardButton("🛒 Apri", url=link)],
        [storico, InlineKeyboardButton("🎵 TikTok", url=TIKTOK_PROFILO_URL)],
    ])


async def aggiorna_pulsanti_offerta(bot, messaggio, link, asin=None, chat_id=None):
    """Dopo l'invio si conosce l'ID del post da condividere. Non reinvia il post."""
    try:
        asin = asin or estrai_asin_da_link(link)
        if not asin:
            asin = await asyncio.wait_for(
                asyncio.to_thread(risolvi_asin_da_link, link), timeout=5
            )
    except Exception:
        asin = None
    try:
        destinazione = getattr(messaggio, "chat_id", None) or chat_id
        await bot.edit_message_reply_markup(
            chat_id=destinazione,
            message_id=messaggio.message_id,
            reply_markup=tastiera_offerta_automatica(
                link, link_post=link_post_telegram(messaggio, chat_id=chat_id), asin=asin
            ),
        )
    except Exception as errore:
        # Il post è già pubblicato: un errore della tastiera non deve duplicarlo.
        print(f"Aggiornamento pulsanti offerta non riuscito: {type(errore).__name__}: {errore}")


async def storico_prezzi_non_disponibile(update, context):
    await update.callback_query.answer(
        "Non è stato possibile identificare il prodotto per Keepa. "
        "Apri l'offerta Amazon e cerca il suo ASIN su Keepa.",
        show_alert=True,
    )


async def pubblica_offerta_automatica(bot, prodotto, canale=None, origine="automatico"):
    if canale is not None and canale not in CANALI:
        raise ValueError('Canale non configurato.')
    canale_effettivo = canale or ('casa' if prodotto.get('categoria') in CASA_CATEGORIE else 'tech')
    prodotto = dict(prodotto)
    if tag_canale(canale_effettivo):
        prodotto['link'] = link_affiliato_multiplo(prodotto.get('link'), prodotto.get('asin') or risolvi_asin_da_link(prodotto.get('link')), canale_effettivo)
    tipo = tipo_o_fallback(prodotto.get('link'), prodotto)
    if tipo == 'sconosciuto' and not prodotto.get('_lettura_offerta_completata'):
        # Solo per pubblicazioni dirette non passate dalla ricerca automatica.
        # La ricerca automatica ha gia' completato l'acquisizione; nessuna
        # seconda lettura viene eseguita al momento del suo invio.
        recuperato = await leggi_offerta_con_sei_tentativi(prodotto.get('link'), richiedi_immagine=True)
        if not recuperato:
            raise ValueError('Offerta non leggibile dopo 3 tentativi: prodotto saltato')
        prodotto.update(recuperato)
        tipo = tipo_o_fallback(prodotto.get('link'), prodotto)
    elif tipo == 'sconosciuto':
        raise ValueError('Offerta non verificabile: prodotto saltato')
    prodotto['tipologia_amazon'] = tipo
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
    tastiera = tastiera_offerta_automatica(prodotto["link"], asin=prodotto.get("asin"))
    foto = await prepara_foto_automatica(prodotto["immagine"])
    telegram_chat_id = _chat_id_per_canale(canale_effettivo)
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
    # Ultima verifica degli orari aggiornati prima di inviare l'offerta.
    await attendi_finestra_offerte(telegram_chat_id, automazione=canale_effettivo if origine == 'automatico' else None)
    messaggio_telegram = await bot.send_photo(
        chat_id=telegram_chat_id,
        photo=foto,
        caption=messaggio,
        parse_mode="HTML",
        reply_markup=tastiera,
    )
    await aggiorna_pulsanti_offerta(
        bot, messaggio_telegram, prodotto["link"], asin=prodotto.get("asin"),
        chat_id=telegram_chat_id,
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
    elif canale_effettivo == "tech" and origine == "automatico":
        await controlla_raccolta_dopo_post_tech(bot, origine=origine)
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

        # Uno slot automatico in pausa resta prenotato e attende la ripresa.
        while True:
            adesso_pausa = datetime.now(ROMA_TZ)
            ripresa = prossimo_fuori_pausa(adesso_pausa, _chat_id_per_canale(canale))
            if ripresa <= adesso_pausa:
                break
            if not _dentro_fascia_automatica(configurazione, ripresa):
                _aggiorna_slot_automatico(data_slot, slot_ora_db, 'rinviata_pausa')
                return
            await asyncio.sleep(max(1, (ripresa - adesso_pausa).total_seconds()))
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
            if not SORGENTE_RICERCA_ATTIVA:
                await asyncio.sleep(30)
                continue
            for canale in tuple(CANALI):
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


@monitoraggio.solo_se_attivo
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
        reply_markup=tastiera_offerta_automatica(
            prodotto["link"],
            link_post=link_post_telegram(chat_id=telegram_chat_id or CHANNEL_ID, message_id=message_id),
            asin=prodotto.get("asin"),
        ),
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
          AND telegram_chat_id = ? AND telegram_message_id = ?
        """,
        (invio_id, str(destinazione), message_id),
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


@monitoraggio.solo_se_attivo
async def controlla_raccolte_casa_terminate(app):
    """Controlla ogni articolo del collage e aggiorna una sola volta la didascalia."""
    righe = _prodotti_raccolta_da_verificare()
    raccolte_modificate = set()
    nomi_terminati = []
    for posizione in range(0, len(righe), 10):
        if not monitoraggio.attivo(DB_PATH):
            return
        gruppo = righe[posizione:posizione + 10]
        asins = [riga[2] for riga in gruppo if riga[2]]
        if not asins:
            continue
        prodotti_api = await _prodotti_monitorati_da_pagina(asins)
        for (
            prodotto_id, raccolta_id, asin, nome, _,
            prezzo_memorizzato, vecchio_memorizzato, sconto_memorizzato,
        ) in gruppo:
            if not monitoraggio.attivo(DB_PATH):
                return
            prodotto = prodotti_api.get(asin)
            if prodotto:
                _aggiorna_verifica_prodotto_raccolta(prodotto_id, False)
            if not prodotto:
                # Un risultato API mancante non dimostra che lo sconto sia finito.
                continue
            sconto_azzerato = bool(prodotto and prodotto.get("sconto") is not None and int(prodotto["sconto"]) == 0)
            if sconto_azzerato:
                raccolta_modificata = _segna_prodotto_raccolta_terminato(prodotto_id)
                if raccolta_modificata:
                    raccolte_modificate.add(raccolta_modificata)
                    nomi_terminati.append(nome)
                continue
            valori_cambiati = (
                prodotto.get('sconto') is not None and (
                int(prodotto.get("sconto") or 0) != int(sconto_memorizzato or 0)
                or _normalizza_valore_monitorato(prodotto.get("prezzo"))
                != _normalizza_valore_monitorato(prezzo_memorizzato)
                or _normalizza_valore_monitorato(prodotto.get("vecchio_prezzo"))
                != _normalizza_valore_monitorato(vecchio_memorizzato)
                )
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


@monitoraggio.solo_se_attivo
async def controlla_raccolte_tech_terminate(app):
    """Controlla ogni articolo del collage e aggiorna una sola volta la didascalia."""
    righe = _prodotti_raccolta_tech_da_verificare()
    raccolte_modificate = set()
    nomi_terminati = []
    for posizione in range(0, len(righe), 10):
        if not monitoraggio.attivo(DB_PATH):
            return
        gruppo = righe[posizione:posizione + 10]
        asins = [riga[2] for riga in gruppo if riga[2]]
        if not asins:
            continue
        prodotti_api = await _prodotti_monitorati_da_pagina(asins)
        for (
            prodotto_id, raccolta_id, asin, nome, _,
            prezzo_memorizzato, vecchio_memorizzato, sconto_memorizzato,
        ) in gruppo:
            if not monitoraggio.attivo(DB_PATH):
                return
            prodotto = prodotti_api.get(asin)
            if prodotto:
                _aggiorna_verifica_prodotto_raccolta_tech(prodotto_id, False)
            if not prodotto:
                # Un risultato API mancante non dimostra che lo sconto sia finito.
                continue
            sconto_azzerato = bool(prodotto and prodotto.get("sconto") is not None and int(prodotto["sconto"]) == 0)
            if sconto_azzerato:
                raccolta_modificata = _segna_prodotto_raccolta_tech_terminato(prodotto_id)
                if raccolta_modificata:
                    raccolte_modificate.add(raccolta_modificata)
                    nomi_terminati.append(nome)
                continue
            valori_cambiati = (
                prodotto.get('sconto') is not None and (
                int(prodotto.get("sconto") or 0) != int(sconto_memorizzato or 0)
                or _normalizza_valore_monitorato(prodotto.get("prezzo"))
                != _normalizza_valore_monitorato(prezzo_memorizzato)
                or _normalizza_valore_monitorato(prodotto.get("vecchio_prezzo"))
                != _normalizza_valore_monitorato(vecchio_memorizzato)
                )
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



async def _prodotti_monitorati_da_pagina(asins):
    """Legge ASIN dal sito senza API; non equipara errore di lettura a prodotto terminato."""
    risultati = {}
    for asin in dict.fromkeys(a for a in asins if a):
        dati = await leggi_offerta_con_sei_tentativi(f'https://www.amazon.it/dp/{asin}')
        if not dati or dati.get('disponibile') is False:
            print(f'Monitoraggio {asin}: dati non verificabili, post lasciato invariato')
            continue
        prezzo = numero_da_prezzo(str(dati.get('prezzo') or ''))
        vecchio = numero_da_prezzo(str(dati.get('vecchio_prezzo') or ''))
        if not prezzo or prezzo <= 0:
            continue
        # Zero solo quando c'e' evidenza esplicita; senza prezzo precedente
        # lo sconto e' sconosciuto e non va dichiarato terminato.
        if vecchio and vecchio > 0:
            dati['sconto'] = max(0, round((1 - prezzo / vecchio) * 100))
        else:
            dati['sconto'] = None
        dati['asin'] = asin
        risultati[asin] = dati
    return risultati

# Evita di terminare post sulla base di una singola lettura incerta.
_conferme_sconto_zero_monitoraggio = {}

async def controlla_offerte_terminate(app):
    while True:
        try:
            if not monitoraggio.attivo(DB_PATH):
                await asyncio.sleep(30)
                continue
            offerte = _offerte_da_verificare()
            for posizione in range(0, len(offerte), 10):
                if not monitoraggio.attivo(DB_PATH):
                    break
                gruppo = offerte[posizione:posizione + 10]
                asins = [riga[1] for riga in gruppo if riga[1]]
                if not asins:
                    continue
                prodotti = await _prodotti_monitorati_da_pagina(asins)

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
                    if not monitoraggio.attivo(DB_PATH):
                        break
                    prodotto = prodotti.get(asin)
                    if prodotto:
                        _aggiorna_verifica_offerta(invio_id, False)
                    if not prodotto:
                        # Le API possono omettere temporaneamente un ASIN:
                        # senza uno sconto certo allo 0% il post resta invariato.
                        continue

                    sconto_attuale = int(prodotto.get("sconto") or 0)
                    chiave_monitoraggio = (invio_id, asin)
                    if prodotto.get('sconto') is not None and sconto_attuale == 0:
                        # Una singola lettura con prezzo/listino uguali puo' essere
                        # temporanea o inesatta. Richiedi una conferma nel ciclo
                        # successivo (30 minuti), senza segnare il post come terminato.
                        conferme = _conferme_sconto_zero_monitoraggio.get(chiave_monitoraggio, 0) + 1
                        _conferme_sconto_zero_monitoraggio[chiave_monitoraggio] = conferme
                        if conferme < 2:
                            print(f'Monitoraggio {asin}: sconto 0% rilevato, attendo seconda verifica prima di modificare il post.')
                            continue
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

                    _conferme_sconto_zero_monitoraggio.pop(chiave_monitoraggio, None)
                    valori_cambiati = (
                        prodotto.get('sconto') is not None and (
                        sconto_attuale != int(sconto_iniziale or 0)
                        or _normalizza_valore_monitorato(prodotto.get("prezzo"))
                        != _normalizza_valore_monitorato(prezzo_memorizzato)
                        or _normalizza_valore_monitorato(prodotto.get("vecchio_prezzo"))
                        != _normalizza_valore_monitorato(vecchio_memorizzato)
                        )
                    )
                    if valori_cambiati:
                        try:
                            if not prodotto.get('link'):
                                with sqlite3.connect(DB_PATH, timeout=30) as db:
                                    record_link = db.execute(
                                        'SELECT link FROM recap_offerte WHERE asin=? AND telegram_message_id=? LIMIT 1',
                                        (asin, message_id),
                                    ).fetchone()
                                prodotto['link'] = record_link[0] if record_link and record_link[0] else None
                                if not prodotto['link']:
                                    print(f'Monitoraggio {asin}: link affiliato originale non disponibile, aggiornamento saltato.')
                                    continue
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

        for _ in range(60):
            if not monitoraggio.attivo(DB_PATH):
                break
            await asyncio.sleep(30)


# =========================================================
# MENU ADMIN
# =========================================================

def menu_principale():
    return menu_canali.menu_iniziale(_servizi_invii)


def menu_pubblicazione():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📝 Invio singolo', callback_data='nuova')],
        [InlineKeyboardButton('📦 Invio multiplo', callback_data='rapido')],
        [InlineKeyboardButton('⬅️ Menu canale', callback_data='menu_admin')],
    ])


async def mostra_menu_pubblicazione(update, context):
    if not await controlla_autorizzazione(update) or not await richiedi_canale(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    await update.effective_message.reply_text('✍️ NUOVI POST — ' + canale_corrente(context).nome, reply_markup=menu_pubblicazione())
    return ConversationHandler.END


def menu_storico():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗂 TUTTI I PRODOTTI", callback_data="archive_all")],
        [InlineKeyboardButton("🕒 ULTIME PUBBLICAZIONI", callback_data="ultime")],
        [InlineKeyboardButton("🔁 INVIA DI NUOVO", callback_data="reinvia_menu")],
        [InlineKeyboardButton("⬅️ TORNA AL MENU PRINCIPALE", callback_data="menu_admin")],
    ])


async def mostra_menu_storico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await mostra_archivio(update, context)


def menu_impostazioni():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 GESTIONE CANALI", callback_data="channels_manage")],
        [InlineKeyboardButton("🎨 GRAFICA E TEMPLATE", callback_data="template")],
        [InlineKeyboardButton("🎯 FILTRI E PRIORITÀ", callback_data="auto_filtri")],
        [InlineKeyboardButton("🌙 ORARIO RECAP SERALE", callback_data="recap_time_menu")],
        [InlineKeyboardButton("📊 STATO DEL BOT", callback_data="bot_status")],
        [InlineKeyboardButton("📋 LOG E DIAGNOSTICA", callback_data="diag_logs_all_0")],
        [InlineKeyboardButton("⬅️ TORNA AL MENU PRINCIPALE", callback_data="menu_admin")],
    ])


def _diagnostic_entries(kind="all"):
    with _LOG_LOCK:
        entries = list(_LOG_BUFFER)
    if kind == "errors":
        entries = [e for e in entries if re.search(r"errore|error|exception|traceback|fallit|timeout|denied|warning|pending", e[2], re.I)]
    elif kind == "amazon":
        entries = [e for e in entries if re.search(r"amazon|asin|creator|prezzo|lettura|offert", e[2], re.I)]
    return entries


def _diag_keyboard(kind, page, total):
    buttons = [
        [InlineKeyboardButton("📋 Tutti", callback_data="diag_logs_all_0"),
         InlineKeyboardButton("❌ Errori", callback_data="diag_logs_errors_0"),
         InlineKeyboardButton("📦 Amazon", callback_data="diag_logs_amazon_0")],
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Più recenti", callback_data=f"diag_logs_{kind}_{page-1}"))
    if (page + 1) * 12 < total:
        nav.append(InlineKeyboardButton("Più vecchi ➡️", callback_data=f"diag_logs_{kind}_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.extend([
        [InlineKeyboardButton("🔄 Aggiorna", callback_data=f"diag_logs_{kind}_{page}"),
         InlineKeyboardButton("📄 Esporta TXT", callback_data=f"diag_export_{kind}")],
        [InlineKeyboardButton("⬅️ Impostazioni", callback_data="settings_menu")],
    ])
    return InlineKeyboardMarkup(buttons)


async def mostra_log_diagnostici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer()
    match = re.fullmatch(r"diag_logs_(all|errors|amazon)_(\d+)", query.data or "")
    if not match:
        return
    kind, page = match.group(1), int(match.group(2))
    entries = _diagnostic_entries(kind)
    total = len(entries)
    max_page = max(0, (total - 1) // 12)
    page = min(page, max_page)
    subset = list(reversed(entries))[page * 12:(page + 1) * 12]
    heading = {"all": "TUTTI", "errors": "ERRORI", "amazon": "AMAZON"}[kind]
    lines = [f"📋 LOG BOT — {heading}",
             f"Avvio raccolta: {_LOG_STARTED.astimezone(ROMA_TZ):%d/%m/%Y %H:%M}",
             f"Eventi: {total} · Pagina {page + 1}/{max_page + 1}",
             "(Solo processo corrente, non l'intero storico Railway)", ""]
    for stamp, source, line in subset:
        candidate = f"[{stamp}] {line}"
        lines.append(candidate[:420])
    text = "\n".join(lines)
    while len(text) > 3900 and len(lines) > 5:
        lines.pop()
        text = "\n".join(lines)
    await query.edit_message_text(text, reply_markup=_diag_keyboard(kind, page, total))


async def esporta_log_diagnostici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    query = update.callback_query
    await query.answer("Preparazione log…")
    match = re.fullmatch(r"diag_export_(all|errors|amazon)", query.data or "")
    if not match:
        return
    kind = match.group(1)
    entries = _diagnostic_entries(kind)
    lines = [f"BestPrice24h — Log {kind}",
             f"Raccolta dal {_LOG_STARTED.astimezone(ROMA_TZ):%Y-%m-%d %H:%M:%S}",
             "Solo log raccolti dal bot durante questo processo; non log completi Railway.", ""]
    lines.extend(f"[{stamp}] [{source}] {line}" for stamp, source, line in entries)
    data = BytesIO("\n".join(lines).encode("utf-8", errors="replace"))
    data.name = f"BestPrice24h_log_{kind}_{datetime.now(ROMA_TZ):%Y%m%d_%H%M}.txt"
    await context.bot.send_document(chat_id=update.effective_chat.id, document=data,
                                    filename=data.name, caption=f"📋 Log {kind}: {len(entries)} eventi")


async def mostra_menu_impostazioni(update, context):
    return await menu_canali.gestisci(_servizi_invii, update, context, data_override='v2_settings')


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


async def torna_menu_admin(update, context):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    await update.callback_query.answer()
    reset_flusso(context)
    channel = canale_corrente(context)
    await update.effective_message.reply_text('📢 GESTIONE ' + channel.nome if channel else '📢 SCEGLI IL CANALE', reply_markup=menu_canali.menu_canale(_servizi_invii, channel) if channel else menu_canali.menu_iniziale(_servizi_invii, update.effective_user.id))
    return ConversationHandler.END



def menu_utente_principale():
    righe = [
        [InlineKeyboardButton("📱 OFFERTE TECH", url=TECH_CHANNEL_URL)],
        [InlineKeyboardButton("🏠 OFFERTE CASA — 🚧 IN COSTRUZIONE", callback_data="casa_costruzione")],
    ]
    if COMMUNITY_URL:
        righe.append([InlineKeyboardButton("👥 COMMUNITY", url=COMMUNITY_URL)])
    else:
        righe.append([InlineKeyboardButton("👥 COMMUNITY", callback_data="community_info")])
    return InlineKeyboardMarkup(righe)


async def casa_in_costruzione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🏠 OFFERTE CASA\n\n"
        "🚧 Sezione in costruzione. Sarà disponibile prossimamente.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ TORNA AL MENU", callback_data="menu_utente")
        ]]),
    )


async def community_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "👥 COMMUNITY BESTPRICE24H\n\n"
        "Il collegamento alla Community non è ancora configurato nel bot.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ TORNA AL MENU", callback_data="menu_utente")
        ]]),
    )


async def torna_menu_utente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔥 BESTPRICE24H\n\n"
        "Trova le offerte Amazon selezionate ogni giorno da BestPrice24h 👇",
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
        reset_flusso(context)
        context.user_data.pop('canale_attivo', None)

        await update.message.reply_text(
            "🔥 AMAZON OFFERTE BOT\n\n"
            "🛠 Modalità amministratore\n\n"
            "Scegli il canale da gestire:",
            reply_markup=menu_canali.menu_iniziale(_servizi_invii, update.effective_user.id),
        )

        return ConversationHandler.END

    # =====================================================
    # UTENTE NORMALE
    # =====================================================

    testo = (
        "🔥 BENVENUTO SU BESTPRICE24H\n\n"
        "Trova le offerte Amazon selezionate ogni giorno da BestPrice24h.\n\n"
        "📱 Il canale Tech è già disponibile.\n"
        "🏠 Offerte Casa è in costruzione.\n"
        "👥 Puoi anche accedere alla Community.\n\n"
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

def estrai_coupon_pagina(soup):
    """Legge solo sezioni coupon esplicite; ignora prezzi e promozioni generiche."""
    selettori = ('#couponFeature', '#couponText', '#couponTextpctch',
                 '#couponTextpctch span', '[id^="couponText"]',
                 '#vpcButton', '.promoPriceBlockMessage')
    trovati = set()
    for selettore in selettori:
        for nodo in soup.select(selettore):
            # Non considerare promozioni nascoste/disabilitate o già scadute.
            if nodo.find_parent(attrs={'aria-hidden':'true'}) or nodo.get('aria-hidden') == 'true':
                continue
            if nodo.has_attr('hidden') or nodo.select_one('input[disabled]'):
                continue
            testo = ' '.join(nodo.stripped_strings).replace('\xa0',' ')
            basso = testo.lower()
            if not any(k in basso for k in ('coupon', 'buono')):
                continue
            if any(k in basso for k in ('scadut', 'non disponibile', 'fino a', 'fino al', 'prossimo acquisto', 'iscriviti', 'iscrizione', 'acquisto periodico', 'minimo', 'minima', 'almeno', 'solo per', 'se acquisti', 'prima consegna', 'clienti selezionati')):
                continue
            # Solo importi vicini alla parola coupon/buono, per non confondere soglie minime.
            espressioni = (
                r'(?:coupon|buono)(?:\s+(?:di|del|da|sconto|risparmio|un|il))*\s*[:=]?\s*(\d+(?:[.,]\d{1,2})?)\s*(%|€|eur(?:o)?)',
                r'(\d+(?:[.,]\d{1,2})?)\s*(%|€|eur(?:o)?)\s*(?:di\s+)?(?:sconto\s+)?(?:con\s+(?:un\s+|il\s+)?)?(?:coupon|buono)',
                r'(?:applica|seleziona|risparmia)\s+(?:il\s+coupon\s+(?:del\s+)?)?(\d+(?:[.,]\d{1,2})?)\s*(%|€|eur(?:o)?)',
            )
            for pattern in espressioni:
                for numero, unita in re.findall(pattern, basso, flags=re.IGNORECASE):
                    valore = float(numero.replace(',', '.'))
                    if valore <= 0 or (unita == '%' and valore > 100):
                        continue
                    valore_testo = (str(int(valore)) if valore.is_integer() else f'{valore:.2f}'.replace('.', ','))
                    trovati.add(valore_testo + ('%' if unita == '%' else ' €'))
    # Importi discordanti: non attribuire al prodotto un coupon incerto.
    return next(iter(trovati)) if len(trovati) == 1 else None


def frase_coupon(coupon):
    if not coupon:
        return ''
    if not re.fullmatch(r'\d+(?:[.,]\d{1,2})?(?:%| €)', str(coupon)):
        return ''
    preposizione = 'del' if str(coupon).endswith('%') else 'da'
    return f'✅ Applica il coupon {preposizione} {coupon} visibile nella pagina Amazon.'


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
            timeout=10,
            allow_redirects=True,
        )

        if risposta.status_code != 200:
            print(f"Amazon pagina HTTP {risposta.status_code}: {risposta.url}")
            return None
        if not risposta.content:
            print(f"Amazon pagina vuota: {risposta.url}")
            return None
        if any(m in risposta.text.lower() for m in ('captcha', 'enter the characters you see below', 'robot check')):
            print(f"Amazon pagina di verifica anti-bot: {risposta.url}")
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

        if not immagine:
            og = soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
            if og:
                immagine = og.get('content')

        if not titolo and not prezzo:
            print(f"Amazon pagina HTTP 200 ma senza titolo e prezzo: {risposta.url}")
            return None

        categorie_pagina = [el.get_text(" ", strip=True) for el in soup.select(
            "#wayfinding-breadcrumbs_feature_div a, #wayfinding-breadcrumbs_container a"
        ) if el.get_text(" ", strip=True)]
        categoria_pagina = categorie_pagina[-1] if categorie_pagina else None
        for voce in reversed(categorie_pagina):
            if any(parola in voce.lower() for parola in ('smartphone', 'cellulari')):
                categoria_pagina = 'smartphone'
                break
        return {
            "nome": titolo,
            "prezzo": prezzo,
            "vecchio_prezzo": vecchio_prezzo,
            "immagine": immagine,
            "categoria": categoria_pagina,
            "coupon": estrai_coupon_pagina(soup),
            "disponibile": not bool(re.search(r'non (?:è )?disponibile|attualmente non disponibile|temporaneamente esaurito', (soup.select_one('#availability').get_text(' ',strip=True) if soup.select_one('#availability') else ''),flags=re.IGNORECASE)),
        }

    except requests.Timeout as errore:
        print(f"Amazon timeout HTTP (10s): {type(errore).__name__}: {errore}")
        return None
    except requests.RequestException as errore:
        print(f"Amazon errore HTTP: {type(errore).__name__}: {errore}")
        return None

    except Exception as errore:

        print(f"Errore lettura Amazon: {type(errore).__name__}: {errore}")

        return None


def estrai_asin_da_link(link):
    testo = str(link or "").strip()

    # Link Amazon classici: /dp/ASIN, /gp/product/ASIN, /gp/aw/d/ASIN.
    corrispondenza = re.search(
        r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)",
        testo,
        flags=re.IGNORECASE,
    )
    if corrispondenza:
        return corrispondenza.group(1).upper()

    # Nuovo formato condiviso da Amazon: https://link.amazon/ASIN
    corrispondenza = re.search(
        r"https?://(?:www\.)?link\.amazon/([A-Z0-9]{10})(?:[/?#]|$)",
        testo,
        flags=re.IGNORECASE,
    )
    return corrispondenza.group(1).upper() if corrispondenza else None




def risolvi_asin_da_link(link):
    """Estrae l'ASIN da link Amazon classici, brevi e link.amazon."""
    asin = estrai_asin_da_link(link)
    if asin:
        return asin
    try:
        with requests.get(
            link,
            timeout=10,
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
    # Compatibilita' con chiamanti esistenti: lettura esclusivamente pagina.
    return leggi_prodotto_amazon(f'https://www.amazon.it/dp/{asin}')



# Adattatori espliciti: i moduli non importano il coordinatore.
import invio_singolo
import invio_multiplo
import repost
import canali
import menu_canali
import invio_automatico
import rubrica
import quiz_multicanale
import aggiunta_canale
from database import ArchivioCanali
_servizi_invii = sys.modules[__name__]

ARCHIVIO = ArchivioCanali(DB_PATH)
FILTRI = filtri_canale.ArchivioFiltri(DB_PATH)
CANALI = canali.carica_canali(os.environ)
for _key, _nome, _chat, _admins in ARCHIVIO.canali_salvati():
    if _key in CANALI:
        if CANALI[_key].chat_id != _chat:
            raise ValueError('Conflitto fra canali salvati e configurazione ambiente: ' + _key)
        continue
    CANALI[_key] = canali.nuovo_canale(CANALI, _key, _nome, _chat, _admins)

# Identico al legacy: le due funzioni get_items/search_items sono disabilitate.
SORGENTE_RICERCA_ATTIVA = False

def categorie_consentite_canale(key):
    if key not in CANALI:
        raise ValueError('Canale non configurato.')
    return TECH_CATEGORIE if key == 'tech' else CASA_CATEGORIE if key == 'casa' else set(AUTO_CATEGORIE)

async def gestisci_automatico_v2(update, context):
    return await invio_automatico.gestisci(_servizi_invii, update, context)

def input_automatico_v2(function):
    async def callback(update, context):
        return await invio_automatico.ricevi(_servizi_invii, update, context, function)
    return callback

async def gestisci_rubrica_v2(update, context):
    return await rubrica.gestisci(_servizi_invii, update, context)

async def ricevi_rubrica_v2(update, context):
    return await rubrica.ricevi(_servizi_invii, update, context)

async def ricevi_nuovo_canale_v2(update, context):
    return await aggiunta_canale.ricevi(_servizi_invii, update, context)

async def interazioni_pubbliche_rubrica(update, context):
    q = update.callback_query
    if q and (q.data or '').startswith(('oro_segno:', 'quiz_r:')):
        return await gestisci_oroscopi(update, context)


def reset_flusso(context):
    canali.reset_flusso(context)

def canale_corrente(context):
    return canali.selezionato(context, CANALI)

async def richiedi_canale(update, context):
    channel = canali.selezionato(context, CANALI, update.effective_user.id)
    if channel is None:
        await update.effective_message.reply_text('Seleziona prima il canale da gestire.', reply_markup=menu_canali.menu_iniziale(_servizi_invii, update.effective_user.id))
        return False
    return True

def tag_canale(key):
    override = ARCHIVIO.impostazioni(CANALI[key].chat_id)['tag'] if key else ''
    return override or (os.environ.get('AMAZON_PARTNER_TAG') or os.environ.get('AMAZON_ASSOCIATE_TAG') or '').strip()

async def gestisci_menu_v2(update, context):
    return await menu_canali.gestisci(_servizi_invii, update, context)

async def ricevi_impostazione_v2(update, context):
    return await menu_canali.ricevi_impostazione(_servizi_invii, update, context)

async def proteggi_menu_v2(update, context):
    channel = canali.selezionato(context, CANALI, update.effective_user.id if update.effective_user else None)
    if update.message and not (update.message.text or '').startswith('/') and context.user_data.get('prog_id'):
        post = ARCHIVIO.dettaglio('programmazioni', channel.chat_id, context.user_data['prog_id']) if channel else None
        if not post or post['stato'] != 'attesa':
            await update.message.reply_text('Post non più modificabile nel canale corrente. Riapri Programmati e code.')
            raise ApplicationHandlerStop
    q = update.callback_query
    if not q or not autorizzato(update):
        return
    data = q.data or ''
    if data.startswith('v2r:global:'):
        return
    if data.startswith(('oro_segno:', 'quiz_r:')) or data == 'offer_price_unavailable':
        return
    if channel and (data == 'programmati' or data == 'prog_esci'):
        return
    if channel and data.startswith('prog_') and not data.startswith('prog_giorno_'):
        post = ARCHIVIO.dettaglio('programmazioni', channel.chat_id, context.user_data.get('prog_id', -1))
        if post and post['stato'] == 'attesa':
            return
    if data.startswith('v2_') or data == 'settings_menu' or data.startswith(('diag_logs_', 'diag_export_')):
        return
    channel = canali.selezionato(context, CANALI, update.effective_user.id)
    if data.startswith(('v2c:', 'v2a:', 'v2r:')):
        if channel and data.split(':', 2)[1] == channel.chiave:
            return
    elif channel and (data in {'nuova','rapido','repost','publish_menu','menu_admin','annulla',
                               'dati_ok','dati_manual','dati_riprova','foto_aggiungi','foto_salta',
                               'pubblica','programma','cambia_template','conferma_orario_vicino','cambia_orario'}
                      or re.fullmatch(r'prog_giorno_[012]|tpl_(pulito|aggressivo|tech)|multi_(timing|personalizzato|min_(10|20|30|40|60)|avvia|annulla)', data)):
        return
    await q.answer('Schermata precedente o canale diverso. Usa /start oppure il menu corrente.', show_alert=True)
    raise ApplicationHandlerStop



# =========================================================
# NUOVA OFFERTA
# =========================================================

async def nuova_da_comando(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.nuova_da_comando(_servizi_invii, update, context)


async def nuova_da_pulsante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.nuova_da_pulsante(_servizi_invii, update, context)


# =========================================================
# RICEZIONE LINK
# =========================================================

async def ricevi_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.ricevi_link(_servizi_invii, update, context)


# =========================================================
# CONFERMA DATI AUTOMATICI
# =========================================================

async def conferma_dati_automatici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.conferma_dati_automatici(_servizi_invii, update, context)


# =========================================================
# INSERIMENTO MANUALE
# =========================================================

async def ricevi_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.ricevi_nome(_servizi_invii, update, context)


async def ricevi_prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.ricevi_prezzo(_servizi_invii, update, context)


async def ricevi_vecchio_prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.ricevi_vecchio_prezzo(_servizi_invii, update, context)


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

# Invio multiplo: usa la coda persistente già visibile in Programmati.
MULTIPLO_LOCK = asyncio.Lock()


def prodotto_inviato_ultime_24h(asin, destinazione):
    """Confronta l'ASIN, non l'URL/tag. Conta solo pubblicazioni effettive."""
    if not asin:
        return False
    adesso = datetime.now(timezone.utc)
    limite = adesso - timedelta(hours=24)
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        for tabella, campo_data in (('recap_offerte', 'pubblicata_il'), ('invii_automatici', 'creato_il')):
            righe = db.execute(
                f"SELECT {campo_data}, asin, link FROM {tabella} "
                "WHERE CAST(telegram_chat_id AS TEXT)=? "
                "AND COALESCE(stato,'pubblicata') IN ('pubblicata','terminata') "
                "AND (asin=? OR asin IS NULL OR asin='')",
                (str(destinazione), asin),
            ).fetchall()
            for data_testo, asin_storico, link in righe:
                data = _data_sqlite(data_testo)
                if data and limite <= data.astimezone(timezone.utc) <= adesso:
                    if (asin_storico or estrai_asin_da_link(link)) == asin:
                        return True
    return False


def filtra_duplicati_recenti_multiplo(draft):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return invio_multiplo.filtra_duplicati_recenti_multiplo(_servizi_invii, draft)


def intervallo_multiplo(utente, valore=None, canale=None):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return invio_multiplo.intervallo_multiplo(_servizi_invii, utente, valore, canale)


def tastiera_annulla_elaborazione():
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return invio_multiplo.tastiera_annulla_elaborazione(_servizi_invii)


def tastiera_multiplo(draft):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return invio_multiplo.tastiera_multiplo(_servizi_invii, draft)


def link_affiliato_multiplo(link, asin, canale=None):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return invio_multiplo.link_affiliato_multiplo(_servizi_invii, link, asin, canale)


def piano_multiplo(prodotti, minuti, destinazione, salva=False, origine='multiplo'):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return invio_multiplo.piano_multiplo(_servizi_invii, prodotti, minuti, destinazione, salva, origine)


def arma_avvio_multiplo(messaggio, context, draft):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return invio_multiplo.arma_avvio_multiplo(_servizi_invii, messaggio, context, draft)


async def avvio_multiplo_differito(messaggio, context, draft, token):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return await invio_multiplo.avvio_multiplo_differito(_servizi_invii, messaggio, context, draft, token)


async def avvia_lotto_multiplo(messaggio, context, draft, automatico=False):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return await invio_multiplo.avvia_lotto_multiplo(_servizi_invii, messaggio, context, draft, automatico)


async def riepilogo_multiplo(messaggio, draft, context=None):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return await invio_multiplo.riepilogo_multiplo(_servizi_invii, messaggio, draft, context)


def asin_in_programmati(destinazione):
    """Callback compatibile; implementazione in repost.py."""
    return repost.asin_in_programmati(_servizi_invii, destinazione)


def candidati_repost(canale, quantita):
    """Callback compatibile; implementazione in repost.py."""
    return repost.candidati_repost(_servizi_invii, canale, quantita)


async def leggi_offerta_repost(link, storico, callback=None):
    """Callback compatibile; implementazione in repost.py."""
    return await repost.leggi_offerta_repost(_servizi_invii, link, storico, callback)


async def repost_da_pulsante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in repost.py."""
    return await repost.repost_da_pulsante(_servizi_invii, update, context)


async def rapido_da_comando(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return await invio_multiplo.rapido_da_comando(_servizi_invii, update, context)


async def rapido_da_pulsante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return await invio_multiplo.rapido_da_pulsante(_servizi_invii, update, context)


async def prepara_repost(messaggio, context, draft):
    """Callback compatibile; implementazione in repost.py."""
    return await repost.prepara_repost(_servizi_invii, messaggio, context, draft)


def offerta_attuale_rilevata(dati):
    """Callback compatibile; implementazione in repost.py."""
    return repost.offerta_attuale_rilevata(_servizi_invii, dati)


def tastiera_confronto_cronologia(pronto=False):
    bottoni = []
    if pronto:
        bottoni += [[InlineKeyboardButton('📤 Pubblica ora',callback_data='hist_pubblica')],
                    [InlineKeyboardButton('📅 Programma',callback_data='hist_programma')]]
    bottoni.append([InlineKeyboardButton('❌ Annulla',callback_data='hist_annulla')])
    return InlineKeyboardMarkup(bottoni)


async def mostra_confronto_cronologia(messaggio, context, draft):
    if context.user_data.get('multiplo') is not draft:
        return
    # Il singolo ricontrollo non deve mai armare il timer dei lotti.
    draft.pop('timer_token',None)
    if not draft['pronti']:
        testo='⚠️ Ricontrollo non riuscito. Nessun invio programmato.\n\n'+'\n'.join(draft['scartati'])
        await messaggio.reply_text(testo[:4000],reply_markup=tastiera_confronto_cronologia())
        return
    prodotto = draft['pronti'][0]
    vecchio = numero_da_prezzo(prodotto.get('vecchio_prezzo'))
    prezzo_esposto = numero_da_prezzo(prodotto['prezzo'])
    _,_,prezzo_finale,coupon_calcolabile,sconto_totale = importi_template(prodotto)
    prezzo_attuale = float(prezzo_finale) if prezzo_finale is not None else prezzo_esposto
    ultima = numero_da_prezzo(draft.get('prezzo_storico'))
    def euro(valore):
        return (f'{valore:.2f}'.replace('.',',')+' €') if valore is not None else 'non disponibile'
    righe=['🔄 <b>CONFRONTO PREZZI</b>',html.escape(prodotto['nome']),
           '', '🕒 Prezzo nell’ultima pubblicazione: '+euro(ultima),
           '🏷 Prezzo precedente/listino rilevato ora: '+euro(vecchio),
           '💰 Prezzo attuale: <b>'+euro(prezzo_attuale)+'</b>']
    if coupon_calcolabile:
        righe.append('🏷 Prezzo esposto prima del coupon: '+euro(prezzo_esposto))
    sconto=sconto_totale
    if sconto is not None and sconto > 0:
        righe.append(f'💥 Sconto attuale: <b>-{sconto}%</b>')
    else:
        righe.append('💥 Nessuna riduzione sul prezzo precedente rilevata.')
    if ultima is not None and prezzo_attuale is not None:
        differenza=prezzo_attuale-ultima
        righe.append('📊 Rispetto all’ultimo post: '+('invariato' if abs(differenza)<0.005 else ('+' if differenza>0 else '−')+euro(abs(differenza))))
    coupon=frase_coupon(prodotto.get('coupon'))
    righe.append(html.escape(coupon) if coupon else '🎟 Nessun coupon rilevato.')
    righe += ['', 'ℹ️ Il prezzo attuale include il coupon quando calcolabile; attivalo nella pagina Amazon.',
              'Scegli se pubblicare, programmare o annullare. Nessun avvio automatico.']
    await messaggio.reply_text('\n'.join(righe),parse_mode='HTML')
    corpo=crea_messaggio_programmato(prodotto['nome'],prodotto['prezzo'],prodotto['vecchio_prezzo'],'pulito',prodotto.get('categoria'),prodotto.get('coupon'))
    anteprima=crea_caption_con_link(corpo,prodotto['link'])
    tastiera=tastiera_confronto_cronologia(True)
    if prodotto.get('foto_file_id'):
        try:
            await messaggio.reply_photo(photo=prodotto['foto_file_id'],caption=anteprima,parse_mode='HTML',reply_markup=tastiera)
            return
        except Exception:
            pass
    await messaggio.reply_text(anteprima,parse_mode='HTML',reply_markup=tastiera)


async def decidi_ricontrollo_cronologia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    q=update.callback_query
    await q.answer()
    draft=context.user_data.get('multiplo')
    if not draft or draft.get('tipo') != 'singolo_cronologia':
        await q.message.reply_text('Ricontrollo non più disponibile. Apri il prodotto dalla cronologia.')
        return ConversationHandler.END
    if q.data == 'hist_annulla':
        context.user_data.pop('multiplo',None)
        await q.message.reply_text('❌ Ripubblicazione annullata. Nessun invio aggiunto.')
        return ConversationHandler.END
    if draft.get('elaborazione') or not draft['pronti']:
        await q.message.reply_text('Il prodotto non è ancora pronto per la pubblicazione.')
        return RAPIDO
    prodotto=draft['pronti'][0]
    destinazione=_chat_id_per_canale(draft['canale'])
    if prodotto_inviato_ultime_24h(prodotto['asin'],destinazione):
        await q.message.reply_text('⏳ Prodotto già pubblicato nelle ultime 24 ore nello stesso canale. Puoi consultare il confronto, ma al momento non ripubblicarlo.')
        return RAPIDO
    if prodotto['asin'] in await asyncio.to_thread(asin_in_programmati,destinazione):
        await q.message.reply_text('⏳ Il prodotto è già presente in Programmati. Nessun doppione aggiunto.')
        return RAPIDO
    corpo=crea_messaggio_programmato(prodotto['nome'],prodotto['prezzo'],prodotto['vecchio_prezzo'],'pulito',prodotto.get('categoria'),prodotto.get('coupon'))
    if q.data == 'hist_programma':
        context.user_data.update(prodotto)
        context.user_data['messaggio']=corpo
        context.user_data['template']='pulito'
        context.user_data['telegram_chat_id']=destinazione
        context.user_data['origine_programmazione']='cronologia'
        context.user_data.pop('multiplo',None)
        await q.message.reply_text('📅 Scegli il giorno, poi inserisci l’orario. Si applica la fascia manuale/multiplo.',reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('📅 Oggi',callback_data='prog_giorno_0'),InlineKeyboardButton('📅 Domani',callback_data='prog_giorno_1')],
            [InlineKeyboardButton('📅 Tra 2 giorni',callback_data='prog_giorno_2')],
            [InlineKeyboardButton('❌ Annulla',callback_data='annulla')]]))
        return CONFERMA
    # Accoda una sola volta, con le normali regole di fascia/spazi e controllo finale 24h.
    async with MULTIPLO_LOCK:
        if context.user_data.get('multiplo') is not draft:
            return ConversationHandler.END
        ora=datetime.now(ROMA_TZ)+timedelta(minutes=minuti_rimanenti_prima_del_prossimo_invio())
        pid,quando=salva_programmazione(prodotto['nome'],corpo,prodotto['link'],prodotto['prezzo'],ora,destinazione,origine='cronologia')
        salva_foto_programmazione(pid,prodotto.get('foto_file_id'))
        context.user_data.pop('multiplo',None)
    await q.message.reply_text(f'✅ Ripubblicazione confermata. Invio previsto: {quando:%d/%m/%Y %H:%M}, ora italiana.\nVisibile in Programmati; se lo spazio è libero parte entro circa 30 secondi.')
    return ConversationHandler.END


async def prepara_lotto_multiplo(messaggio, context, draft, links, seconda_passata=False):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return await invio_multiplo.prepara_lotto_multiplo(_servizi_invii, messaggio, context, draft, links, seconda_passata)


async def ricevi_rapido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return await invio_multiplo.ricevi_rapido(_servizi_invii, update, context)


async def gestisci_multiplo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_multiplo.py."""
    return await invio_multiplo.gestisci_multiplo(_servizi_invii, update, context)



# =========================================================
# RICEZIONE ORA PROGRAMMAZIONE
# =========================================================

@navigazione_coordinatore
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
        data_locale, context.user_data["telegram_chat_id"]
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
        origine=context.user_data.get("origine_programmazione","manuale"),
    )

    salva_foto_programmazione(
        programmazione_id,
        context.user_data.get("foto_file_id"),
    )

    da_reinvio = context.user_data.get("programmazione_da_reinvio", False)
    reset_flusso(context)

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
        await invia_lista_programmati(update.message, destinazione=canale_corrente(context).chat_id)

    return ConversationHandler.END



# =========================================================
# CONTROLLO SLOT PROGRAMMAZIONE
# =========================================================

DISTANZA_MINIMA_MINUTI = 29


def programmazioni_del_giorno(data_locale, destinazione=CHANNEL_ID):

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
          AND CAST(COALESCE(telegram_chat_id, ?) AS TEXT)=?
          AND invio_previsto >= ?
          AND invio_previsto < ?
        ORDER BY invio_previsto ASC
    """, (
        str(CHANNEL_ID), str(destinazione),
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
    destinazione=CHANNEL_ID,
):

    eventi = programmazioni_del_giorno(
        data_locale.date(), destinazione
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
    destinazione=CHANNEL_ID,
):

    eventi = programmazioni_del_giorno(
        data_giorno, destinazione
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
            candidato, destinazione
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
            candidato, destinazione
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

@navigazione_coordinatore
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
        origine=context.user_data.get("origine_programmazione","manuale"),
    )

    salva_foto_programmazione(
        programmazione_id,
        context.user_data.get("foto_file_id"),
    )

    da_reinvio = context.user_data.get("programmazione_da_reinvio", False)
    reset_flusso(context)

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
        await invia_lista_programmati(query.message, destinazione=canale_corrente(context).chat_id)

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
            stato,
            telegram_chat_id
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
        "telegram_chat_id": riga[10],
    }


def crea_messaggio_programmato(nome, prezzo, vecchio, template, categoria=None, coupon=None):
    # Il parametro storico template resta compatibile con database e vecchi callback.
    return corpo_pulito_post(nome,prezzo,vecchio,categoria,coupon)


def aggiorna_messaggio_programmato(
    programmazione_id,
):

    post = leggi_programmato(
        programmazione_id
    )

    if not post:
        return False

    coupon_salvato = re.search(r"✅ Applica il coupon (?:del|da) (\d+(?:[.,]\d{1,2})?(?:%| €)) visibile", post.get("messaggio", ""))
    categoria_salvata = re.search(r"Categoria:\s*(#[\w]+)", post.get("messaggio", ""))
    messaggio = crea_messaggio_programmato(
        post["nome"],
        post["prezzo"],
        post["vecchio_prezzo"],
        post["template"],
        categoria_salvata.group(1) if categoria_salvata else None,
        coupon_salvato.group(1) if coupon_salvato else None,
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
    destinazione=CHANNEL_ID,
):

    riallinea_programmati_fascia()
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    cur.execute("""
        SELECT
            id,
            nome,
            prezzo,
            invio_previsto
        FROM programmazioni
        WHERE stato = 'attesa' AND CAST(COALESCE(telegram_chat_id, ?) AS TEXT)=?
        ORDER BY invio_previsto ASC
        LIMIT 100
    """, (str(CHANNEL_ID),str(destinazione)))

    righe_db = cur.fetchall()

    db.close()

    giorni_lista = {datetime.now(ROMA_TZ).date()}
    for _, _, _, previsto in righe_db:
        dt = data_programmata_locale(previsto)
        if dt:
            giorni_lista.add(dt.date())
    eventi_caffe = []
    for canale in (destinazione,):
        eventi_caffe.extend(descrizione_pause_programmate(canale, giorni_lista))
    # Elenco cronologico con indicazione del canale per i post speciali.
    if not righe_db and not eventi_caffe:

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

    elementi = []
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

        elementi.append((data_locale or datetime.now(ROMA_TZ),
            f"#{programmazione_id} • {quando}\n📦 {nome} — {prezzo} €\n"))
    for canale in (destinazione,):
        nome_canale = 'CASA' if str(canale) == str(CASA_CHANNEL_ID) else 'TECH'
        for inizio, descrizione in descrizione_pause_programmate(canale, giorni_lista):
            elementi.append((inizio, f"{descrizione} · {nome_canale}\n"))
    righe.extend(testo for _, testo in sorted(elementi, key=lambda r: r[0]))

    if righe_db:
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


@navigazione_coordinatore
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

    context.user_data.pop('multiplo', None)

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

    await invia_lista_programmati(messaggio, destinazione=canale_corrente(context).chat_id)

    return PROG_SELEZIONE


@navigazione_coordinatore
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

    if not ARCHIVIO.dettaglio('programmazioni', canale_corrente(context).chat_id, programmazione_id):
        post = None
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
        f"📅 POST PROGRAMMATO #{post['id']} — {next((c.nome for c in CANALI.values() if c.chat_id == str(post['telegram_chat_id'])), post['telegram_chat_id'])}\n"
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
            *tastiera_offerta_automatica(post["link"]).inline_keyboard,
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


@navigazione_coordinatore
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

        await invia_lista_programmati(query.message, destinazione=canale_corrente(context).chat_id)

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

        await invia_lista_programmati(query.message, destinazione=canale_corrente(context).chat_id)

        return PROG_SELEZIONE

    return PROG_GESTIONE


@navigazione_coordinatore
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


@navigazione_coordinatore
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


@navigazione_coordinatore
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


@navigazione_coordinatore
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


@navigazione_coordinatore
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


@navigazione_coordinatore
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


@navigazione_coordinatore
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
        data_locale, canale_corrente(context).chat_id
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



@navigazione_coordinatore
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


@navigazione_coordinatore
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


@navigazione_coordinatore
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
    dati=context.user_data
    return corpo_pulito_post(dati['nome'],dati['prezzo'],dati.get('vecchio_prezzo','NO'),dati.get('categoria'),dati.get('coupon'))


async def prova_foto_automatica_o_chiedi(update, context):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.prova_foto_automatica_o_chiedi(_servizi_invii, update, context)


async def chiedi_immagine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.chiedi_immagine(_servizi_invii, update, context)


async def scelta_immagine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.scelta_immagine(_servizi_invii, update, context)


async def ricevi_immagine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.ricevi_immagine(_servizi_invii, update, context)


# =========================================================
# ANTEPRIMA
# =========================================================

async def mostra_anteprima(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.mostra_anteprima(_servizi_invii, update, context)


# =========================================================
# CONTROLLO DISTANZA INVII MANUALI
# =========================================================

def minuti_rimanenti_prima_del_prossimo_invio(destinazione=CHANNEL_ID):
    adesso = datetime.now(timezone.utc)
    with sqlite3.connect(DB_PATH) as db:
        dates = db.execute("SELECT pubblicata_il FROM recap_offerte WHERE CAST(telegram_chat_id AS TEXT)=?", (str(destinazione),)).fetchall()
    times = [_data_sqlite(row[0]) for row in dates if _data_sqlite(row[0])]
    if not times:
        return 0
    return max(0, int((DISTANZA_MINIMA_MINUTI * 60 - (adesso-max(times)).total_seconds() + 59) // 60))


# =========================================================
# CONFERMA / PUBBLICAZIONE
# =========================================================

async def conferma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback compatibile; implementazione in invio_singolo.py."""
    return await invio_singolo.conferma(_servizi_invii, update, context)


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


def preferenza_pagina_cronologia(utente, valore=None):
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute("CREATE TABLE IF NOT EXISTS preferenze_cronologia(utente TEXT PRIMARY KEY,per_pagina INTEGER NOT NULL)")
        if valore in (5,10,50,100):
            db.execute("INSERT OR REPLACE INTO preferenze_cronologia VALUES (?,?)",(str(utente),valore))
        riga = db.execute("SELECT per_pagina FROM preferenze_cronologia WHERE utente=?",(str(utente),)).fetchone()
    return riga[0] if riga and riga[0] in (5,10,50,100) else 5


def righe_cronologia(filtro='tutti', periodo='7', ricerca=''):
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.row_factory = sqlite3.Row
        righe = [dict(r) for r in db.execute("SELECT id,nome,link,COALESCE(prezzo_finale_pubblicato,prezzo) AS prezzo,vecchio_prezzo,pubblicata_il,asin,telegram_chat_id,stato,foto_file_id,origine FROM recap_offerte ORDER BY id DESC").fetchall()]
    ora = datetime.now(ROMA_TZ)
    limite = ora.replace(hour=0,minute=0,second=0,microsecond=0) if periodo == 'oggi' else ora-timedelta(days=int(periodo)) if periodo in ('7','30') else None
    # Sort by parsed timestamps to support both old UTC and Italian-time records.
    righe.sort(key=lambda r:(_data_sqlite(r['pubblicata_il']) or datetime.min.replace(tzinfo=timezone.utc),r['id']),reverse=True)
    unici = []
    visti = set()
    for riga in righe:
        data = _data_sqlite(riga['pubblicata_il'])
        if not data or (limite and data < limite):
            continue
        canale = 'casa' if str(riga['telegram_chat_id']) == str(CASA_CHANNEL_ID) else 'tech'
        if filtro in ('tech','casa') and canale != filtro:
            continue
        asin = riga['asin'] or estrai_asin_da_link(riga['link'])
        identita = (canale,asin or str(riga['link']).split('?')[0] or str(riga['nome']).casefold())
        if identita in visti:
            continue
        visti.add(identita)
        if ricerca and ricerca.casefold() not in str(riga['nome']).casefold():
            continue
        riga['canale'] = canale
        unici.append(riga)
    return unici


async def pulisci_pannelli_cronologia(query, context):
    pannelli = context.user_data.pop('cronologia_pannelli',[])
    for chat_id, message_id in pannelli:
        if chat_id == query.message.chat_id and message_id == query.message.message_id:
            continue
        try:
            await context.bot.delete_message(chat_id=chat_id,message_id=message_id)
        except Exception:
            pass


async def render_cronologia(query, testo, tastiera, foto=None):
    if foto:
        try:
            nuovo = await query.message.reply_photo(photo=foto,caption=testo,parse_mode='HTML',reply_markup=tastiera)
        except Exception:
            nuovo = await query.message.reply_text(testo,parse_mode='HTML',reply_markup=tastiera)
        try:
            await query.message.delete()
        except Exception:
            pass
        return nuovo
    if getattr(query.message,'photo',None):
        nuovo = await query.message.reply_text(testo,parse_mode='HTML',reply_markup=tastiera)
        try:
            await query.message.delete()
        except Exception:
            pass
        return nuovo
    try:
        return await query.edit_message_text(testo,parse_mode='HTML',reply_markup=tastiera)
    except Exception as exc:
        if 'message is not modified' in str(exc).lower():
            return query.message
        raise


async def mostra_archivio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    q = update.callback_query
    await q.answer()
    azione = q.data
    pagina = 0
    if azione.startswith('archive_filter_'):
        filtro = azione.replace('archive_filter_','',1)
        context.user_data['archivio_filtro'] = filtro if filtro in ('tech','casa') else 'tutti'
    elif azione.startswith('archive_period_'):
        context.user_data['archivio_periodo'] = azione.replace('archive_period_','',1)
    elif azione.startswith('archive_size_') and azione != 'archive_size_menu':
        preferenza_pagina_cronologia(update.effective_user.id,int(azione.rsplit('_',1)[1]))
    elif azione == 'archive_clear_search':
        context.user_data.pop('archivio_ricerca',None)
    elif azione.startswith('archive_page_'):
        pagina = int(azione.rsplit('_',1)[1])
    filtro = context.user_data.get('archivio_filtro','tutti')
    if filtro not in ('tech','casa'):
        filtro = 'tutti'
    periodo = context.user_data.get('archivio_periodo','7')
    if periodo not in ('oggi','7','30','tutto'):
        periodo = '7'
    ricerca = context.user_data.get('archivio_ricerca','')
    per_pagina = preferenza_pagina_cronologia(update.effective_user.id)
    righe = righe_cronologia(filtro,periodo,ricerca)
    totale_pagine = max(1,(len(righe)+per_pagina-1)//per_pagina)
    pagina = min(max(0,pagina),totale_pagine-1)
    context.user_data['archivio_pagina'] = pagina
    visibili = righe[pagina*per_pagina:(pagina+1)*per_pagina]
    periodo_testo = {'oggi':'Oggi','7':'Ultimi 7 giorni','30':'Ultimi 30 giorni','tutto':'Tutto lo storico'}[periodo]
    testo = f"📚 <b>CRONOLOGIA — {filtro.upper()}</b>\n{periodo_testo} · {len(righe)} prodotti\nPagina {pagina+1}/{totale_pagine} · {per_pagina} per pagina\n\nPrezzi all’ultima pubblicazione, non verificati adesso.\nTocca un prodotto per aprire la scheda."
    if ricerca:
        testo += '\n🔎 ' + html.escape(ricerca)
    if not visibili:
        testo += '\n\nNessun prodotto trovato.'
    controlli = [
        [InlineKeyboardButton(('✅ ' if filtro==x else '')+label,callback_data='archive_filter_'+x) for x,label in [('tech','📱 Tech'),('casa','🏠 Casa'),('tutti','📋 Tutti')]],
        [InlineKeyboardButton('🔎 Cerca prodotto',callback_data='archive_search'),InlineKeyboardButton('📆 Periodo',callback_data='archive_period_menu')],
        [InlineKeyboardButton(f'🔢 Prodotti per pagina: {per_pagina}',callback_data='archive_size_menu')],
    ]
    if ricerca:
        controlli.append([InlineKeyboardButton('✖️ Cancella ricerca',callback_data='archive_clear_search')])
    nav=[]
    if pagina>0:
        nav.append(InlineKeyboardButton('⬅️ Precedente',callback_data=f'archive_page_{pagina-1}'))
    if pagina+1<totale_pagine:
        nav.append(InlineKeyboardButton('Successiva ➡️',callback_data=f'archive_page_{pagina+1}'))
    if nav:
        controlli.append(nav)
    controlli.append([InlineKeyboardButton('⬅️ Menu principale',callback_data='menu_admin')])
    bottoni=[]
    for r in visibili:
        breve=accorcia_nome_articolo(r['nome'])[:38]
        data=_data_sqlite(r['pubblicata_il']).astimezone(ROMA_TZ)
        prezzo=str(r['prezzo'] or '—').replace('€','').strip()
        bottoni.append([InlineKeyboardButton(f"📦 {breve} · {prezzo} € · {data:%d/%m %H:%M}",callback_data=f"archive_view_{r['id']}")])
    await pulisci_pannelli_cronologia(q,context)
    # 100 products remain one page, split into 2 panels of 50 to avoid oversized keyboards.
    primo=await render_cronologia(q,testo,InlineKeyboardMarkup(bottoni[:50]+controlli))
    pannelli=[(primo.chat_id,primo.message_id)]
    if len(bottoni)>50:
        secondo=await primo.reply_text('📚 Cronologia — prodotti 51–100 della stessa pagina',reply_markup=InlineKeyboardMarkup(bottoni[50:]))
        pannelli.append((secondo.chat_id,secondo.message_id))
    context.user_data['cronologia_pannelli']=pannelli


async def opzioni_cronologia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    q=update.callback_query
    await q.answer()
    if q.data=='archive_size_menu':
        testo='🔢 <b>Numero di prodotti da mostrare per pagina</b>\nLa scelta resta salvata. Con 100 prodotti la pagina è divisa in due blocchi da 50.'
        bottoni=[[InlineKeyboardButton(str(n),callback_data=f'archive_size_{n}') for n in (5,10,50,100)]]
    else:
        testo='📆 <b>Periodo della cronologia</b>\nLo storico completo resta conservato.'
        bottoni=[[InlineKeyboardButton(label,callback_data='archive_period_'+valore) for valore,label in [('oggi','Oggi'),('7','7 giorni'),('30','30 giorni'),('tutto','Tutto')]]]
    bottoni.append([InlineKeyboardButton('⬅️ Cronologia',callback_data='archive_page_0')])
    await pulisci_pannelli_cronologia(q,context)
    await render_cronologia(q,testo,InlineKeyboardMarkup(bottoni))


async def mostra_scheda_archivio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    q=update.callback_query
    await q.answer()
    pid=int(q.data.rsplit('_',1)[1])
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM recap_offerte WHERE id=?',(pid,)).fetchone()
    if not row:
        await q.message.reply_text('❌ Prodotto non trovato.')
        return
    r=dict(row)
    canale='Casa' if str(r.get('telegram_chat_id'))==str(CASA_CHANNEL_ID) else 'Tech'
    dati_salvati=dati_template_da_corpo(r.get('messaggio'),nome=r['nome'],prezzo=r.get('prezzo'),vecchio=r.get('vecchio_prezzo'),categoria=r.get('categoria'))
    # The stored body has the exposed base price; displayed history may have a separate final price.
    testo=(f"📚 Anteprima ricostruita — {canale}\nPubblicato: {_data_archivio(r['pubblicata_il'])}\nDati salvati, non ricontrollati adesso.\n\n"
           +crea_caption_con_link(corpo_pulito_post(dati_salvati['nome'],dati_salvati['prezzo'],dati_salvati.get('vecchio_prezzo'),dati_salvati.get('categoria'),dati_salvati.get('coupon')),r['link']))
    pagina=context.user_data.get('archivio_pagina',0)
    bottoni=InlineKeyboardMarkup([
        *tastiera_offerta_automatica(
            r['link'], asin=r.get('asin'),
            link_post=link_post_telegram(chat_id=r.get('telegram_chat_id'), message_id=r.get('telegram_message_id')),
        ).inline_keyboard,
        [InlineKeyboardButton('🔄 Ricontrolla e ripubblica',callback_data=f'archive_recheck_{pid}')],
        [InlineKeyboardButton('📜 Pubblicazioni precedenti',callback_data=f'archive_previous_{pid}_0')],
        [InlineKeyboardButton('⬅️ Torna alla lista',callback_data=f'archive_page_{pagina}')],
    ])
    await pulisci_pannelli_cronologia(q,context)
    await render_cronologia(q,testo,bottoni,foto=r.get('foto_file_id'))


async def precedenti_cronologia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    q=update.callback_query
    await q.answer()
    _,_,pid,pagina=q.data.split('_')
    pid,pagina=int(pid),int(pagina)
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory=sqlite3.Row
        prodotto=db.execute('SELECT asin,link,telegram_chat_id FROM recap_offerte WHERE id=?',(pid,)).fetchone()
        if not prodotto:
            await q.message.reply_text('❌ Prodotto non trovato.')
            return
        asin=prodotto['asin'] or estrai_asin_da_link(prodotto['link'])
        righe=db.execute("SELECT pubblicata_il,COALESCE(prezzo_finale_pubblicato,prezzo) AS prezzo FROM recap_offerte WHERE CAST(telegram_chat_id AS TEXT)=? AND ((?<>' ' AND asin=?) OR link=?) ORDER BY id DESC",(str(prodotto['telegram_chat_id']),asin or ' ',asin,prodotto['link'])).fetchall()
    per_pagina=15
    totale=max(1,(len(righe)+per_pagina-1)//per_pagina)
    pagina=min(max(0,pagina),totale-1)
    testo='📜 <b>PUBBLICAZIONI DEL PRODOTTO</b>\n\n'+'\n'.join(html.escape(f"{_data_archivio(r['pubblicata_il'])} · {str(r['prezzo']).replace('€','').strip()} €") for r in righe[pagina*per_pagina:(pagina+1)*per_pagina])
    bottoni=[]
    nav=[]
    if pagina:
        nav.append(InlineKeyboardButton('⬅️',callback_data=f'archive_previous_{pid}_{pagina-1}'))
    if pagina+1<totale:
        nav.append(InlineKeyboardButton('➡️',callback_data=f'archive_previous_{pid}_{pagina+1}'))
    if nav:
        bottoni.append(nav)
    bottoni.append([InlineKeyboardButton('⬅️ Prodotto',callback_data=f'archive_view_{pid}')])
    await render_cronologia(q,testo,InlineKeyboardMarkup(bottoni))


async def ricontrolla_da_cronologia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return ConversationHandler.END
    q=update.callback_query
    await q.answer()
    pid=int(q.data.rsplit('_',1)[1])
    with sqlite3.connect(DB_PATH) as db:
        row=db.execute('SELECT link,telegram_chat_id,asin,COALESCE(prezzo_finale_pubblicato,prezzo),pubblicata_il FROM recap_offerte WHERE id=?',(pid,)).fetchone()
    if not row:
        await q.message.reply_text('❌ Prodotto non trovato.')
        return ConversationHandler.END
    if not (os.environ.get('AMAZON_PARTNER_TAG') or os.environ.get('AMAZON_ASSOCIATE_TAG') or '').strip():
        await q.message.reply_text('⚠️ Imposta AMAZON_PARTNER_TAG nelle variabili Railway.')
        return ConversationHandler.END
    link,chat_id,asin,prezzo_storico,data_storica=row
    canale='casa' if str(chat_id)==str(CASA_CHANNEL_ID) else 'tech'
    context.user_data.pop('multiplo',None)
    draft={'tipo':'singolo_cronologia','prezzo_storico':prezzo_storico,'data_storica':data_storica,'canale':canale,'minuti':intervallo_multiplo(update.effective_user.id),'pronti':[],'scartati':[],'duplicati':0,'elaborazione':True,'richiesti':1,'candidati':1}
    context.user_data['multiplo']=draft
    attesa=await q.message.reply_text('🔄 Ricontrollo il prodotto: prezzi, disponibilità e coupon. Ti mostrerò confronto e anteprima; attenderò la tua decisione, senza avvio automatico.')
    context.application.create_task(prepara_lotto_multiplo(attesa,context,draft,['https://www.amazon.it/dp/'+asin if asin else link]),update=update)
    return RAPIDO


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
    context.user_data['archivio_ricerca']=ricerca
    # Create a normal callback target that opens the already-filtered results.
    await update.message.reply_text(f'🔎 Ricerca: {ricerca}',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('📚 Risultati',callback_data='archive_page_0')]]))
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
        *tastiera_offerta_automatica(draft["link"], asin=draft.get("asin")).inline_keyboard,
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

    draft = await _dati_reinvio(context)
    if not draft:
        await query.message.reply_text("❌ Offerta non trovata.")
        return

    messaggio = _messaggio_reinvio(draft)
    ora = datetime.now(ROMA_TZ)
    if prossimo_orario_manuale(ora) != ora:
        corpo = ('__RICERCA_HTML__' + messaggio) if draft.get('template') == 'automatico' else messaggio
        pid, quando = salva_programmazione(draft.get('nome'),corpo,draft['link'],draft.get('prezzo'),ora,CHANNEL_ID)
        salva_foto_programmazione(pid,draft.get('foto_file_id'))
        await query.message.reply_text(f"🌙 Fuori fascia: reinvio programmato per {quando:%d/%m/%Y %H:%M} (ora italiana).")
        return

    minuti_rimanenti = minuti_rimanenti_prima_del_prossimo_invio()
    if minuti_rimanenti > 0:
        await query.message.reply_text(
            f"⏳ Attendi ancora {minuti_rimanenti} minuto/i.\n\n"
            f"Tra un post e l'altro devono passare almeno {DISTANZA_MINIMA_MINUTI} minuti."
        )
        return

    messaggio_con_link = crea_caption_con_link(
        messaggio,
        draft["link"],
        messaggio_gia_html=draft.get("template") == "automatico",
    )
    bottoni = tastiera_offerta_automatica(draft["link"], asin=draft.get("asin"))

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

    await aggiorna_pulsanti_offerta(
        context.bot, messaggio_telegram, draft["link"],
        asin=draft.get("asin"), chat_id=CHANNEL_ID,
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

async def template_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await controlla_autorizzazione(update):
        return
    q=update.callback_query
    await q.answer()
    await q.message.reply_text('🎨 GRAFICA E TEMPLATE\n\n🏷 Offerta: meno del 30%\n🔥 Super offerta: dal 30% al 69%\n🚨 Sconto extra: dal 70%\n🎟 Solo coupon: quando manca una riduzione sul prezzo esposto.\n♻️ Amazon Seconda mano: solo se condizione e prezzo specifico sono verificati.\n🔄 Amazon Renewed: ricondizionato identificato esplicitamente.\n\n❓ Tipologia non verificabile → SALTA IL PRODOTTO.\n\nPrezzo e disponibilità possono variare.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Impostazioni',callback_data='settings_menu')]]))


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

    reset_flusso(context)

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

OROSCOPO_SEGNI = (
    ("♈", "Ariete"), ("♉", "Toro"), ("♊", "Gemelli"),
    ("♋", "Cancro"), ("♌", "Leone"), ("♍", "Vergine"),
    ("♎", "Bilancia"), ("♏", "Scorpione"), ("♐", "Sagittario"),
    ("♑", "Capricorno"), ("♒", "Acquario"), ("♓", "Pesci"),
)
OROSCOPO_DIDASCALIA_SOLE = (
    "☀️ Un caffè con il sole ☕\n\n"
    "📅 {data} — Il tuo oroscopo di oggi\n\n"
    "Tra un impegno e l’altro, ritagliati un momento tutto tuo: un caffè, "
    "un sorriso e un piccolo consiglio dalle stelle. ✨\n\n"
    "👇 Tocca il tuo segno e scopri cosa ti aspetta!"
)
OROSCOPO_DIDASCALIA_LUNA = (
    "🌙 Un caffè con la luna ☕\n\n"
    "📅 {data} — La tua pausa della sera\n\n"
    "La giornata rallenta: lascia da parte gli impegni e concediti un momento "
    "di leggerezza al chiaro di luna. ✨\n\n"
    "Non hai ancora letto il tuo oroscopo? Oppure vuoi rileggerlo con calma?\n\n"
    "👇 Tocca il tuo segno e prenditi una pausa!"
)
OROSCOPO_DIDASCALIA = OROSCOPO_DIDASCALIA_SOLE
OROSCOPO_LOCK = asyncio.Lock()


def crea_didascalia_oroscopo(giorno, slot=0):
    data = datetime.strptime(giorno, "%Y-%m-%d").date()
    settimana = ("Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica")
    mesi = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
            "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")
    etichetta = f"{settimana[data.weekday()]} {data.day} {mesi[data.month - 1]}"
    modello = OROSCOPO_DIDASCALIA_LUNA if slot == 2 else OROSCOPO_DIDASCALIA_SOLE
    return modello.format(data=etichetta)


def foto_oroscopo(config, slot=1):
    # La vecchia foto resta il fallback per non interrompere le rubriche esistenti.
    return config.get('foto_luna' if slot == 2 else 'foto_sole') or config.get('foto', '')


def inizializza_oroscopi():
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS oroscopo_config (
                chiave TEXT PRIMARY KEY, valore TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS oroscopo_giorni (
                giorno TEXT PRIMARY KEY, testi TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS oroscopo_snapshot (
                id TEXT PRIMARY KEY, giorno TEXT NOT NULL, testi TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS oroscopo_invii (
                giorno TEXT NOT NULL, canale TEXT NOT NULL, stato TEXT NOT NULL,
                message_id INTEGER, errore TEXT,
                PRIMARY KEY(giorno, canale));
            CREATE TABLE IF NOT EXISTS oroscopo_uscite (
                giorno TEXT NOT NULL, canale TEXT NOT NULL, stato TEXT NOT NULL,
                message_id INTEGER, errore TEXT, slot INTEGER NOT NULL,
                PRIMARY KEY(giorno, canale, slot));
            CREATE TABLE IF NOT EXISTS oroscopo_clic (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                callback_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL, username TEXT, nome TEXT NOT NULL,
                segno INTEGER NOT NULL, giorno TEXT NOT NULL,
                slot INTEGER NOT NULL, canale TEXT, clic_il TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_oroscopo_clic_data ON oroscopo_clic(clic_il);
            CREATE INDEX IF NOT EXISTS idx_oroscopo_clic_utente ON oroscopo_clic(user_id);
        """)
        # Conserva gli invii della versione precedente come prima uscita.
        db.execute("""INSERT OR IGNORE INTO oroscopo_uscite
            (giorno,canale,stato,message_id,errore,slot)
            SELECT giorno,canale,stato,message_id,errore,1 FROM oroscopo_invii""")
        colonne = {r[1] for r in db.execute("PRAGMA table_info(oroscopo_snapshot)")}
        for nome, definizione in (("slot", "INTEGER NOT NULL DEFAULT 0"),
                                  ("anteprima", "INTEGER NOT NULL DEFAULT 1")):
            if nome not in colonne:
                db.execute(f"ALTER TABLE oroscopo_snapshot ADD COLUMN {nome} {definizione}")
        defaults = {"attivo": False, "ora": "13:30", "canali": ["tech"],
                    "ora2": "18:30", "secondo_attivo": False,
                    "foto": "", "foto_sole": "", "foto_luna": "",
                    "promemoria": "", "esaurimento": ""}
        db.executemany("INSERT OR IGNORE INTO oroscopo_config VALUES (?, ?)",
                       [(k, json.dumps(v, ensure_ascii=False)) for k, v in defaults.items()])


def configurazione_oroscopo():
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        values = {k: json.loads(v) for k, v in db.execute("SELECT chiave, valore FROM oroscopo_config")}
    values["canali"] = list(CANALI)
    return values


def imposta_oroscopo(chiave, valore):
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute("INSERT OR REPLACE INTO oroscopo_config VALUES (?, ?)",
                   (chiave, json.dumps(valore, ensure_ascii=False)))


def orari_oroscopo(cfg):
    orari = [(1, cfg["ora"])]
    if cfg.get("secondo_attivo", False):
        orari.append((2, cfg.get("ora2", "18:30")))
    return orari


def valida_orari_oroscopo(primo, secondo):
    if secondo <= primo:
        raise ValueError("Il secondo orario deve essere successivo al primo, nello stesso giorno.")


def giorni_oroscopo():
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        return db.execute("SELECT giorno FROM oroscopo_giorni ORDER BY giorno").fetchall()


def testi_oroscopo(giorno):
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        row = db.execute("SELECT testi FROM oroscopo_giorni WHERE giorno=?", (giorno,)).fetchone()
    return json.loads(row[0]) if row else None


def lunghezza_telegram(testo):
    # Telegram conta le unità UTF-16: alcune emoji occupano due unità.
    return len(testo.encode("utf-16-le")) // 2


def analizza_oroscopi(testo):
    """Formato: DATA: AAAA-MM-GG, poi dodici righe '♈ Ariete: testo'."""
    giornate, corrente, segno = {}, None, None
    for numero, raw in enumerate(testo.lstrip("\ufeff").splitlines(), 1):
        line = raw.strip()
        if not line or re.fullmatch(r"[-=]{3,}", line):
            continue
        data = re.fullmatch(r"(?:DATA\s*:\s*)?(\d{4}-\d{2}-\d{2})", line, re.I)
        if data:
            corrente = datetime.strptime(data[1], "%Y-%m-%d").date().isoformat()
            if corrente in giornate:
                raise ValueError(f"Data ripetuta: {corrente}.")
            giornate[corrente], segno = {}, None
            continue
        trovato = None
        for i, (simbolo, nome) in enumerate(OROSCOPO_SEGNI):
            match = re.fullmatch(r"(?:" + re.escape(simbolo) + r"\ufe0f?\s*)?"
                                 + nome + r"(?:\s*[:\-–]\s*|\s+|$)(.*)", line, re.I)
            if match:
                trovato = (i, match[1].strip())
                break
        if corrente is None:
            raise ValueError(f"Riga {numero}: inizia con DATA: AAAA-MM-GG.")
        if trovato:
            segno, contenuto = trovato
            if str(segno) in giornate[corrente]:
                raise ValueError(f"{corrente}: {OROSCOPO_SEGNI[segno][1]} ripetuto.")
            giornate[corrente][str(segno)] = contenuto
        elif segno is not None:
            key = str(segno)
            giornate[corrente][key] = (giornate[corrente][key] + " " + line).strip()
        else:
            raise ValueError(f"Riga {numero}: segno zodiacale non riconosciuto.")
    if not giornate:
        raise ValueError("Nessuna giornata trovata.")
    if len(giornate) > 62:
        raise ValueError("Carica al massimo 62 giornate alla volta.")
    for giorno, testi in giornate.items():
        for i, (simbolo, nome) in enumerate(OROSCOPO_SEGNI):
            if not testi.get(str(i)):
                raise ValueError(f"{giorno}: manca il testo di {nome}.")
            popup = f"{simbolo} {nome}\n{testi[str(i)]}"
            if lunghezza_telegram(popup) > 200:
                raise ValueError(f"{giorno}, {nome}: supera 200 caratteri, incluso il titolo.")
    return giornate


def salva_oroscopi(giornate):
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute("BEGIN IMMEDIATE")
        for giorno in giornate:
            if db.execute("SELECT 1 FROM oroscopo_uscite WHERE giorno=?", (giorno,)).fetchone():
                raise ValueError(f"{giorno}: giornata già inviata o in verifica; non sovrascrivibile.")
        db.executemany("INSERT OR REPLACE INTO oroscopo_giorni VALUES (?, ?)",
                       [(g, json.dumps(t, ensure_ascii=False)) for g, t in giornate.items()])


def tastiera_segni_oroscopo(snapshot_id):
    pulsanti = [InlineKeyboardButton(f"{s} {n}", callback_data=f"oro_segno:{snapshot_id}:{i}")
                for i, (s, n) in enumerate(OROSCOPO_SEGNI)]
    return InlineKeyboardMarkup([pulsanti[i:i + 2] for i in range(0, 12, 2)])


async def invia_anteprima_oroscopo(bot, chat_id, giorno, slot=0, anteprima=True):
    config, testi = configurazione_oroscopo(), testi_oroscopo(giorno)
    if not testi:
        raise ValueError("Nessun testo caricato per questa giornata.")
    foto = foto_oroscopo(config, slot)
    if not foto:
        raise ValueError("Prima carica la foto " + ("luna" if slot == 2 else "sole") + " dal pannello della rubrica.")
    snapshot = os.urandom(8).hex()
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute("INSERT INTO oroscopo_snapshot(id,giorno,testi,slot,anteprima) VALUES (?, ?, ?, ?, ?)",
                   (snapshot, giorno, json.dumps(testi, ensure_ascii=False), slot, int(anteprima)))
    # Lo snapshot resta immutabile anche se si modificano i testi futuri.
    return await bot.send_photo(chat_id=chat_id, photo=foto,
                                caption=crea_didascalia_oroscopo(giorno, slot=slot),
                                reply_markup=tastiera_segni_oroscopo(snapshot))


async def mostra_pannello_oroscopo(messaggio, context):
    cfg = configurazione_oroscopo()
    oggi = datetime.now(ROMA_TZ).date().isoformat()
    future = [g[0] for g in giorni_oroscopo() if g[0] >= oggi]
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        invii = dict(db.execute("SELECT stato, count(*) FROM oroscopo_uscite GROUP BY stato"))
    stato = "ATTIVA" if cfg["attivo"] else "SOSPESA"
    riepilogo = (
        f"☕ UN CAFFÈ CON LE STELLE — {stato}\n\n"
        f"🕒 Primo invio: {cfg['ora']} (Italia)\n"
        f"🕕 Secondo invio: {cfg['ora2']} — {'ON' if cfg['secondo_attivo'] else 'OFF'}\n"
        f"📢 Canali: {', '.join(c.upper() for c in cfg['canali'])}\n"
        f"☀️ Foto sole: {'caricata' if foto_oroscopo(cfg, 1) else 'da caricare'}\n"
        f"🌙 Foto luna: {'caricata' if foto_oroscopo(cfg, 2) else 'da caricare'}\n"
        f"📅 Giornate da oggi: {len(future)}\n"
        f"Ultima data caricata: {future[-1] if future else 'nessuna'}\n"
        f"✅ Post inviati: {invii.get('inviato', 0)}\n"
        f"⚠️ Invii da verificare: {sum(v for k, v in invii.items() if k != 'inviato')}\n\n"
        "Promemoria nella chat admin 24 ore prima dell’ultimo post."
    )
    await messaggio.reply_text(riepilogo, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Carica oroscopi", callback_data="oro_carica"),
         InlineKeyboardButton("📅 Calendario / modifica", callback_data="oro_cal:0")],
        [InlineKeyboardButton("☀️ Imposta foto sole", callback_data="oro_foto_sole"),
         InlineKeyboardButton("🌙 Imposta foto luna", callback_data="oro_foto_luna")],
        [InlineKeyboardButton("☀️ Anteprima sole", callback_data="oro_anteprima:1:0"),
         InlineKeyboardButton("🌙 Anteprima luna", callback_data="oro_anteprima:2:0")],
        [InlineKeyboardButton("⚙️ Impostazioni rubrica", callback_data="oro_impostazioni")],
        [InlineKeyboardButton("📊 Statistiche", callback_data="oro_stats:oggi")],
        [InlineKeyboardButton("⏸ Sospendi" if cfg["attivo"] else "▶️ Attiva", callback_data="oro_attiva")],
        [InlineKeyboardButton("⬅️ Rubrica", callback_data="rub_menu")],
    ]))


def oroscopo_indietro():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Rubrica", callback_data="oro_menu")]])


def registra_clic_oroscopo(query, snapshot, segno):
    utente = getattr(query, "from_user", None)
    if utente is None or not getattr(query, "id", None):
        return
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        dati = db.execute("SELECT giorno,slot,anteprima FROM oroscopo_snapshot WHERE id=?",
                          (snapshot,)).fetchone()
        if not dati:
            return
        giorno, slot, anteprima = dati
        messaggio = getattr(query, "message", None)
        canale = str(getattr(messaggio, "chat_id", "") or "")
        if anteprima:
            # Vecchi post: il loro snapshot non aveva ancora il tipo di uscita.
            pubblicato = db.execute(
                "SELECT slot FROM oroscopo_uscite WHERE giorno=? AND canale=? AND message_id=?",
                (giorno, canale, getattr(messaggio, "message_id", None))).fetchone()
            if not pubblicato:
                return  # Le anteprime private non entrano nelle statistiche.
            slot = pubblicato[0]
        nome = " ".join(str(getattr(utente, "full_name", "") or "Utente").split())[:200]
        username = getattr(utente, "username", None)
        db.execute("""INSERT OR IGNORE INTO oroscopo_clic
            (callback_id,user_id,username,nome,segno,giorno,slot,canale,clic_il)
            VALUES (?,?,?,?,?,?,?,?,?)""", (
                str(query.id), int(utente.id), username, nome, segno, giorno, slot, canale,
                datetime.now(timezone.utc).isoformat(timespec="seconds")))


def filtro_statistiche_oroscopo(periodo):
    if periodo not in {"oggi", "7", "30", "tutto"}:
        raise ValueError("Periodo statistiche non valido.")
    if periodo == "tutto":
        return "1=1", [], "Tutto il periodo"
    giorni = 1 if periodo == "oggi" else int(periodo)
    inizio = datetime.now(ROMA_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    inizio -= timedelta(days=giorni - 1)
    return "clic_il>=?", [inizio.astimezone(timezone.utc).isoformat(timespec="seconds")], (
        "Oggi" if periodo == "oggi" else f"Ultimi {giorni} giorni")


def tastiera_statistiche_oroscopo(periodo):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(titolo, callback_data=f"oro_stats:{valore}")
         for valore, titolo in (("oggi", "Oggi"), ("7", "7 giorni"), ("30", "30 giorni"), ("tutto", "Tutto"))],
        [InlineKeyboardButton("👥 Elenco utenti", callback_data=f"oro_utenti:{periodo}:0"),
         InlineKeyboardButton("📥 Esporta CSV", callback_data=f"oro_export:{periodo}")],
        [InlineKeyboardButton("🔄 Aggiorna", callback_data=f"oro_stats:{periodo}"),
         InlineKeyboardButton("⬅️ Rubrica", callback_data="oro_menu")],
    ])


async def mostra_statistiche_oroscopo(msg, periodo):
    dove, valori, etichetta = filtro_statistiche_oroscopo(periodo)
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        totale, utenti = db.execute(
            f"SELECT count(*),count(DISTINCT user_id) FROM oroscopo_clic WHERE {dove}", valori).fetchone()
        segni = db.execute(f"SELECT segno,count(*) FROM oroscopo_clic WHERE {dove} "
                           "GROUP BY segno ORDER BY count(*) DESC,segno", valori).fetchall()
        uscite = db.execute(f"SELECT slot,count(*),count(DISTINCT user_id) FROM oroscopo_clic WHERE {dove} "
                            "GROUP BY slot ORDER BY slot", valori).fetchall()
    righe = [f"📊 STATISTICHE OROSCOPO — {etichetta}",
             f"\n👆 Clic totali: {totale}", f"👥 Persone uniche: {utenti}", "\n📣 Confronto pubblicazioni:"]
    for slot, clic, persone in uscite:
        nome = f"Invio {slot}" if slot in {1, 2} else "Post precedenti"
        righe.append(f"{nome}: {clic} clic · {persone} persone")
    if not uscite:
        righe.append("Nessun clic registrato nel periodo.")
    righe.append("\n🔮 Segni più selezionati:")
    for indice, quantita in segni:
        simbolo, nome = OROSCOPO_SEGNI[indice]
        righe.append(f"{simbolo} {nome}: {quantita}")
    righe.append("\nLe anteprime private sono escluse. I clic ripetuti contano; le persone sono deduplicate per ID Telegram.")
    await msg.reply_text("\n".join(righe), reply_markup=tastiera_statistiche_oroscopo(periodo))


async def mostra_utenti_oroscopo(msg, periodo, pagina=0):
    dove, valori, etichetta = filtro_statistiche_oroscopo(periodo)
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        totale = db.execute(f"SELECT count(DISTINCT user_id) FROM oroscopo_clic WHERE {dove}", valori).fetchone()[0]
        pagina = min(pagina, max(0, (totale - 1) // 8))
        righe = db.execute(f"""WITH utenti AS (
            SELECT user_id,count(*) AS clic,max(id) AS ultimo FROM oroscopo_clic
            WHERE {dove} GROUP BY user_id)
            SELECT c.user_id,c.username,c.nome,c.segno,c.giorno,c.slot,c.clic_il,u.clic
            FROM utenti u JOIN oroscopo_clic c ON c.id=u.ultimo
            ORDER BY c.id DESC LIMIT 8 OFFSET ?""", [*valori, pagina * 8]).fetchall()
    testo = [f"👥 UTENTI OROSCOPO — {etichetta}", f"Persone: {totale} · Pagina {pagina + 1}"]
    for uid, username, nome, segno, giorno, slot, quando, clic in righe:
        identita = f"@{username}" if username else f"{nome} (senza username)"
        data = datetime.fromisoformat(quando).astimezone(ROMA_TZ).strftime("%d/%m/%Y %H:%M")
        simbolo, nome_segno = OROSCOPO_SEGNI[segno]
        testo.append(f"\n{identita[:100]} · ID {uid}\n"
                     f"{clic} clic · Ultimo: {simbolo} {nome_segno}, {data}\n"
                     f"Oroscopo {giorno} · Invio {slot}")
    if not righe:
        testo.append("\nNessun utente nel periodo selezionato.")
    bottoni, navigazione = [], []
    if pagina:
        navigazione.append(InlineKeyboardButton("⬅️", callback_data=f"oro_utenti:{periodo}:{pagina - 1}"))
    if totale > (pagina + 1) * 8:
        navigazione.append(InlineKeyboardButton("➡️", callback_data=f"oro_utenti:{periodo}:{pagina + 1}"))
    if navigazione:
        bottoni.append(navigazione)
    bottoni.append([InlineKeyboardButton("📥 Esporta tutti i clic", callback_data=f"oro_export:{periodo}")])
    bottoni.append([InlineKeyboardButton("⬅️ Statistiche", callback_data=f"oro_stats:{periodo}")])
    await msg.reply_text("\n".join(testo), reply_markup=InlineKeyboardMarkup(bottoni))


def crea_csv_clic_oroscopo(periodo):
    dove, valori, _ = filtro_statistiche_oroscopo(periodo)
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        righe = db.execute(f"""SELECT user_id,username,nome,segno,giorno,slot,canale,clic_il
            FROM oroscopo_clic WHERE {dove} ORDER BY clic_il,id""", valori).fetchall()
    testo = StringIO(newline="")
    writer = csv.writer(testo, delimiter=";")
    writer.writerow(["ID Telegram", "Username", "Nome", "Segno premuto", "Data oroscopo",
                     "Invio", "Chat del clic", "Data e ora clic (Italia)"])
    def sicuro(valore):
        valore = str(valore or "")
        return "'" + valore if valore.lstrip().startswith(("=", "+", "-", "@")) else valore
    for uid, username, nome, segno, giorno, slot, canale, quando in righe:
        data = datetime.fromisoformat(quando).astimezone(ROMA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow([uid, sicuro(username), sicuro(nome), OROSCOPO_SEGNI[segno][1],
                         giorno, slot, sicuro(canale), data])
    return testo.getvalue().encode("utf-8-sig"), len(righe)


async def esporta_clic_oroscopo(msg, periodo):
    dati, quantita = crea_csv_clic_oroscopo(periodo)
    file = BytesIO(dati)
    file.name = f"clic_oroscopo_{periodo}_{datetime.now(ROMA_TZ):%Y%m%d}.csv"
    await msg.reply_document(document=file, filename=file.name,
                             caption=f"📊 Report oroscopo: {quantita} clic. Orari italiani; anteprime escluse.")


async def gestisci_oroscopi(update, context):
    """Gruppo -1: blocca gli altri handler solo per aggiornamenti della rubrica."""
    query, msg = update.callback_query, update.effective_message
    dato = query.data if query else ""
    if query and dato.startswith("quiz_r:"):
        await risposta_quiz(query)
        raise ApplicationHandlerStop
    if query and dato.startswith("oro_segno:"):
        row = None
        try:
            _, snapshot, indice = dato.split(":")
            i = int(indice)
            if not 0 <= i < 12:
                raise ValueError("segno")
            with sqlite3.connect(DB_PATH, timeout=30) as db:
                row = db.execute("SELECT testi FROM oroscopo_snapshot WHERE id=?", (snapshot,)).fetchone()
            if not row:
                raise ValueError("snapshot")
            simbolo, nome = OROSCOPO_SEGNI[i]
            popup = f"{simbolo} {nome}\n{json.loads(row[0])[str(i)]}"
        except (ValueError, KeyError, TypeError):
            popup = "Questo oroscopo non è disponibile."
        await query.answer(popup, show_alert=True)
        if row and popup != "Questo oroscopo non è disponibile.":
            try:
                registra_clic_oroscopo(query, snapshot, i)
            except Exception as errore:
                # La raccolta statistiche non deve impedire di leggere il segno.
                print(f"Errore registrazione clic oroscopo: {type(errore).__name__}")
        raise ApplicationHandlerStop
    modalita = context.user_data.get("oroscopo_modalita")
    if query and not (dato.startswith("oro_") or dato.startswith("quiz_") or dato == "rub_menu"):
        context.user_data.pop("oroscopo_modalita", None)
        return
    if not ((query and (dato.startswith("oro_") or dato.startswith("quiz_") or dato == "rub_menu")) or (modalita and update.message)):
        return
    if not await controlla_autorizzazione(update):
        raise ApplicationHandlerStop
    if update.effective_chat.type != "private":
        if query:
            await query.answer("Gestisci la rubrica nella chat privata del bot.", show_alert=True)
        raise ApplicationHandlerStop
    if update.message and (msg.text or "").startswith("/"):
        context.user_data.pop("oroscopo_modalita", None)
        if (msg.text or "").split()[0].split("@")[0] == "/annulla":
            context.user_data.pop("oroscopo_import", None)
            await mostra_pannello_oroscopo(msg, context)
            raise ApplicationHandlerStop
        return
    try:
        if query:
            await query.answer()
            if dato == "rub_menu" or dato.startswith("quiz_"):
                await azione_quiz(dato, msg, context)
            else:
                await azione_oroscopo(dato, msg, context)
        else:
            if str(modalita).startswith("quiz_"):
                await input_quiz(msg, context, modalita)
            else:
                await ricevi_input_oroscopo(msg, context, modalita)
    except ValueError as errore:
        await msg.reply_text(f"⚠️ {errore}", reply_markup=oroscopo_indietro())
    except Exception as errore:
        print(f"Errore rubrica oroscopo: {type(errore).__name__}: {errore}")
        await msg.reply_text("⚠️ Operazione non riuscita. Riprova dal menu della rubrica.",
                             reply_markup=oroscopo_indietro())
    raise ApplicationHandlerStop


async def azione_oroscopo(dato, msg, context):
    cfg = configurazione_oroscopo()
    context.user_data.pop("oroscopo_modalita", None)
    if dato == "oro_menu":
        context.user_data.pop("oroscopo_verificati", None)
        context.user_data.pop("oroscopo_import", None)
        await mostra_pannello_oroscopo(msg, context)
    elif dato == "oro_carica" or dato.startswith("oro_modifica:"):
        context.user_data["oroscopo_modalita"] = "importa"
        context.user_data["oroscopo_import"] = ""
        context.user_data.pop("oroscopo_verificati", None)
        context.user_data["oroscopo_modifica"] = dato.split(":", 1)[1] if ":" in dato else None
        await msg.reply_text(
            "📥 Incolla i testi, anche in più messaggi, oppure allega il file .txt UTF-8.\n\n"
            "Formato:\nDATA: 2026-11-01\n♈ Ariete: Testo breve…\n♉ Toro: Testo breve…\n"
            "…tutti i 12 segni…\n\nDATA: 2026-11-02\n…\n\n"
            "Quando hai finito premi Verifica. Nulla viene salvato prima della conferma.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 Verifica testi", callback_data="oro_verifica")],
                [InlineKeyboardButton("⬅️ Annulla", callback_data="oro_menu")]]))
    elif dato == "oro_verifica":
        context.user_data["oroscopo_modalita"] = "importa"
        giornate = analizza_oroscopi(context.user_data.get("oroscopo_import", ""))
        data_modifica = context.user_data.get("oroscopo_modifica")
        if data_modifica and set(giornate) != {data_modifica}:
            raise ValueError(f"Per questa modifica inserisci solo DATA: {data_modifica}.")
        date = sorted(giornate)
        context.user_data["oroscopo_verificati"] = giornate
        await msg.reply_text(
            f"✅ {len(date)} giornate complete, {12 * len(date)} testi validi.\n"
            f"Dal {date[0]} al {date[-1]}.\nLe date esistenti non pubblicate saranno sostituite.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💾 Conferma e salva", callback_data="oro_salva")],
                [InlineKeyboardButton("⬅️ Annulla", callback_data="oro_menu")]]))
    elif dato == "oro_salva":
        giornate = context.user_data.pop("oroscopo_verificati", None)
        if not giornate:
            raise ValueError("Prima carica e verifica i testi.")
        salva_oroscopi(giornate)
        context.user_data.pop("oroscopo_import", None)
        await msg.reply_text(f"💾 Salvate {len(giornate)} giornate. Puoi provarle con Anteprima.")
        await mostra_pannello_oroscopo(msg, context)
    elif dato in {"oro_foto", "oro_foto_sole", "oro_foto_luna", "oro_ora", "oro_ora1", "oro_ora2"}:
        campo = dato[4:]
        if campo == "foto":
            campo = "foto_sole"
        if campo == "ora1":
            campo = "ora"
        context.user_data["oroscopo_modalita"] = campo
        istruzioni = {"foto_sole": "☀️ Invia la foto per il primo appuntamento come immagine Telegram.",
                      "foto_luna": "🌙 Invia la foto per il secondo appuntamento come immagine Telegram.",
                      "ora": "🕒 Scrivi il primo orario HH:MM, ad esempio 13:30 (ora italiana).",
                      "ora2": "🕕 Scrivi il secondo orario HH:MM, successivo al primo. Salvandolo attivi il secondo invio."}
        await msg.reply_text(istruzioni[campo], reply_markup=oroscopo_indietro())
    elif dato == "oro_didascalia":
        # Compatibilità con il vecchio pulsante eventualmente ancora in chat.
        await msg.reply_text("La didascalia è automatica e include giorno della settimana e data.",
                             reply_markup=oroscopo_indietro())
    elif dato == "oro_impostazioni":
        await msg.reply_text(
            f"⚙️ Impostazioni rubrica\nPrimo invio: {cfg['ora']} (Italia)\n"
            f"Secondo invio: {cfg['ora2']} — {'ON' if cfg['secondo_attivo'] else 'OFF'}\n"
            "I due post usano gli stessi testi della giornata su tutti i canali.\n"
            f"Canali: {', '.join(cfg['canali'])}\n\nImpostazioni comuni a tutti i canali:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🕒 Primo orario", callback_data="oro_ora"),
                 InlineKeyboardButton("🕕 Secondo orario", callback_data="oro_ora2")],
                [InlineKeyboardButton("🔔 Secondo invio: " + ("ON" if cfg['secondo_attivo'] else "OFF"),
                                      callback_data="oro_secondo_toggle")],
                [InlineKeyboardButton("⬅️ Rubrica", callback_data="oro_menu")]]))
    elif dato == "oro_secondo_toggle":
        if not cfg["secondo_attivo"]:
            valida_orari_oroscopo(cfg["ora"], cfg["ora2"])
        imposta_oroscopo("secondo_attivo", not cfg["secondo_attivo"])
        await azione_oroscopo("oro_impostazioni", msg, context)
    elif dato.startswith("oro_stats:"):
        await mostra_statistiche_oroscopo(msg, dato.split(":")[1])
    elif dato.startswith("oro_utenti:"):
        _, periodo, pagina = dato.split(":")
        await mostra_utenti_oroscopo(msg, periodo, max(0, int(pagina)))
    elif dato.startswith("oro_export:"):
        await esporta_clic_oroscopo(msg, dato.split(":")[1])
    elif dato.startswith("oro_canali:"):
        valore = dato.split(":")[1]
        if valore not in CANALI and valore != "entrambi":
            raise ValueError("Canale non valido.")
        imposta_oroscopo("canali", list(CANALI) if valore == "entrambi" else [valore])
        await mostra_pannello_oroscopo(msg, context)
    elif dato == "oro_attiva":
        if not cfg["attivo"]:
            oggi = datetime.now(ROMA_TZ).date().isoformat()
            if not all(foto_oroscopo(cfg, slot) for slot, _ in orari_oroscopo(cfg)) or not any(g[0] >= oggi for g in giorni_oroscopo()):
                raise ValueError("Carica le foto degli appuntamenti attivi e almeno una giornata da oggi in poi prima di attivare.")
        imposta_oroscopo("attivo", not cfg["attivo"])
        await mostra_pannello_oroscopo(msg, context)
    elif dato.startswith(("oro_cal:", "oro_anteprima:")) or dato == "oro_anteprima":
        righe = giorni_oroscopo()
        if not righe:
            raise ValueError("Carica prima una giornata di prova.")
        parti = dato.split(":")
        slot_anteprima = int(parti[1]) if dato.startswith("oro_anteprima:") else None
        if slot_anteprima is not None and slot_anteprima not in {1, 2}:
            raise ValueError("Appuntamento non valido.")
        pagina = max(0, int(parti[2] if slot_anteprima else parti[1])) if len(parti) > 1 else 0
        pagina = min(pagina, max(0, (len(righe)-1)//7))
        destinazione_pagina = f"oro_anteprima:{slot_anteprima}:" if slot_anteprima else "oro_cal:"
        bottoni = []
        with sqlite3.connect(DB_PATH, timeout=30) as db:
            inviate = {r[0] for r in db.execute("SELECT DISTINCT giorno FROM oroscopo_uscite")}
        for (giorno,) in righe[pagina * 7:pagina * 7 + 7]:
            row = [InlineKeyboardButton(f"{'✅' if giorno in inviate else '👁'} {giorno}",
                                        callback_data=(f"oro_prova:{slot_anteprima}:{giorno}:{pagina}" if slot_anteprima else f"oro_preview:{giorno}"))]
            if giorno not in inviate and slot_anteprima is None:
                row.append(InlineKeyboardButton("✏️ Modifica", callback_data=f"oro_modifica:{giorno}"))
            bottoni.append(row)
        nav = []
        if pagina:
            nav.append(InlineKeyboardButton("⬅️", callback_data=destinazione_pagina + str(pagina - 1)))
        if len(righe) > (pagina + 1) * 7:
            nav.append(InlineKeyboardButton("➡️", callback_data=destinazione_pagina + str(pagina + 1)))
        if nav:
            bottoni.append(nav)
        bottoni.append([InlineKeyboardButton("⬅️ Rubrica", callback_data="oro_menu")])
        await msg.reply_text(("☀️ Anteprima sole" if slot_anteprima == 1 else "🌙 Anteprima luna" if slot_anteprima == 2 else "📅 Calendario / modifica") + "\nScegli una data per l’anteprima privata (nessun invio al canale).",
                             reply_markup=InlineKeyboardMarkup(bottoni))
    elif dato.startswith("oro_preview:"):
        giorno = dato.split(":")[1]
        await msg.reply_text(f"👁 Scegli l’anteprima privata del {giorno}:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("☀️ Anteprima sole", callback_data=f"oro_prova:1:{giorno}"),
             InlineKeyboardButton("🌙 Anteprima luna", callback_data=f"oro_prova:2:{giorno}")],
            [InlineKeyboardButton("⬅️ Indietro", callback_data="oro_anteprima")]]))
    elif dato.startswith("oro_prova:"):
        parti = dato.split(":")
        _, numero, giorno = parti[:3]
        ritorno = f"oro_anteprima:{numero}:{max(0, int(parti[3]))}" if len(parti) == 4 else f"oro_preview:{giorno}"
        if numero not in {"1", "2"}:
            raise ValueError("Appuntamento non valido.")
        await invia_anteprima_oroscopo(context.bot, msg.chat_id, giorno, slot=int(numero))
        await msg.reply_text("Prova i 12 pulsanti qui sopra.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Indietro", callback_data=ritorno)]]))


async def ricevi_input_oroscopo(msg, context, modalita):
    if modalita in {"foto", "foto_sole", "foto_luna"}:
        if not msg.photo:
            raise ValueError("Invia una foto come immagine, non come documento.")
        imposta_oroscopo("foto_sole" if modalita == "foto" else modalita, msg.photo[-1].file_id)
    elif modalita in {"ora", "ora2"}:
        valore = (msg.text or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", valore):
            raise ValueError("Usa il formato HH:MM, ad esempio 13:30.")
        cfg = configurazione_oroscopo()
        if modalita == "ora2":
            valida_orari_oroscopo(cfg["ora"], valore)
            imposta_oroscopo("ora2", valore)
            imposta_oroscopo("secondo_attivo", True)
        else:
            if cfg["secondo_attivo"]:
                valida_orari_oroscopo(valore, cfg["ora2"])
            imposta_oroscopo("ora", valore)
    elif modalita == "importa":
        if msg.document:
            if not (msg.document.file_name or "").lower().endswith(".txt"):
                raise ValueError("Allega un file .txt.")
            if (msg.document.file_size or 0) > 1_000_000:
                raise ValueError("Il file è troppo grande (massimo 1 MB).")
            file = await msg.document.get_file()
            dati = await file.download_as_bytearray()
            if len(dati) > 1_000_000:
                raise ValueError("Il file supera 1 MB.")
            try:
                valore = dati.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise ValueError("Salva il file con codifica UTF-8.")
        else:
            valore = msg.text or ""
        if not valore.strip():
            raise ValueError("Invia il testo degli oroscopi oppure un file .txt.")
        accumulato = context.user_data.get("oroscopo_import", "") + "\n" + valore
        if len(accumulato) > 1_000_000:
            raise ValueError("Troppo testo. Annulla e carica un blocco più piccolo.")
        context.user_data["oroscopo_import"] = accumulato
        context.user_data.pop("oroscopo_verificati", None)
        await msg.reply_text(
            f"📥 Testo ricevuto ({len(accumulato.strip())} caratteri). Puoi continuare a incollare o verificare.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 Verifica testi", callback_data="oro_verifica")],
                [InlineKeyboardButton("⬅️ Annulla", callback_data="oro_menu")]]))
        return
    else:
        return
    context.user_data.pop("oroscopo_modalita", None)
    await msg.reply_text("✅ Impostazione salvata.")
    await mostra_pannello_oroscopo(msg, context)


async def verifica_scadenza_oroscopi(bot, adesso, cfg):
    date = [g[0] for g in giorni_oroscopo()]
    if not date:
        return
    ultimo = max(date)
    ultimo_orario = orari_oroscopo(cfg)[-1][1]
    scadenza = datetime.fromisoformat(f"{ultimo}T{ultimo_orario}").replace(tzinfo=ROMA_TZ)
    chiave = f"{ultimo} {ultimo_orario}"
    scadenza_utc, adesso_utc = scadenza.astimezone(timezone.utc), adesso.astimezone(timezone.utc)
    if scadenza_utc - timedelta(hours=24) <= adesso_utc <= scadenza_utc and cfg["promemoria"] != chiave and ADMIN_ID:
        await bot.send_message(chat_id=ADMIN_ID, text=(
            f"⚠️ Un caffè con le stelle: ultimo post disponibile {ultimo} alle {ultimo_orario}.\n"
            "Chiedimi il prossimo file con i 12 segni per 30 giorni e caricalo nel bot."))
        imposta_oroscopo("promemoria", chiave)
    if adesso > scadenza + timedelta(minutes=1) and adesso.date().isoformat() > ultimo:
        imposta_oroscopo("attivo", False)
        if cfg["esaurimento"] != ultimo and ADMIN_ID:
            await bot.send_message(chat_id=ADMIN_ID, text=(
                "⏸ Un caffè con le stelle sospesa: testi esauriti. "
                "Carica le nuove giornate e premi Attiva."))
            imposta_oroscopo("esaurimento", ultimo)


async def pubblica_oroscopo_giornaliero(app, adesso=None):
    adesso = adesso or datetime.now(ROMA_TZ)
    async with OROSCOPO_LOCK:
        cfg = configurazione_oroscopo()
        if not cfg["attivo"]:
            return
        await verifica_scadenza_oroscopi(app.bot, adesso, cfg)
        if not configurazione_oroscopo()["attivo"]:
            return
        giorno = adesso.date().isoformat()
        scaduti = [(slot, ora) for slot, ora in orari_oroscopo(cfg)
                   if adesso >= datetime.fromisoformat(f"{giorno}T{ora}").replace(tzinfo=ROMA_TZ)]
        if not scaduti:
            return
        # Al riavvio usa l'ultimo orario raggiunto: niente due post arretrati insieme.
        slot, ora_slot = scaduti[-1]
        if not testi_oroscopo(giorno):
            # Nessun riuso di vecchi testi; notifica il buco una sola volta al giorno.
            if cfg.get("giorno_mancante") != giorno and ADMIN_ID:
                await app.bot.send_message(chat_id=ADMIN_ID,
                    text=f"⚠️ Nessun oroscopo caricato per {giorno}: oggi la rubrica non viene pubblicata.")
                imposta_oroscopo("giorno_mancante", giorno)
            return
        if not foto_oroscopo(cfg, slot):
            imposta_oroscopo("attivo", False)
            return
        for canale in cfg["canali"]:
            if canale not in CANALI:
                continue
            destinazione = _chat_id_per_canale(canale)
            # Prenotazione persistente prima dell'invio: un riavvio non ripubblica.
            with sqlite3.connect(DB_PATH, timeout=30) as db:
                risultato = db.execute(
                    "INSERT OR IGNORE INTO oroscopo_uscite(giorno,canale,stato,slot) VALUES (?,?,'in_invio',?)",
                    (giorno, str(destinazione), slot))
                if risultato.rowcount == 0:
                    continue
            try:
                post = await invia_anteprima_oroscopo(app.bot, destinazione, giorno, slot=slot, anteprima=False)
                with sqlite3.connect(DB_PATH, timeout=30) as db:
                    db.execute("INSERT OR REPLACE INTO pausa_caffe_pubblicazioni VALUES (?,?,?,?)",
                               (giorno, str(destinazione), slot, adesso.isoformat(timespec='seconds')))
                    db.execute("UPDATE oroscopo_uscite SET stato='inviato', message_id=? WHERE giorno=? AND canale=? AND slot=?",
                               (post.message_id, giorno, str(destinazione), slot))
            except Exception as errore:
                with sqlite3.connect(DB_PATH, timeout=30) as db:
                    db.execute("UPDATE oroscopo_uscite SET stato='da_verificare', errore=? WHERE giorno=? AND canale=? AND slot=?",
                               (str(errore)[:500], giorno, str(destinazione), slot))
                if ADMIN_ID:
                    await app.bot.send_message(chat_id=ADMIN_ID, text=(
                        f"⚠️ Invio {slot} oroscopo {giorno}, ore {ora_slot} ({canale.upper()}) da verificare. "
                        "Controlla il canale: nessun nuovo tentativo automatico, per evitare doppioni."))


async def controlla_oroscopi(app):
    while True:
        try:
            await pubblica_oroscopo_giornaliero(app)
        except Exception as errore:
            print(f"Errore controllo oroscopi: {type(errore).__name__}: {errore}")
        await asyncio.sleep(30)



# =========================================================
# RUBRICA: QUIZ (un quiz al giorno, orari modificabili)
# =========================================================
QUIZ_LOCK = asyncio.Lock()

def inizializza_quiz():
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS quiz_config (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS quiz_giorni (giorno TEXT PRIMARY KEY, contenuto TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS quiz_uscite (giorno TEXT PRIMARY KEY, stato TEXT NOT NULL, message_id INTEGER, pubblicato_il TEXT, errore TEXT);
        CREATE TABLE IF NOT EXISTS quiz_voti (giorno TEXT NOT NULL, user_id INTEGER NOT NULL, username TEXT, scelta INTEGER NOT NULL, corretta INTEGER NOT NULL, votato_il TEXT NOT NULL, PRIMARY KEY(giorno,user_id));
        CREATE TABLE IF NOT EXISTS quiz_voti_test (giorno TEXT NOT NULL, user_id INTEGER NOT NULL, scelta INTEGER NOT NULL, votato_il TEXT NOT NULL, PRIMARY KEY(giorno,user_id));
        """)
        defaults={'attivo':False,'ora':'17:00','foto':'','promemoria':'','esaurimento':''}
        db.executemany('INSERT OR IGNORE INTO quiz_config VALUES (?,?)',[(k,json.dumps(v)) for k,v in defaults.items()])

    quiz_multicanale.inizializza(_servizi_invii)

def configurazione_quiz():
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        return {k:json.loads(v) for k,v in db.execute('SELECT chiave,valore FROM quiz_config')}

def imposta_quiz(k,v):
    with sqlite3.connect(DB_PATH, timeout=30) as db:
        db.execute('INSERT OR REPLACE INTO quiz_config VALUES (?,?)',(k,json.dumps(v,ensure_ascii=False)))

def valida_file_quiz(testo):
    try:
        data=json.loads(testo.lstrip('\ufeff'))
    except (ValueError,TypeError) as e:
        raise ValueError('File JSON non valido: '+str(e))
    if not isinstance(data,list) or not 1 <= len(data) <= 62:
        raise ValueError('Il file deve contenere da 1 a 62 quiz.')
    giorni={}
    for item in data:
        if not isinstance(item,dict): raise ValueError('Ogni quiz deve essere un oggetto JSON.')
        g=item.get('data')
        try: g=datetime.strptime(g,'%Y-%m-%d').date().isoformat()
        except (ValueError,TypeError): raise ValueError('Data non valida nel file quiz.')
        op=item.get('risposte')
        if not isinstance(op,list) or len(op)!=4 or any(not isinstance(x,str) or not x.strip() or len(x)>80 for x in op):
            raise ValueError(f'{g}: servono esattamente 4 risposte brevi.')
        if not isinstance(item.get('domanda'),str) or not 8<=len(item['domanda'])<=300:
            raise ValueError(f'{g}: domanda mancante o troppo lunga.')
        if not isinstance(item.get('corretta'),int) or not 0<=item['corretta']<=3:
            raise ValueError(f'{g}: corretta deve essere un numero da 0 a 3.')
        if not isinstance(item.get('approfondimento'),str) or not 20<=len(item['approfondimento'])<=450:
            raise ValueError(f'{g}: approfondimento mancante (20–450 caratteri).')
        if g in giorni: raise ValueError(f'Data duplicata: {g}')
        giorni[g]=item
    return giorni

def tastiera_quiz(g):
    with sqlite3.connect(DB_PATH,timeout=30) as db:
        r=db.execute('SELECT contenuto FROM quiz_giorni WHERE giorno=?',(g,)).fetchone()
    item=json.loads(r[0])
    return InlineKeyboardMarkup([[InlineKeyboardButton(x,callback_data=f'quiz_r:{g}:{i}')] for i,x in enumerate(item['risposte'])])

async def risposta_quiz(query):
    try:
        _, g, scelta_testo = query.data.split(':')
        scelta = int(scelta_testo)
        with sqlite3.connect(DB_PATH, timeout=30) as db:
            row = db.execute('SELECT contenuto FROM quiz_giorni WHERE giorno=?', (g,)).fetchone()
            if not row:
                raise ValueError('Quiz non disponibile.')
            item = json.loads(row[0])
            giusta = int(item['corretta'])
            if not 0 <= scelta < len(item['risposte']):
                raise ValueError('Risposta non valida.')
            uid = query.from_user.id
            ufficiale = quiz_multicanale.voto_ufficiale(_servizi_invii, db, query, g)
            if ufficiale:
                # Il voto ufficiale viene registrato una sola volta per utente e data.
                inserito = db.execute(
                    'INSERT OR IGNORE INTO quiz_voti VALUES (?,?,?,?,?,?)',
                    (g, uid, query.from_user.username, scelta, int(scelta == giusta),
                     datetime.now(timezone.utc).isoformat())
                ).rowcount
            else:
                # Anche l'anteprima privata blocca i tentativi successivi.
                # I test sono separati dalle statistiche e dai voti del canale.
                inserito = db.execute(
                    'INSERT OR IGNORE INTO quiz_voti_test VALUES (?,?,?,?)',
                    (g, uid, scelta, datetime.now(timezone.utc).isoformat())
                ).rowcount
            if not inserito:
                await query.answer(
                    '🧠 Hai già risposto al quiz di oggi!\n✨ Torna domani per una nuova sfida!',
                    show_alert=True
                )
                return
        # Un solo popup Telegram, nessun messaggio privato (test e canale).
        # Telegram limita answerCallbackQuery a 200 caratteri.
        # Formato compatto: ❌ solo se errata, poi risposta e 📚 spiegazione.
        # Manteniamo la risposta corretta visibile e non tagliamo parole a metà.
        intestazione = ("❌\n" if scelta != giusta else "") + f"✅ {item['risposte'][giusta]}\n📚 "
        spiegazione = ' '.join(item['approfondimento'].split())
        spazio = max(0, 200 - len(intestazione))
        if len(spiegazione) <= spazio:
            popup = intestazione + spiegazione
        elif spazio > 1:
            parole = spiegazione.split()
            testo = ''
            for parola in parole:
                candidato = (testo + ' ' + parola).strip()
                if len(candidato) + 1 > spazio:
                    break
                testo = candidato
            popup = intestazione + (testo + '…' if testo else spiegazione[:spazio - 1].rstrip() + '…')
        else:
            popup = intestazione[:200]
        await query.answer(popup, show_alert=True)
    except Exception as e:
        await query.answer(f'Quiz non disponibile: {str(e)[:100]}', show_alert=True)

async def mostra_rubrica(msg):
    oc=configurazione_oroscopo(); qc=configurazione_quiz()
    await msg.reply_text(f"☕ RUBRICA — BESTPRICE24H\n\n☀️ Primo Caffè: {oc['ora']}\n🧠 Quiz: {qc['ora']} ({'ON' if qc['attivo'] else 'OFF'})\n🌙 Secondo Caffè: {oc['ora2']}\n\n⏸ Pausa offerte: 30 minuti per ogni appuntamento.",reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton('♈ Oroscopo',callback_data='oro_menu'),InlineKeyboardButton('🧠 Quiz',callback_data='quiz_menu')],
        [InlineKeyboardButton('🕒 Orari rubrica',callback_data='quiz_orari')],
        [InlineKeyboardButton('⬅️ Menu principale',callback_data='menu_admin')]]))

async def pannello_quiz(msg):
    c=configurazione_quiz(); oggi=datetime.now(ROMA_TZ).date().isoformat()
    with sqlite3.connect(DB_PATH,timeout=30) as db:
        gg=[r[0] for r in db.execute('SELECT giorno FROM quiz_giorni WHERE giorno>=? ORDER BY giorno',(oggi,))]
    await msg.reply_text(f"🧠 QUIZ DEL CAFFÈ — TUTTI I CANALI\n\nStato: {'ATTIVO' if c['attivo'] else 'SOSPESO'}\n🕒 Orario: {c['ora']} (Italia)\n🖼 Foto: {'caricata' if c['foto'] else 'da caricare'}\n📅 Quiz disponibili: {len(gg)}\nUltima data: {gg[-1] if gg else 'nessuna'}\n⏸ Pausa offerte: 30 minuti",reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton('📥 Carica quiz',callback_data='quiz_carica'),InlineKeyboardButton('🖼 Imposta foto',callback_data='quiz_foto')],
        [InlineKeyboardButton('🕒 Cambia orario',callback_data='quiz_ora'),InlineKeyboardButton('📅 Calendario quiz',callback_data='quiz_cal:0')],
        [InlineKeyboardButton('👁 Anteprima di oggi',callback_data='quiz_preview')],
        [InlineKeyboardButton('📊 Statistiche',callback_data='quiz_stats'),InlineKeyboardButton('▶️ Attiva' if not c['attivo'] else '⏸ Sospendi',callback_data='quiz_toggle')],
        [InlineKeyboardButton('⬅️ Rubrica',callback_data='rub_menu')]]))

async def azione_quiz(dato,msg,context):
    context.user_data.pop('oroscopo_modalita',None)
    if dato=='rub_menu': await mostra_rubrica(msg); return
    if dato=='quiz_menu': await pannello_quiz(msg); return
    if dato=='quiz_orari':
        c=configurazione_oroscopo(); q=configurazione_quiz()
        await msg.reply_text(f"🕒 ORARI RUBRICA\n☀️ Primo Caffè: {c['ora']}\n🧠 Quiz: {q['ora']}\n🌙 Secondo Caffè: {c['ora2']}\n\nLe modifiche aggiornano subito la lista Programmati e le pause di 30 minuti.",reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('☀️ Primo Caffè',callback_data='oro_ora'),InlineKeyboardButton('🧠 Quiz',callback_data='quiz_ora')],
            [InlineKeyboardButton('🌙 Secondo Caffè',callback_data='oro_ora2')],
            [InlineKeyboardButton('⬅️ Rubrica',callback_data='rub_menu')]])); return
    if dato in ('quiz_carica','quiz_foto','quiz_ora'):
        context.user_data['oroscopo_modalita']=dato
        prompt={'quiz_carica':'📥 Invia il file JSON dei quiz (30 giornate con domanda, 4 risposte, corretta e approfondimento).', 'quiz_foto':'🖼 Invia una foto Telegram da utilizzare per il quiz quotidiano.', 'quiz_ora':'🕒 Invia il nuovo orario del quiz in formato HH:MM.'}[dato]
        await msg.reply_text(prompt,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Annulla',callback_data='quiz_menu')]])); return
    if dato=='quiz_toggle':
        c=configurazione_quiz()
        if not c['attivo']:
            oggi=datetime.now(ROMA_TZ).date().isoformat()
            with sqlite3.connect(DB_PATH,timeout=30) as db:
                disponibile=db.execute('SELECT 1 FROM quiz_giorni WHERE giorno>=? LIMIT 1',(oggi,)).fetchone()
            if not c['foto'] or not disponibile: raise ValueError('Prima carica foto e quiz per le prossime giornate.')
        imposta_quiz('attivo',not c['attivo']); await pannello_quiz(msg); return
    if dato.startswith('quiz_cal:'):
        # Elenco completo, comprese le date passate, come nel calendario oroscopo.
        try: pagina = max(0, int(dato.split(':', 1)[1]))
        except (ValueError, IndexError): pagina = 0
        with sqlite3.connect(DB_PATH, timeout=30) as db:
            righe = db.execute("SELECT g.giorno, u.stato FROM quiz_giorni g LEFT JOIN quiz_uscite u ON u.giorno=g.giorno ORDER BY g.giorno").fetchall()
        if not righe: raise ValueError('Nessun quiz caricato. Usa 📥 Carica quiz.')
        pagine = max(1, (len(righe) + 6) // 7)
        pagina = min(pagina, pagine - 1)
        bottoni = []
        for giorno, stato in righe[pagina*7:(pagina+1)*7]:
            simbolo = '✅' if stato == 'inviato' else ('⚠️' if stato else '👁')
            bottoni.append([InlineKeyboardButton(f'{simbolo} {giorno}', callback_data=f'quiz_det:{giorno}:{pagina}')])
        nav = []
        if pagina: nav.append(InlineKeyboardButton('⬅️ Precedenti', callback_data=f'quiz_cal:{pagina-1}'))
        if pagina + 1 < pagine: nav.append(InlineKeyboardButton('Successivi ➡️', callback_data=f'quiz_cal:{pagina+1}'))
        if nav: bottoni.append(nav)
        bottoni.append([InlineKeyboardButton('⬅️ Menu Quiz', callback_data='quiz_menu')])
        await msg.reply_text(f'📅 CALENDARIO QUIZ\nPagina {pagina+1}/{pagine} · {len(righe)} quiz\n\n👁 Da pubblicare · ✅ Pubblicato · ⚠️ Da verificare\n\nSeleziona una data per leggere domanda, risposte e spiegazione in privato.', reply_markup=InlineKeyboardMarkup(bottoni))
        return
    if dato.startswith('quiz_det:'):
        parti = dato.split(':')
        if len(parti) != 3: raise ValueError('Data quiz non valida.')
        _, giorno, pagina = parti
        with sqlite3.connect(DB_PATH, timeout=30) as db:
            r = db.execute('SELECT contenuto FROM quiz_giorni WHERE giorno=?', (giorno,)).fetchone()
            uscita = db.execute('SELECT stato FROM quiz_uscite WHERE giorno=?', (giorno,)).fetchone()
        if not r: raise ValueError('Quiz non trovato per questa data.')
        item = json.loads(r[0]); giusta = int(item['corretta'])
        righe = [f'🧠 QUIZ — {giorno}', f"❓ {item['domanda']}", '']
        for i, risposta in enumerate(item['risposte']):
            righe.append(f"{'✅ ' if i == giusta else '▫️ '}{risposta}")
        righe.extend(['', '📚 Spiegazione completa:', item['approfondimento'], '',
                      '📢 Stato: ' + (uscita[0] if uscita else 'non ancora pubblicato')])
        await msg.reply_text('\n'.join(righe), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('⬅️ Calendario quiz', callback_data=f'quiz_cal:{pagina}')],
            [InlineKeyboardButton('🧠 Menu Quiz', callback_data='quiz_menu')]]))
        return
    if dato=='quiz_preview':
        oggi=datetime.now(ROMA_TZ).date().isoformat()
        with sqlite3.connect(DB_PATH,timeout=30) as db:
            row=db.execute('SELECT giorno FROM quiz_giorni WHERE giorno>=? ORDER BY giorno LIMIT 1',(oggi,)).fetchone()
        if not row: raise ValueError('Carica prima il file quiz.')
        await invia_quiz(context.bot,msg.chat_id,row[0],anteprima=True)
        await msg.reply_text('👁 Anteprima privata: premi una risposta per leggere la spiegazione.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Quiz',callback_data='quiz_menu')]])); return
    if dato=='quiz_stats':
        with sqlite3.connect(DB_PATH,timeout=30) as db:
            tot,giuste,persone=db.execute('SELECT count(*),coalesce(sum(corretta),0),count(DISTINCT user_id) FROM quiz_voti').fetchone()
        await msg.reply_text(f'📊 QUIZ\n👥 Partecipanti unici: {persone}\n🗳 Risposte: {tot}\n✅ Corrette: {giuste}\n❌ Errate: {tot-giuste}\n🎯 Successo: {100*giuste/tot:.1f}%' if tot else '📊 Nessun voto registrato.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Quiz',callback_data='quiz_menu')]])); return

async def input_quiz(msg,context,modalita):
    if modalita=='quiz_foto':
        if not msg.photo: raise ValueError('Invia una foto Telegram, non un documento.')
        imposta_quiz('foto',msg.photo[-1].file_id)
    elif modalita=='quiz_ora':
        ora=(msg.text or '').strip()
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',ora): raise ValueError('Usa HH:MM, per esempio 17:00.')
        imposta_quiz('ora',ora)
    elif modalita=='quiz_carica':
        if not msg.document or not (msg.document.file_name or '').lower().endswith('.json'): raise ValueError('Allega il file .json.')
        if (msg.document.file_size or 0)>1_000_000: raise ValueError('File troppo grande (max 1 MB).')
        f=await msg.document.get_file(); dati=await f.download_as_bytearray()
        giorni=valida_file_quiz(bytes(dati).decode('utf-8-sig'))
        with sqlite3.connect(DB_PATH,timeout=30) as db:
            # I quiz già pubblicati o prenotati non vengono mai alterati.
            bloccati = {r[0] for r in db.execute('SELECT giorno FROM quiz_uscite WHERE giorno IN (' + ','.join('?' for _ in giorni) + ')', tuple(giorni))}
            aggiornabili = [(g, json.dumps(item, ensure_ascii=False)) for g,item in giorni.items() if g not in bloccati]
            if aggiornabili:
                db.executemany('INSERT OR REPLACE INTO quiz_giorni VALUES (?,?)', aggiornabili)
        await msg.reply_text(f'✅ Quiz caricati/aggiornati: {len(aggiornabili)} su {len(giorni)}.\n🔒 Già pubblicati o prenotati, lasciati invariati: {len(bloccati)}.\n📅 Dal {min(giorni)} al {max(giorni)}.\nControlla tutto da 📅 Calendario quiz.')
    context.user_data.pop('oroscopo_modalita',None)
    await pannello_quiz(msg)

async def invia_quiz(bot,chat_id,g,anteprima=False):
    c=configurazione_quiz()
    if not c['foto']: raise ValueError('Imposta prima la foto del quiz.')
    with sqlite3.connect(DB_PATH,timeout=30) as db:
        row=db.execute('SELECT contenuto FROM quiz_giorni WHERE giorno=?',(g,)).fetchone()
    if not row: raise ValueError('Quiz mancante per '+g)
    item=json.loads(row[0])
    return await bot.send_photo(chat_id=chat_id,photo=c['foto'],caption=f"🧠 QUIZ\n📅 {datetime.strptime(g, '%Y-%m-%d').strftime('%d/%m/%Y')}\n\n⚡ La sfida del giorno!\nQuattro risposte, una sola corretta. Riuscirai a indovinarla?\n\n❓ {item['domanda']}",reply_markup=tastiera_quiz(g))

async def pubblica_quiz(app, adesso=None):
    return await quiz_multicanale.pubblica(_servizi_invii, app, adesso)

async def controlla_quiz(app):
    while True:
        try:
            c=configurazione_quiz()
            if c['attivo']:
                with sqlite3.connect(DB_PATH,timeout=30) as db:
                    r=db.execute('SELECT max(giorno) FROM quiz_giorni').fetchone()
                if r and r[0]:
                    ultimo=r[0]; scadenza=datetime.fromisoformat(f"{ultimo}T{c['ora']}").replace(tzinfo=ROMA_TZ)
                    adesso=datetime.now(ROMA_TZ)
                    if timedelta(0)<=scadenza-adesso<=timedelta(hours=24) and c.get('promemoria')!=ultimo and ADMIN_ID:
                        await app.bot.send_message(chat_id=ADMIN_ID,text=f'⏰ PROMEMORIA QUIZ\n\n📅 Ultimo quiz disponibile: {datetime.strptime(ultimo, "%Y-%m-%d").strftime("%d/%m/%Y")} alle {c["ora"]}.\n\n📥 Mancano meno di 24 ore alla conclusione del ciclo: carica il nuovo file JSON da 30 giorni tramite ☕ Rubrica → 🧠 Quiz → Carica quiz.')
                        imposta_quiz('promemoria',ultimo)
            await pubblica_quiz(app)
        except Exception as e: print('Errore quiz:',type(e).__name__,str(e)[:300])
        await asyncio.sleep(30)


def main():

    inizializza_oroscopi()
    inizializza_quiz()
    inizializza_pause_caffe()
    inizializza_programmazioni()
    inizializza_recap()
    inizializza_automazione()
    inizializza_tiktok()
    ARCHIVIO.inizializza(list(CANALI.values()), config_fascia_manuale())
    avvia_api_offerte_web()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .post_init(avvia_programmazioni)
        .build()
    )

    app.add_handler(TypeHandler(Update, proteggi_menu_v2), group=-2)

    # Intercetta solo la rubrica; gli altri flussi mantengono i propri handler.
    app.add_handler(TypeHandler(Update, interazioni_pubbliche_rubrica), group=-1)

    app.add_handler(CallbackQueryHandler(
        storico_prezzi_non_disponibile, pattern="^offer_price_unavailable$"
    ))

    conversazione = ConversationHandler(

        entry_points=[
            CallbackQueryHandler(gestisci_menu_v2, pattern=r'^v2(?:_|c:)'),
            CallbackQueryHandler(gestisci_automatico_v2, pattern=r'^v2a:'),
            CallbackQueryHandler(gestisci_rubrica_v2, pattern=r'^v2r:'),
            CallbackQueryHandler(ricontrolla_da_cronologia, pattern=r'^archive_recheck_[0-9]+$'),

            CallbackQueryHandler(repost_da_pulsante, pattern='^repost$'),


            CommandHandler(
                "nuova",
                nuova_da_comando,
            ),

            CommandHandler("multiplo", rapido_da_comando),
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
            aggiunta_canale.INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_nuovo_canale_v2)],
            rubrica.INPUT: [MessageHandler((filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, ricevi_rubrica_v2)],
            AUTO_INTERVALLO: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_intervallo_automatico'))],
            AUTO_FASCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_fascia_automatica'))],
            FILTRO_MARCHIO_AGGIUNGI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_modifica_filtro'))],
            FILTRO_MARCHIO_RIMUOVI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_modifica_filtro'))],
            FILTRO_PAROLA_AGGIUNGI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_modifica_filtro'))],
            FILTRO_PAROLA_RIMUOVI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_modifica_filtro'))],
            PRIORITA_AGGIUNGI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_modifica_priorita'))],
            PRIORITA_RIMUOVI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_modifica_priorita'))],
            PRIORITA_ACCESSORIO_AGGIUNGI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_modifica_priorita'))],
            PRIORITA_ACCESSORIO_RIMUOVI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_automatico_v2('ricevi_modifica_priorita'))],
            menu_canali.INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_impostazione_v2)],

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
                    pattern="^(dati_ok|dati_manual|dati_riprova)$",
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
                CallbackQueryHandler(decidi_ricontrollo_cronologia,pattern=r'^hist_(pubblica|programma|annulla)$'),
                CallbackQueryHandler(gestisci_multiplo, pattern=r"^multi_(?:canale_(?:tech|casa)|timing|personalizzato|min_(?:10|20|30|40|60)|avvia|annulla)$"),
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

    # Registrata sotto, dopo aver unificato gli stati di Programmati.

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

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_fascia_manuale, pattern=r'^mf_(menu|toggle|inizio|fine)$')],
        states={'FASCIA_ORARIO':[MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_fascia_manuale)]},
        fallbacks=[CommandHandler('annulla',annulla),CallbackQueryHandler(mostra_menu_pubblicazione,pattern='^publish_menu$')],
        allow_reentry=True,
    ))

    app.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(menu_orario_recap, pattern=r'^recap_time_menu$'),
            CallbackQueryHandler(seleziona_orario_recap, pattern=r'^recap_time_(?:custom|\d{4})$'),
        ],
        states={RECAP_ORARIO_ATTESA: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_orario_recap),
            CallbackQueryHandler(seleziona_orario_recap, pattern=r'^recap_time_(?:custom|\d{4})$'),
        ]},
        fallbacks=[CommandHandler('annulla', annulla)],
        allow_reentry=True,
    ))

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
    app.add_handler(CallbackQueryHandler(mostra_log_diagnostici, pattern=r"^diag_logs_(?:all|errors|amazon)_\d+$"))
    app.add_handler(CallbackQueryHandler(esporta_log_diagnostici, pattern=r"^diag_export_(?:all|errors|amazon)$"))
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
            pattern=r"^(archive_all|archive_page_[0-9]+|archive_filter_(tech|casa|tutti|automatico|manuale)|archive_period_(oggi|7|30|tutto)|archive_size_(5|10|50|100)|archive_clear_search)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(mostra_scheda_archivio, pattern=r"^archive_view_[0-9]+$")
    )

    app.add_handler(CallbackQueryHandler(opzioni_cronologia,pattern=r'^archive_(size|period)_menu$'))
    app.add_handler(CallbackQueryHandler(precedenti_cronologia,pattern=r'^archive_previous_[0-9]+_[0-9]+$'))
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

    # Un solo stato per utente: entrando in Programmati si esce da RAPIDO.
    conversazione.entry_points.extend(gestione_programmati.entry_points)
    conversazione.states.update(gestione_programmati.states)
    app.add_handler(conversazione)


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


    app.add_handler(CallbackQueryHandler(casa_in_costruzione, pattern="^casa_costruzione$"))
    app.add_handler(CallbackQueryHandler(community_info, pattern="^community_info$"))

    app.add_handler(
        CallbackQueryHandler(
            torna_menu_utente,
            pattern="^menu_utente$",
        )
    )


    print(
        "🤖 BestPrice24h Offer Bot avviato"
    )

    app.run_polling()


if __name__ == "__main__":
    main()


