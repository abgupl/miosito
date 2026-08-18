"""
Configurazione del bot.
Modifica qui le categorie/parole chiave da cercare e i parametri di ricerca.
"""

# Parole chiave o categorie da cercare su Amazon.
# Ogni ricerca produce candidati tra cui il bot ne sceglie uno a rotazione.
SEARCH_TERMS = [
    "offerte elettronica",
    "offerte informatica",
    "offerte casa e cucina",
    # Aggiungi/rimuovi le categorie che vuoi seguire
]

# Nodo di ricerca Amazon (opzionale). Lascialo vuoto per cercare in tutte le categorie.
SEARCH_INDEX = "All"

# Marketplace Amazon (cambia se non usi Amazon.it)
MARKETPLACE = "www.amazon.it"
PARTNER_TAG_ENV = "AMAZON_PARTNER_TAG"  # il tuo tag associato, letto da variabile d'ambiente
REGION = "eu-west-1"  # regione per l'endpoint EU (IT, ES, FR, DE, UK, ecc.)
HOST = "webservices.amazon.it"

# Sconto minimo (%) sotto il quale un prodotto NON viene pubblicato (0 = pubblica tutto)
MIN_DISCOUNT_PERCENT = 15

# Quanti prodotti pubblicare ad ogni esecuzione dello script
PRODUCTS_PER_RUN = 1
