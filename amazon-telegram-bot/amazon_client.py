"""
Client per la Amazon Product Advertising API 5.0, basato sulla libreria
"python-amazon-paapi" (gestisce firma delle richieste, autenticazione ed
errori in modo affidabile, senza doverlo implementare a mano).
"""

import os
from amazon_paapi import AmazonApi

import config


def _get_client():
    access_key = os.environ["AMAZON_ACCESS_KEY"]
    secret_key = os.environ["AMAZON_SECRET_KEY"]
    partner_tag = os.environ[config.PARTNER_TAG_ENV]

    return AmazonApi(
        access_key,
        secret_key,
        partner_tag,
        config.COUNTRY,  # es. "IT"
        throttling=1,  # secondi di attesa tra le richieste, per stare nei limiti
    )


def search_items(keywords, search_index="All", item_count=10):
    """Cerca prodotti su Amazon e restituisce una lista di oggetti prodotto."""
    amazon = _get_client()
    risultato = amazon.search_items(
        keywords=keywords,
        search_index=search_index,
        item_count=item_count,
    )
    # La libreria restituisce un oggetto con l'attributo .items
    return getattr(risultato, "items", []) or []
