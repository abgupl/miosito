# BestPrice24h V2

## Stato attuale

Questa cartella contiene la V2, separata dal progetto originale
`../amazon-telegram-bot/`, che rimane invariato.

Prima fase completata: 34 funzioni operative sono state estratte in tre moduli:
13 in `invio_singolo.py`, 15 in `invio_multiplo.py`, 6 in `repost.py`.
`manual_bot.py` conserva i callback pubblici con le firme originali e delega ai
moduli. I moduli ricevono esplicitamente il coordinatore come parametro
`servizi`: nessun import circolare e nessun avvio di Telegram durante l'import.

Database, pianificazione condivisa, pubblicazione e altre funzioni storiche
restano nel coordinatore in questa fase. Il menu è ancora quello originale.
La selezione iniziale del canale e l'isolamento delle impostazioni devono
ancora essere implementati. Non considerare questa fase una migrazione
multicanale completa.

## Struttura attuale e prevista

| File | Responsabilità |
|---|---|
| manual_bot.py | Coordinatore e callback compatibili; selezione iniziale canale da implementare |
| invio_singolo.py | Preparazione e invio del singolo post |
| invio_multiplo.py | Preparazione e gestione delle sequenze |
| repost.py | Candidati dalla cronologia del solo canale selezionato |
| canali.py (previsto) | Canali e accessi autorizzati |
| database.py (previsto) | Persistenza e migrazioni, isolamento per canale |
| pubblicazione.py (previsto) | Invio condiviso e registrazione dell'esito |

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

## Verifica della prima fase

Dalla cartella V2:

```bash
python -m compileall -q manual_bot.py invio_singolo.py invio_multiplo.py repost.py
python -m unittest discover -s tests -v
```

I 10 test usano un database temporaneo e simulano Telegram/Amazon:
non richiedono token e non effettuano chiamate di rete.
Coprono isolamento della cronologia e delle code repost, esclusioni temporali,
priorità dei metadati, verifica delle offerte attuali, autorizzazioni,
deleghe dei callback e conservazione della destinazione del lotto.

I comportamenti ereditati restano invariati, compreso l'avvio automatico del
lotto dopo due minuti dal riepilogo. Nessun test live o deploy è stato eseguito.
