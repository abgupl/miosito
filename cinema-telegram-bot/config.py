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
        admins = frozenset(int(x.strip()) for x in os.environ.get("CINEMA_ADMIN_IDS", "").split(",") if x.strip())
        if not token or not channel or not admins or not url.startswith("https://t.me/"):
            raise ValueError("Imposta CINEMA_BOT_TOKEN, CINEMA_CHANNEL_ID, CINEMA_CHANNEL_URL e CINEMA_ADMIN_IDS.")
        channel = int(channel) if channel.lstrip("-").isdigit() else channel
        path = Path(os.environ.get("CINEMA_DB_PATH", str(Path(__file__).parent / "data" / "cinema.sqlite3")))
        return cls(token, channel, url, admins, path, os.environ.get("CINEMA_SERVER", "017"))
