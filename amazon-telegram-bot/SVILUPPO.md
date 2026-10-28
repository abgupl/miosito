# Stato dello sviluppo

## Funzioni disponibili

- Invio singolo, multiplo e repost nei moduli condivisi.
- Scelta canale, cronologia e code con apertura tramite numero digitato.
- Configurazioni automatiche indipendenti per ciascun canale.
- Marchi, parole escluse, priorità e anti-accessori separati, con migrazione non distruttiva dei valori legacy.
- Pannelli automatici originali: categorie, intervalli, fasce, sconti, qualità, selettiva, priorità, duplicati e varianti.
- Rubrica condivisa nella prima schermata, senza selezione del canale: gestione oroscopi, quiz, calendari, caricamenti, foto, statistiche ed esportazioni.
- Quiz e oroscopo condivisi nella prima schermata, pubblicati su tutti i canali presenti e futuri; impostazioni uniche.
- Aggiunta guidata del canale con verifica dei permessi Telegram, conferma e persistenza.
- Pulsanti dei pannelli automatici vincolati al canale; rubrica con navigazione globale; rifiuto di pannelli precedenti di altri canali.
- I job automatici usano la propria configurazione e destinazione, indipendentemente dal menu aperto.

- Migrazione degli invii quiz legacy senza perdita di dati e tracciamento per giorno/canale.

## Validazione

39 test senza invii reali, inclusa navigazione con gli handler Telegram,
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
