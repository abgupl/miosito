"""
Script principale: cerca prodotti in offerta tra le categorie configurate
e pubblica quelli che superano lo sconto minimo sul canale Telegram.

Esegui manualmente con: python bot.py
In produzione viene lanciato automaticamente da GitHub Actions (vedi
.github/workflows/post_offers.yml).
"""

import random
import sys

import config
from amazon_client import search_items
from telegram_client import post_product


def estrai_prodotti(items):
    """Estrae i campi utili dagli oggetti prodotto restituiti dalla libreria."""
    prodotti = []

    for item in items:
        try:
            title = item.item_info.title.display_value
            image_url = item.images.primary.large.url
            product_url = item.detail_page_url

            listing = item.offers.listings[0]
            price_val = listing.price.amount
            price = f"{price_val:.2f} {listing.price.currency}"

            old_price = None
            discount_percent = 0
            saving_basis = getattr(listing, "saving_basis", None)
            if saving_basis and saving_basis.amount:
                old_val = saving_basis.amount
                old_price = f"{old_val:.2f} {saving_basis.currency}"
                if old_val > 0:
                    discount_percent = round((1 - price_val / old_val) * 100)

            prodotti.append(
                {
                    "title": title,
                    "price": price,
                    "old_price": old_price,
                    "discount_percent": discount_percent,
                    "image_url": image_url,
                    "product_url": product_url,
                }
            )
        except (AttributeError, IndexError, TypeError):
            # Prodotto senza dati sufficienti (es. niente offerta attiva): salta
            continue

    return prodotti


def main():
    termine = random.choice(config.SEARCH_TERMS)
    print(f"Cerco prodotti per: {termine}")

    items = search_items(termine, search_index=config.SEARCH_INDEX)
    prodotti = estrai_prodotti(items)

    candidati = [
        p for p in prodotti if p["discount_percent"] >= config.MIN_DISCOUNT_PERCENT
    ]

    if not candidati:
        print("Nessun prodotto trovato con lo sconto minimo richiesto. Esco.")
        sys.exit(0)

    random.shuffle(candidati)
    da_pubblicare = candidati[: config.PRODUCTS_PER_RUN]

    for prodotto in da_pubblicare:
        print(f"Pubblico: {prodotto['title']} ({prodotto['discount_percent']}%)")
        post_product(
            title=prodotto["title"],
            price=prodotto["price"],
            old_price=prodotto["old_price"],
            discount_percent=prodotto["discount_percent"],
            image_url=prodotto["image_url"],
            product_url=prodotto["product_url"],
        )

    print("Fatto.")


if __name__ == "__main__":
    main()
