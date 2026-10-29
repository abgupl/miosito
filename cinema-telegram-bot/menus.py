"""Tutte le schermate protette hanno un ritorno esplicito al genitore."""
from dataclasses import dataclass
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup


@dataclass
class Screen:
    text: str
    rows: list
    parent: str | None = "home"
    photo: str = ""

    def markup(self):
        rows = [[Button(label, url=target[4:]) if target.startswith("url:") else Button(label, callback_data=target)] for row in self.rows for label, target in row]
        if self.parent is not None:
            rows.append([Button("⬅️ Indietro", callback_data=self.parent)])
        return InlineKeyboardMarkup(rows)


def home(channel_url, admin=False):
    rows = [
        [("🎬 Richiedi un film", "new:film"), ("📺 Richiedi una serie", "new:serie")],
        [("📋 Le mie richieste", "mine:0"), ("📲 Scarica le app", "platforms")],
        [("📖 Guida all’installazione", "guide")],
        [("🛠 Segnala un problema app", "reportapps:0")],
    ]
    if admin:
        rows.append([("🔧 Amministrazione", "admin")])
    return Screen("Scegli una funzione:", rows, None)
