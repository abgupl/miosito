# BestPrice24h V2

## Stato attuale

Questa cartella è una copia indipendente dei file del progetto originale
`../amazon-telegram-bot/`, creata come base per la riorganizzazione.
Il codice originale non è stato modificato. Il README copiato descrive
il funzionamento ereditato; la separazione in moduli non è ancora implementata.

## Struttura prevista

| File | Responsabilità |
|---|---|
| manual_bot.py | Avvio, autorizzazioni, selezione canale e menu |
| invio_singolo.py | Preparazione e invio del singolo post |
| invio_multiplo.py | Preparazione e gestione delle sequenze |
| repost.py | Candidati dalla cronologia del solo canale selezionato |
| canali.py | Canali e accessi autorizzati |
| database.py | Persistenza e migrazioni, isolamento per canale |
| pubblicazione.py | Invio condiviso e registrazione dell'esito |

Non creare moduli vuoti: estrarre le funzioni effettive e aggiornare i
collegamenti durante la riorganizzazione.

## Menu concordato

Prima schermata: scelta del canale e Impostazioni generali.
Dentro il canale: Nuovi post (singolo/multiplo), Repost, Programmati e code,
Cronologia, Impostazioni canale, Cambia canale.

Cronologia, code, impostazioni e repost devono essere associati esplicitamente
al canale. Ogni lavoro programmato deve conservare la destinazione originale
indipendentemente dal canale aperto nel menu.

## Avvio e dati

Il servizio esistente continua a utilizzare la cartella originale.
Questa modifica non cambia configurazione o comando di avvio del servizio.

Per avviare la copia usare come directory di lavoro `amazon-telegram-bot-v2`
e comando `python manual_bot.py`, dopo aver installato `requirements.txt`.
Usare un bot Telegram di test distinto mentre il vecchio bot è attivo.
Impostare `CLUB_DB_PATH` su un database separato per le prove, senza
riutilizzare il percorso del database di produzione.

Il database non è presente nel repository: la copia dei file non trasferisce
cronologia e impostazioni del servizio. La migrazione dei dati e il passaggio
in produzione saranno gestiti separatamente.
