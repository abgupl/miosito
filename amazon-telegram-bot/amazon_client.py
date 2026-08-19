"""
Client per Amazon Creators API.

Utilizza le nuove credenziali Amazon:
- Credential ID
- Credential Secret
- Version
- Partner Tag
"""

import os

from amazon_creatorsapi import AmazonCreatorsApi, Country

import config


def _get_client():
    credential_id = os.environ["AMAZON_CREDENTIAL_ID"]
    credential_secret = os.environ["AMAZON_CREDENTIAL_SECRET"]
    version = os.environ["AMAZON_CREDENTIAL_VERSION"]
    partner_tag = os.environ[config.PARTNER_TAG_ENV]

    return AmazonCreatorsApi(
        credential_id,
        credential_secret,
        version,
        partner_tag,
        Country.IT,
        throttling=1,
    )


def search_items(keywords, search_index="All", item_count=10):
    """
    Cerca prodotti su Amazon tramite Creators API
    e restituisce una lista di oggetti prodotto.
    """

    amazon = _get_client()

    risultato = amazon.search_items(
        keywords=keywords,
        search_index=search_index,
        item_count=item_count,
    )

    return getattr(risultato, "items", []) or []
