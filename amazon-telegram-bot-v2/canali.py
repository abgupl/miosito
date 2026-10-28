"""Registro canali e selezione per amministratore; nessuna destinazione globale mutabile."""
from dataclasses import dataclass
import json
import re


@dataclass(frozen=True)
class Canale:
    chiave: str
    nome: str
    chat_id: str
    admin_ids: tuple[str, ...] = ()

    def accessibile(self, user_id):
        return not self.admin_ids or str(user_id) in self.admin_ids


def carica_canali(env):
    elementi = [
        {'chiave': 'tech', 'nome': '💻 TECH', 'chat_id': env['TELEGRAM_CHAT_ID']},
        {'chiave': 'casa', 'nome': '🏠 CASA', 'chat_id': env.get('TELEGRAM_CHAT_ID_CASA', '@BestPrice24hCasa')},
    ]
    # La lista opzionale aggiunge categorie senza copiare il codice del bot.
    extra = json.loads(env.get('BOT_CHANNELS_JSON', '[]'))
    if not isinstance(extra, list):
        raise ValueError('BOT_CHANNELS_JSON deve essere una lista JSON')
    elementi.extend(extra)
    registro = {}
    destinazioni = set()
    for item in elementi:
        key = item['chiave']
        chat = str(item['chat_id']).strip()
        name = str(item['nome']).strip()
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,23}', key) or key in registro:
            raise ValueError('Chiave canale non valida o duplicata: ' + str(key))
        if not chat or not name or chat.casefold() in destinazioni:
            raise ValueError('Nome/destinazione canale mancanti o destinazione duplicata')
        admins = item.get('admin_ids', [])
        if not isinstance(admins, list):
            raise ValueError('admin_ids deve essere una lista')
        registro[key] = Canale(key, name, chat, tuple(str(a) for a in admins))
        destinazioni.add(chat.casefold())
    return registro


def selezionato(context, registro, user_id=None):
    channel = registro.get(context.user_data.get('canale_attivo'))
    if channel is not None and (user_id is None or channel.accessibile(user_id)):
        return channel
    return None


def reset_flusso(context):
    """Interrompe bozze/timer, conservando soltanto la selezione del canale."""
    key = context.user_data.get('canale_attivo')
    draft = context.user_data.get('multiplo')
    if draft:
        draft['annullato'] = True
        draft.pop('timer_token', None)
    context.user_data.clear()
    if key:
        context.user_data['canale_attivo'] = key


def chat_per_chiave(registro, key):
    # Nessun fallback silenzioso su TECH per categorie sconosciute.
    return registro[key].chat_id
