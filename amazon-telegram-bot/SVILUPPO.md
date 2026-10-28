# Stato dello sviluppo

## Funzioni disponibili

- Invio singolo, multiplo e repost nei moduli condivisi.
- Scelta canale, cronologia e code con apertura tramite numero digitato.
- Configurazioni automatiche indipendenti per ciascun canale.
- Marchi, parole escluse, priorità e anti-accessori separati, con migrazione non distruttiva dei valori legacy.
- Pannelli automatici originali: categorie, intervalli, fasce, sconti, qualità, selettiva, priorità, duplicati e varianti.
- Rubrica legacy: gestione oroscopi, quiz, calendari, caricamenti, foto, statistiche ed esportazioni.
- Destinazioni dell'oroscopo estese ai canali aggiunti; testi e orari restano condivisi come nel legacy, quiz dedicato a TECH.
- Aggiunta guidata del canale con verifica dei permessi Telegram, conferma e persistenza.
- Pulsanti dei pannelli legacy vincolati al canale; rifiuto di pannelli precedenti di altri canali.
- I job automatici usano la propria configurazione e destinazione, indipendentemente dal menu aperto.

## Validazione

36 test senza invii reali, inclusa navigazione con gli handler Telegram,
modifica dei filtri separati tra TECH, CASA e SPORT, aggiunta del canale,
caricamento degli oroscopi, programmazione e pubblicazione simulate.
Verificato anche l'isolamento del contesto tra ricerche concorrenti.

## Limiti

- La sorgente Creators API è disabilitata nel codice legacy: `get_items` e
  `search_items` restituiscono liste vuote. Il nuovo menu lo mostra e non
  permette di attivare una ricerca priva di sorgente.
- TikTok non è ancora nel nuovo menu.
- Nessun accesso diretto al database o al servizio di produzione, nessun
  invio reale durante le verifiche.
- Il progetto precedente in `amazon-telegram-bot-legacy` rimane invariato.

Istruzioni complete in [README.md](README.md).
