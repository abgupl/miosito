"""Adatta le schermate legacy senza mutare gli oggetti Telegram originali."""
from canali import selezionato
from functools import wraps


def tastiera_scoped(s, markup, namespace, channel):
    if markup is not None and not hasattr(markup, 'inline_keyboard'):
        return markup
    rows = []
    for row in (markup.inline_keyboard if markup else []):
        result = []
        for button in row:
            data = button.callback_data
            if not isinstance(data, str) or data.startswith(('oro_segno:', 'quiz_r:', 'v2')) or data == 'offer_price_unavailable':
                result.append(button)
                continue
            if data == 'menu_admin' or (data == 'publish_menu' and ('principale' in button.text.lower() or namespace == 'v2r')):
                scoped = 'v2_home'
            elif data == 'publish_menu':
                scoped = 'v2c:' + channel + ':menu'
            elif data == 'settings_menu':
                scoped = 'v2_settings'
            elif data == 'auto_channels':
                scoped = 'v2c:' + channel + ':menu'
            elif namespace == 'v2m':
                scoped = data
            else:
                scoped = namespace + ':' + channel + ':' + data
            if len(scoped.encode('utf-8')) > 64:
                raise ValueError('Identificativo pulsante troppo lungo per Telegram.')
            payload = button.to_dict()
            payload['callback_data'] = scoped
            if data == 'auto_channels':
                payload['text'] = '⬅️ Menu canale'
            result.append(s.InlineKeyboardButton.de_json(payload, None))
        rows.append(result)
    callbacks = [b.callback_data or '' for row in rows for b in row]
    has_back = any(('⬅' in b.text or 'menu principale' in b.text.lower())
                   for row in rows for b in row)
    if not has_back:
        target = ('v2a:' + channel + ':auto_menu' if namespace == 'v2a' else
                  'v2r:global:rub_menu' if namespace == 'v2r' else
                  'v2_add_back' if channel == 'global' else 'v2c:' + channel + ':menu')
        rows.append([s.InlineKeyboardButton('⬅️ Indietro', callback_data=target)])
    from pulsanti import normalizza_righe
    return s.InlineKeyboardMarkup(normalizza_righe(rows, s.InlineKeyboardButton))


class OggettoScoped:
    def __init__(self, original, s, namespace, channel):
        self.original, self.s, self.namespace, self.channel = original, s, namespace, channel

    def __getattr__(self, name):
        value = getattr(self.original, name)
        if name == 'message' and value is not None:
            return OggettoScoped(value, self.s, self.namespace, self.channel)
        if callable(value) and (name.startswith('reply_') or name.startswith('edit_')):
            async def call(*args, **kwargs):
                if name in {'reply_text', 'reply_photo', 'reply_document', 'edit_text', 'edit_caption', 'edit_message_text', 'edit_reply_markup', 'edit_message_reply_markup'}:
                    kwargs['reply_markup'] = tastiera_scoped(self.s, kwargs.get('reply_markup'), self.namespace, self.channel)
                returned = await value(*args, **kwargs)
                # Follow-up edits, including progress screens, remain scoped.
                if returned is not None and hasattr(returned, 'reply_text'):
                    return OggettoScoped(returned, self.s, self.namespace, self.channel)
                return returned
            return call
        return value


class UpdateScoped:
    def __init__(self, update, s, namespace, channel, data=None):
        self.original, self.s, self.namespace, self.channel = update, s, namespace, channel
        self._data = data

    def __getattr__(self, name):
        value = getattr(self.original, name)
        if value is not None and name in {'message', 'effective_message', 'callback_query'}:
            proxy = OggettoScoped(value, self.s, self.namespace, self.channel)
            if name == 'callback_query' and self._data is not None:
                proxy.data = self._data
            return proxy
        return value


async def verifica(s, update, context, namespace):
    if not await s.controlla_autorizzazione(update):
        return None
    channel = selezionato(context, s.CANALI, update.effective_user.id)
    data = update.callback_query.data if update.callback_query else ''
    prefix = namespace + ':' + (channel.chiave if channel else '') + ':'
    if channel is None or not data.startswith(prefix):
        if update.callback_query:
            await update.callback_query.answer('Questa schermata non appartiene al canale corrente.', show_alert=True)
        return None
    return channel, data[len(prefix):]


def navigabile(function):
    """Mantiene un'uscita nei flussi manuali senza cambiare i callback esistenti."""
    @wraps(function)
    async def wrapped(s, update, context, *args, **kwargs):
        channel = s.canale_corrente(context) if hasattr(s, 'canale_corrente') else None
        if channel and hasattr(s, 'InlineKeyboardButton') and not isinstance(update, UpdateScoped):
            update = UpdateScoped(update, s, 'v2m', channel.chiave)
        return await function(s, update, context, *args, **kwargs)
    return wrapped


def navigazione_coordinatore(function):
    @wraps(function)
    async def wrapped(update, context):
        import sys
        s = sys.modules[function.__module__]
        channel = s.canale_corrente(context)
        if channel and not isinstance(update, UpdateScoped):
            update = UpdateScoped(update, s, 'v2m', channel.chiave)
        return await function(update, context)
    return wrapped
