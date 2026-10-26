"""BestPrice24h: safe, shared Telegram publication gateway (phase 1).

No fallback to TECH. Caller must provide an explicit, registered, enabled channel.
This module does not change historical database records or configure automations.
"""
from dataclasses import dataclass
import bestprice_channels as registry


class ChannelRoutingError(ValueError):
    """Publication refused because its destination is not valid."""


@dataclass(frozen=True)
class Destination:
    chat_id: str
    display_name: str


def resolve_destination(db_path, channel, *, legacy_tech_id=None, legacy_casa_id=None):
    """Resolve legacy keys or registered chat IDs, rejecting unknown/disabled channels."""
    if channel is None or not str(channel).strip():
        raise ChannelRoutingError('Canale di destinazione non selezionato')
    value = str(channel).strip()
    registered = registry.channels(db_path)
    for entry in registered:
        if value == str(entry['chat_id']) or value == str(entry.get('legacy_key') or ''):
            return Destination(str(entry['chat_id']), str(entry['display_name']))
    # Do not accept a channel merely because it matches an environment variable:
    # it must be in the enabled registry.
    raise ChannelRoutingError('Canale inesistente o disattivato: invio bloccato')


def active_destination(db_path, admin_id):
    active = registry.active_channel(db_path, admin_id)
    if active is None:
        raise ChannelRoutingError('Seleziona prima un canale')
    return resolve_destination(db_path, active['chat_id'])


async def send_offer(bot, db_path, channel, *, text, photo=None, parse_mode='HTML', reply_markup=None):
    """Single verified send for both text and photo offers.

    Returns the Telegram Message; DB/history updates remain with the caller.
    """
    destination = resolve_destination(db_path, channel)
    if not text or not str(text).strip():
        raise ValueError('Testo offerta mancante')
    if photo:
        message = await bot.send_photo(
            chat_id=destination.chat_id, photo=photo, caption=text,
            parse_mode=parse_mode, reply_markup=reply_markup,
        )
    else:
        message = await bot.send_message(
            chat_id=destination.chat_id, text=text,
            parse_mode=parse_mode, reply_markup=reply_markup,
        )
    return message
