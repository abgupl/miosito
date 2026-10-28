"""Adatta le schermate legacy senza mutare gli oggetti Telegram originali."""
from canali import selezionato


def tastiera_scoped(s, markup, namespace, channel):
    if markup is None or not hasattr(markup, 'inline_keyboard'):
        return markup
    rows = []
    for row in markup.inline_keyboard:
        result = []
        for button in row:
            data = button.callback_data
            if not isinstance(data, str) or data.startswith(('oro_segno:', 'quiz_r:', 'v2')) or data == 'offer_price_unavailable':
                result.append(button)
                continue
            if data in {'menu_admin', 'publish_menu'}:
                scoped = 'v2c:' + channel + ':menu'
            elif data == 'settings_menu':
                scoped = 'v2_settings'
            elif data == 'auto_channels':
                scoped = 'v2c:' + channel + ':automatic'
            else:
                scoped = namespace + ':' + channel + ':' + data
            if len(scoped.encode('utf-8')) > 64:
                raise ValueError('Identificativo pulsante troppo lungo per Telegram.')
            payload = button.to_dict()
            payload['callback_data'] = scoped
            result.append(s.InlineKeyboardButton.de_json(payload, None))
        rows.append(result)
    return s.InlineKeyboardMarkup(rows)


class OggettoScoped:
    def __init__(self, original, s, namespace, channel):
        self.original, self.s, self.namespace, self.channel = original, s, namespace, channel

    def __getattr__(self, name):
        value = getattr(self.original, name)
        if name == 'message' and value is not None:
            return OggettoScoped(value, self.s, self.namespace, self.channel)
        if callable(value) and (name.startswith('reply_') or name.startswith('edit_')):
            async def call(*args, **kwargs):
                if 'reply_markup' in kwargs:
                    kwargs['reply_markup'] = tastiera_scoped(self.s, kwargs['reply_markup'], self.namespace, self.channel)
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
