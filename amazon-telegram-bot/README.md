# BestPrice24h — V2 multicanale

La V2 è separata dal progetto originale in `../amazon-telegram-bot-legacy/`.
Il punto di avvio rimane `manual_bot.py`.

## Menu

`/start` mostra i canali disponibili all'amministratore, **☕ Rubrica** e **Impostazioni generali**.
Dopo la selezione, il menu del canale contiene:

- Nuovi post: invio singolo e multiplo.
- Repost: ricerca casuale nella cronologia del solo canale corrente.
- Invio automatico: gestione dei filtri e delle impostazioni legacy, indipendenti per canale.
- Programmati e code: elenco, dettagli, modifica e annullamento dei post in attesa.
- Cronologia: pubblicazioni del canale, con dettagli e paginazione.
- Impostazioni canale: intervallo, fascia oraria, tag affiliato e verifica dei permessi Telegram.
- Cambia canale.

Dopo gli elenchi di cronologia e programmati il bot chiede quale # aprire:
si digita il numero (123 oppure #123), senza pulsanti per i singoli risultati.
Il numero viene cercato solo nel canale selezionato.

Le impostazioni generali mostrano tag predefinito, fuso orario, canali configurati,
stato e diagnostica. I nuovi canali si aggiungono dal bot; gli amministratori globali restano configurati nelle variabili del servizio. La verifica dei permessi Telegram è esplicita: una configurazione
presente non viene mostrata automaticamente come collegamento verificato.

## Link accettati

Singolo e multiplo usano lo stesso filtro in `link_amazon.py`.
Sono ammessi link HTTP/HTTPS diretti Amazon e link brevi `amzn.eu`,
`amzn.to`, `a.co`, `link.amazon` e `link.amazon.it`, oltre ai domini
Amazon esteri come `amazon.de` e `amazon.com`. Il link deve condurre a un
prodotto identificabile: l'accettazione del dominio non garantisce la lettura.
La lettura corrente dei prodotti continua a usare Amazon Italia.

## Invii e isolamento

La scelta del canale appartiene al singolo amministratore. Cambiare schermata
annulla le bozze e i timer dei lotti non ancora confermati; le code già salvate
continuano sulla destinazione originale. I pulsanti di una schermata appartenente
a un altro canale vengono rifiutati.

Anche **Pubblica ora** inserisce il post nella coda del canale: se lo spazio è
libero esce entro circa 30 secondi, altrimenti al primo slot consentito.
Gli invii rispettano fascia oraria e distanza minima. Multiplo e repost mantengono
l'avvio automatico dopo due minuti dal riepilogo, salvo annullamento.

Il repost legge gli ultimi 7, 30 o 90 giorni, secondo l'impostazione del canale.
Esclude raccolte, prodotti pubblicati nelle ultime 24 ore e quelli già in coda
nello stesso canale. Rilegge le pagine Amazon e richiede uno sconto o coupon
attuale. La scelta è casuale con priorità per i prodotti con nome e foto salvati.
La ricerca si avvia su richiesta: non è un nuovo servizio di repost ricorrente.

## Ricerca automatica per canale

Il motore di ricerca, il calcolo dei punteggi e i filtri derivano dal
`manual_bot.py` legacy. Ogni canale conserva separatamente attivazione,
intervallo, fascia automatica, categorie, sconto minimo, modalità qualità,
punteggio, bonus sconto, priorità Amazon, raggruppamento varianti e duplicati.
Anche marchi, parole escluse, prodotti prioritari e parole anti-accessorio
sono indipendenti. Un ripristino o una modifica disattiva soltanto l'automazione
del canale corrente.

Al primo utilizzo le regole vengono copiate dai dati legacy in un archivio
dedicato al canale. Le copie sono indipendenti; i dati originali non vengono
modificati. Il motore condivide solo il codice: ogni ricerca riceve il canale
esplicitamente e usa le sue regole, anche quando più ricerche sono concorrenti.

**Limite ereditato:** nel legacy `get_items()` e `search_items()` restituiscono
liste vuote perché la Creators API è disabilitata. Il nuovo menu lo segnala e
impedisce di attivare una ricerca senza sorgente. Questa modifica recupera
gestione, filtri e pianificazione; non ripristina il collegamento API mancante.

## Rubrica legacy

La rubrica si apre direttamente dalla prima schermata, senza scegliere un
canale. Quiz e oroscopi hanno un'unica gestione condivisa; anche il ritorno
al menu porta alla prima schermata. Il pulsante non è nei menu dei canali.

Sono nuovamente disponibili calendario, caricamento e modifica oroscopi,
foto, anteprima, due orari, attivazione, statistiche e CSV. Il quiz mantiene
caricamento JSON, foto, calendario, orario, anteprima e statistiche del legacy.
Quiz e oroscopo hanno testi, grafica, orari e attivazione condivisi e vengono
pubblicati su tutti i canali configurati, inclusi quelli aggiunti in futuro.
Ogni invio del quiz è registrato per giorno e canale, senza ripetizioni dopo
un riavvio; gli invii storici TECH vengono conservati. Le pause offerte e il
riconoscimento delle risposte ufficiali al quiz funzionano su tutti i canali.
Le pause offerte di 30 minuti e i controlli contro gli invii duplicati restano
quelli precedenti. La gestione della rubrica condivisa richiede accesso a tutti
i canali; i pulsanti pubblici per segni zodiacali e risposte al quiz restano attivi.

## Aggiungere un canale dal bot

Aprire **Impostazioni generali → Aggiungi canale** e inserire nome, chiave univoca
e @username o ID -100…. Il bot verifica che la destinazione sia un canale e che
disponga del permesso di pubblicazione, poi chiede conferma. Il registro viene
salvato nel database e ricaricato al riavvio. I canali aggiunti riusano gli stessi
moduli, con cronologia, code, regole e configurazione automatiche indipendenti.
La selezione delle categorie automatiche avviene nel menu del nuovo canale.

## Struttura

| File | Responsabilità |
|---|---|
| `manual_bot.py` | Avvio, coordinamento, callback compatibili e servizi storici |
| `invio_singolo.py` | Preparazione, anteprima e conferma del singolo post |
| `invio_multiplo.py` | Preparazione lotti e pianificazione sequenze |
| `repost.py` | Selezione e verifica dei candidati dalla cronologia |
| `canali.py` | Registro, autorizzazioni per canale e selezione personale |
| `database.py` | Impostazioni e query con destinazione esplicita |
| `menu_canali.py` | Navigazione e configurazione V2 |
| `invio_automatico.py` | Gestione multicanale delle funzioni automatiche legacy |
| `filtri_canale.py` | Regole automatiche persistenti e isolate per canale |
| `rubrica.py` | Gestione dell'oroscopo e del quiz legacy |
| `aggiunta_canale.py` | Procedura guidata e verifica del nuovo canale |
| `interfaccia_legacy.py` | Adattamento dei pannelli legacy con pulsanti legati al canale |
| `assets/` | Loghi e font |
| `sito-web/` | Sito che legge l'API delle offerte |
| `tests/` | Verifiche senza invii reali |

## Avvio

Usare Python 3.11 o successivo e la cartella V2 come directory di lavoro:

```bash
pip install -r requirements.txt
python manual_bot.py
```

| Variabile | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot |
| `TELEGRAM_CHAT_ID` | Destinazione TECH |
| `TELEGRAM_CHAT_ID_CASA` | Destinazione CASA; predefinita `@BestPrice24hCasa` |
| `ADMIN_TELEGRAM_ID` | Amministratore principale |
| `ADMIN_TELEGRAM_IDS` | Eventuali altri amministratori, separati da virgola |
| `AMAZON_PARTNER_TAG` | Tag affiliato generale; alternativa `AMAZON_ASSOCIATE_TAG` |
| `CLUB_DB_PATH` | Database persistente della V2; predefinito `club.db` nella directory di lavoro |
| `BOT_CHANNELS_JSON` | Lista JSON facoltativa di ulteriori canali |
| `PORT` | Porta HTTP per l'API delle offerte |
| `RAILWAY_PUBLIC_DOMAIN` | Dominio pubblico per immagini e integrazioni |

Esempio di `BOT_CHANNELS_JSON`:

```json
[{"chiave":"sport","nome":"🏃 SPORT","chat_id":"@mio_canale_sport","admin_ids":[123456789]}]
```

`admin_ids` limita gli amministratori globali che possono gestire quel canale.
Se omesso, il canale è disponibile a tutti gli amministratori globali.
Chiavi e destinazioni duplicate vengono rifiutate.

## Dati e passaggio al servizio

La nuova versione occupa ora la cartella `amazon-telegram-bot`; il vecchio
codice è conservato intatto in `amazon-telegram-bot-legacy`. Un servizio che
segue automaticamente la cartella principale può quindi avviare la V2.
Per le prove usare un
token Telegram distinto e un database separato. Non avviare due processi con lo
stesso token. Il database del servizio non è incluso nel repository.

Impostazioni e cronologia sono conservate su SQLite. I nuovi valori per canale
vengono creati senza sovrascrivere quelli già salvati; la fascia iniziale viene
copiata dalla configurazione precedente. I vecchi record senza destinazione
vengono associati a TECH. Il database esistente può essere riutilizzato: mantenere
`CLUB_DB_PATH` invariata oppure usare `club.db` nella stessa directory di lavoro
di prima. Prima del primo avvio con la V2 conservare un backup. Il database deve
essere usato da una sola versione del bot alla volta.

Un invio acquisito dal worker passa a `in_invio`; un errore con esito incerto
viene segnalato come `da_verificare`, senza ripetizione automatica che potrebbe
duplicare il messaggio. Un invio già in corso non è più annullabile.

TikTok rimane nel coordinatore e non è ancora stato riportato nel nuovo menu.

## Verifiche

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

I test usano database temporanei e simulano Telegram e Amazon. Il test di
integrazione costruisce l'applicazione e attraversa gli handler Telegram reali,
senza polling e senza rete. Richiede le dipendenze di `requirements.txt`.

## Navigazione aggiornata

La schermata iniziale mostra, nell’ordine: lista canali; Aggiungi canale; Rubrica e Impostazioni affiancate. La rubrica è unica e globale, senza pulsanti duplicati nei menu dei canali.

Il ritorno dall’automazione apre il menu del canale; Menu principale apre sempre la lista iniziale. Le schermate di inserimento, i pannelli automatici, le anteprime e gli editor dispongono di pulsanti di uscita. L’aggiunta del canale consente di tornare al passo precedente senza perdere tutta la bozza.

Verifiche: 44 test, con navigazione degli handler reali su TECH, CASA e un canale SPORT simulato; nessun invio reale.
