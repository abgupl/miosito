"""Configurazione indipendente da Manual Bot, esclusivamente da ambiente."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    token: str
    channel: int | str
    channel_url: str
    admins: frozenset[int]
    database: Path
    server: str = "017"

    @classmethod
    def load(cls):
        token = os.environ.get("CINEMA_BOT_TOKEN", "").strip()
        channel = os.environ.get("CINEMA_CHANNEL_ID", "").strip()
        url = os.environ.get("CINEMA_CHANNEL_URL", "").strip()
        raw_admins = os.environ.get("CINEMA_ADMIN_IDS", "").strip()
        missing = [name for name, value in (
            ("CINEMA_BOT_TOKEN", token),
            ("CINEMA_CHANNEL_ID", channel),
            ("CINEMA_ADMIN_IDS", raw_admins),
        ) if not value]
        if missing:
            raise ValueError("Variabili mancanti: " + ", ".join(missing) + ".")
        try:
            admins = frozenset(int(x.strip()) for x in raw_admins.split(",") if x.strip())
        except ValueError:
            raise ValueError("CINEMA_ADMIN_IDS deve contenere ID numerici positivi separati da virgole.") from None
        if not admins or any(uid <= 0 for uid in admins):
            raise ValueError("CINEMA_ADMIN_IDS deve contenere ID numerici positivi separati da virgole.")
        # Compatibilità con le vecchie configurazioni: il link non è più richiesto né mostrato.
        channel = int(channel) if channel.lstrip("-").isdigit() else channel
        path = Path(os.environ.get("CINEMA_DB_PATH", str(Path(__file__).parent / "data" / "cinema.sqlite3")))
        return cls(token, channel, url, admins, path, os.environ.get("CINEMA_SERVER", "017"))
