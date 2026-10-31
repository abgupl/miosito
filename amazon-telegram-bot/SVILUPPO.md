# Stato dello sviluppo

## Funzioni disponibili

- Invio unico da 1 a 50 link e repost nei moduli condivisi.
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

44 test senza invii reali, inclusa navigazione con gli handler Telegram,
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

## Navigazione aggiornata

La schermata iniziale mostra, nell’ordine: lista canali; Aggiungi canale; Rubrica e Impostazioni affiancate. La rubrica è unica e globale, senza pulsanti duplicati nei menu dei canali.

Il ritorno dall’automazione apre il menu del canale; Menu principale apre sempre la lista iniziale. Le schermate di inserimento, i pannelli automatici, le anteprime e gli editor dispongono di pulsanti di uscita. L’aggiunta del canale consente di tornare al passo precedente senza perdere tutta la bozza.

Verifiche: 44 test, con navigazione degli handler reali su TECH, CASA e un canale SPORT simulato; nessun invio reale.

## Recupero articoli solo su richiesta

Per tutti i canali, il lotto esegue una sola lettura con massimo tre tentativi per articolo. La seconda passata automatica dopo 20 secondi è rimossa. Il riepilogo conserva i link non letti e mostra il pulsante Riprova articoli non letti (N); il recupero riparte solo su pressione del pulsante, conserva i prodotti pronti e la destinazione e mantiene il controllo duplicati tra le passate. Finché ci sono non letti, e dopo un recupero manuale, il lotto richiede conferma esplicita. Nessun timer può avviarlo durante il recupero. Per lotti completamente riusciti al primo giro resta l'avvio dopo due minuti. Il riepilogo distingue link ricevuti, pronti, non letti, esclusi e duplicati.

Le anteprime automatiche dei link sono disabilitate tramite Defaults dell'applicazione Telegram, anche per riepiloghi e modifiche di messaggi; foto e anteprime richieste esplicitamente rimangono disponibili. Le nuove regole si applicano dopo il deploy e non riscrivono i vecchi messaggi. Validazione: 58 test, con controllo del pulsante e delle callback reali e isolamento TECH/CASA/SPORT; nessun invio reale.

## Invio unico

Il pulsante Invio del canale apre direttamente la preparazione da 1 a 50 link Amazon, uno per riga. Il modulo invio_singolo.py e i suoi handler sono rimossi. La logica comune resta in invio_multiplo.py, con tre tentativi massimi, recupero manuale dei non letti, controlli duplicati e destinazione per canale. I lotti interamente riusciti al primo giro mantengono l'avvio dopo due minuti; quelli con non letti o recuperati attendono conferma. Nessun nuovo editor prima della conferma viene aggiunto. La scelta giorno/orario usata da cronologia e ricerca è conservata nel coordinatore come funzione condivisa. /invio è il comando principale; i vecchi comandi /nuova, /multiplo, /rapido e il vecchio pulsante nuova aprono il medesimo flusso unico. Il separatore dei link è corretto per gli a capo e la lettera s negli URL. Rubrica, automatico, repost e archivio legacy restano preservati. Validazione: 57 test, inclusi flussi da uno e più link per TECH/CASA/SPORT, preparazione/programmazione reale con servizi esterni simulati e modifica di un programmato con foto.
