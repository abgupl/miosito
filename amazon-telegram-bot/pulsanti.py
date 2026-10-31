"""Formato comune delle etichette; callback e URL rimangono invariati."""
from telegram import InlineKeyboardButton as TelegramButton


def etichetta(testo):
    testo = testo.lower()
    for index, character in enumerate(testo):
        if character.isalpha():
            return testo[:index] + character.upper() + testo[index+1:]
    return testo


class InlineKeyboardButton(TelegramButton):
    __slots__ = ()

    def __init__(self, text, *args, **kwargs):
        super().__init__(etichetta(text), *args, **kwargs)


from telegram import InlineKeyboardMarkup as TelegramMarkup


def normalizza_righe(rows, button_class=InlineKeyboardButton):
    """Un solo ritorno contestuale; frecce di paginazione e annullamenti restano azioni."""
    if any(not hasattr(b, "text") for row in rows for b in row):
        return rows
    def ritorno(button):
        text = button.text.lower()
        return (('⬅' in text and not any(x in text for x in ('precedent', 'recenti')) and text.strip() != '⬅️')
                or 'menu principale' in text or 'scelta canale' in text)
    candidates = [b for row in rows for b in row if ritorno(b)]
    chosen = next((b for b in candidates if b.callback_data not in {'v2_home', 'menu_admin'}),
                  candidates[0] if candidates else None)
    result = []
    for row in rows:
        kept = []
        for button in row:
            if ritorno(button):
                if button is not chosen:
                    continue
                payload = button.to_dict()
                payload['text'] = '⬅️ Indietro'
                button = button_class.de_json(payload, None)
            kept.append(button)
        if kept:
            result.append(kept)
    return result


class InlineKeyboardMarkup(TelegramMarkup):
    __slots__ = ()

    def __init__(self, inline_keyboard, **kwargs):
        super().__init__(normalizza_righe(inline_keyboard), **kwargs)
