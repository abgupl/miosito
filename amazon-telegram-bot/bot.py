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


def estrai_prodotti(risposta_api):
    """Estrae i campi utili dalla risposta JSON della PA-API."""
    prodotti = []
    items = risposta_api.get("SearchResult", {}).get("Items", [])

    for item in items:
        try:
            title = item["ItemInfo"]["Title"]["DisplayValue"]
            image_url = item["Images"]["Primary"]["Large"]["URL"]
            product_url = item["DetailPageURL"]

            listing = item["Offers"]["Listings"][0]
            price_info = listing["Price"]
            price = price_info["DisplayAmount"]

            old_price = None
            discount_percent = 0
            saving_basis = listing.get("SavingBasis")
            if saving_basis:
                old_price = saving_basis["DisplayAmount"]
                try:
                    price_val = price_info["Amount"]
                    old_val = saving_basis["Amount"]
                    if old_val > 0:
                        discount_percent = round((1 - price_val / old_val) * 100)
                except (KeyError, ZeroDivisionError):
                    discount_percent = 0

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
        except (KeyError, IndexError):
            # Prodotto senza dati sufficienti (es. niente offerta attiva): salta
            continue

    return prodotti


def main():
    termine = random.choice(config.SEARCH_TERMS)
    print(f"Cerco prodotti per: {termine}")

    risposta = search_items(termine, search_index=config.SEARCH_INDEX)
    prodotti = estrai_prodotti(risposta)

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
