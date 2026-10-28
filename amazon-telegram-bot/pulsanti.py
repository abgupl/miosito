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
