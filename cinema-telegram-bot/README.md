# Bot cinema Telegram

Bot autonomo, separato da `amazon-telegram-bot/manual_bot.py`: token, processo e database propri. Python 3.10 o superiore.

## Primo avvio

1. Crea un nuovo bot con @BotFather e aggiungilo come amministratore al canale.
2. Imposta le variabili indicate in `.env.example` nell'ambiente del processo: token del nuovo bot, ID numerico del canale (oppure username pubblico), ID numerici degli amministratori separati da virgola. Anche gli amministratori devono essere iscritti al canale.
3. Dalla cartella `cinema-telegram-bot`:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python bot.py
```

Su Windows attivare `.venv\Scripts\activate`. Il file `.env.example` è un modello: il programma legge le variabili d'ambiente e non carica automaticamente file `.env`. Non inserire token o credenziali su GitHub.

Il bot gira sul tuo PC/server, con accesso a Telegram. GitHub conserva solo il codice: non lo esegue. Per uso continuativo mantenere il processo attivo tramite il proprio servizio di hosting. Non utilizzare il token di Manual Bot e non avviare più processi di polling con lo stesso token.

## Menu utenti

- Richiedi un film / Richiedi una serie: titolo, dettagli facoltativi, conferma e modifica.
- Le mie richieste: elenco paginato, dettagli e stato.
- Scarica le app: dispositivo, elenco e scheda con link e codice Downloader se presente.
- Guida all’installazione: indicazioni generali e server 017.
- Segnala un problema app: scelta app, problema, nota facoltativa e conferma finale.

## Amministrazione

Menu visibile solo agli ID configurati: gestione richieste, gestione app, segnalazioni app e statistiche. Non sono presenti avvisi aggiornamento o configurazione nel menu.

Le richieste si possono segnare Ricevuta, In lavorazione, Disponibile o Non reperibile. Il passaggio a Disponibile crea avvisi persistenti per gli utenti interessati, elaborati ogni 30 secondi. Anche prima degli avvisi viene verificata l'iscrizione. Chi ha lasciato il canale non riceve il messaggio; gli errori temporanei vengono ritentati. Non vengono inviati messaggi agli amministratori: consultano l'elenco nel bot.

Richieste con tipo, titolo e dettagli uguali (ignorando maiuscole e spazi ripetuti) vengono unite: ogni utente trova il titolo nelle proprie richieste. Non è prevista ricerca automatica sul disco né confronto approssimativo tra titoli.

Gestisci app usa una procedura guidata sia per aggiunta sia per modifica: nome, piattaforme selezionabili (anche più di una), link, codice Downloader facoltativo, note facoltative. Ogni passaggio richiede Conferma; Indietro mantiene la bozza. Il riepilogo richiede Conferma e salva prima di modificare il database. Il codice non richiede file JSON. La rimozione delle app ha una conferma separata.

## Accesso e navigazione

Ogni comando, messaggio e callback verifica l'iscrizione al canale tramite `getChatMember`. Se Telegram non risponde, l'accesso resta bloccato. I vecchi pulsanti richiedono una nuova verifica; le funzioni amministrative controllano inoltre l'ID dell'utente. Il bot risponde soltanto in privato.

Ogni schermata interna usa un pulsante Indietro verso il menu genitore. Non è presente il pulsante Menu principale; tutti i pulsanti sono in una colonna. Indietro annulla l'attesa corrente e riporta allo step precedente; nelle richieste mantiene la bozza. Il menu principale è la radice. La schermata di accesso negato mostra soltanto Verifica accesso, senza link al canale. CINEMA_CHANNEL_URL non è richiesta. All’avvio si elimina l’elenco pubblico dei comandi; /start, /menu e /cancel restano utilizzabili digitandoli. I collegamenti esterni si aprono fuori dal bot e non hanno un menu gestibile dal bot.

L'iscrizione protegge le funzioni del bot, non impedisce di copiare link già ricevuti. La verifica non sostituisce l'autenticazione del servizio video.

## App iniziali e dati

Sono inseriti i nove collegamenti forniti dal gestore. Le sei app con codice Downloader sono elencate in Android e Fire TV Stick con nota di compatibilità da verificare: questa assegnazione è provvisoria, non una compatibilità certificata. I download non sono stati eseguiti e i collegamenti non sono stati verificati. Per iOS è mantenuto il link App Store con regione eg; per Mac il link Intel. Istruzioni specifiche si possono aggiungere alle note di ogni app.

Richieste, utenti interessati, app, avvisi, segnalazioni e statistiche risiedono in `data/cinema.sqlite3`. Le app iniziali vengono caricate una volta sola: rimuoverle non le fa ricomparire al riavvio. Eseguire backup del database a processo fermo e usare un disco persistente, eventualmente impostando `CINEMA_DB_PATH`. Le bozze di compilazione sono temporanee e si perdono al riavvio; premere /start per ricominciare. Nessun file di Manual Bot viene letto o modificato.

## Controlli

```sh
python -m unittest discover -s tests -v
python -m compileall -q .
```

I test usano Telegram simulato: navigazione, controllo iscrizione/ruoli, richieste, persistenza, avvisi e gestione app. Per la prova reale servono token e canale: avviare il bot, provare un iscritto e un non iscritto, uscire dal canale e premere un vecchio pulsante, quindi verificare app e cambio di stato di una richiesta.

## Statistiche e segnalazioni app

Statistiche mostra conteggi totali, utenti distinti, dettaglio per utente (nome, username quando disponibile e ID Telegram), dettaglio per pulsante e ultima pressione in orario italiano. I conteggi partono da questo aggiornamento, includono gli amministratori e registrano soltanto callback accettate dopo il controllo di iscrizione e ruolo. Comandi, messaggi e tentativi bloccati sono esclusi. Lo stesso ID callback non viene contato due volte. Sono disponibili paginazione e Indietro, e i dati restano nel database persistente. Le aperture dei pulsanti di navigazione sono raggruppate; i download distinguono le singole app.

Scarica apre una schermata con il link esterno: si conta la richiesta di download, non l’apertura del link esterno o l’effettivo download. Telegram non fornisce questi ultimi eventi al bot.

Segnala un problema app è disponibile dal menu e dalle schede app: link non funzionante, app non disponibile, app che non si avvia o altro. È possibile scegliere Altra app se manca dall’elenco, aggiungere una descrizione e confermare l’invio. Le segnalazioni sono consultabili soltanto dagli amministratori, con nome, username, ID del mittente, app, motivo e descrizione. Il gestore può segnarle come risolte; non viene inviato un messaggio automatico di risoluzione.

Validazione aggiornamento: 21 test automatici con Telegram simulato, incluse conferme della procedura app, statistiche, permessi, persistenza e segnalazioni.
