"""
Client minimale per pubblicare messaggi su un canale Telegram tramite Bot API.
"""

import os
import requests


def post_product(title, price, old_price, discount_percent, image_url, product_url):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]  # es. @nomecanale oppure ID numerico

    caption_lines = [f"🛒 *{title}*", ""]

    if discount_percent and discount_percent > 0:
        caption_lines.append(f"💥 -{discount_percent}%")
        caption_lines.append(f"~{old_price}~  ➜  *{price}*")
    else:
        caption_lines.append(f"💶 *{price}*")

    caption_lines.append("")
    caption_lines.append(f"[Vai all'offerta]({product_url})")

    caption = "\n".join(caption_lines)

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": image_url,
        "caption": caption,
        "parse_mode": "Markdown",
    }

    response = requests.post(url, data=payload, timeout=15)
    response.raise_for_status()
    return response.json()
