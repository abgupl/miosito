# Bot cinema Telegram

Bot autonomo, separato da `amazon-telegram-bot/manual_bot.py`: token, processo e database propri. Python 3.10 o superiore.

## Primo avvio

1. Crea un nuovo bot con @BotFather e aggiungilo come amministratore al canale.
2. Imposta le variabili indicate in `.env.example` nell'ambiente del processo: token del nuovo bot, ID numerico del canale (oppure username pubblico), link al canale e ID numerici degli amministratori separati da virgola. Anche gli amministratori devono essere iscritti al canale.
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
- Apri il canale: collegamento al canale.

## Amministrazione

Menu visibile solo agli ID configurati: gestione richieste e gestione app. Non sono presenti segnalazioni problemi, avvisi aggiornamento o configurazione nel menu.

Le richieste si possono segnare Ricevuta, In lavorazione, Disponibile o Non reperibile. Il passaggio a Disponibile crea avvisi persistenti per gli utenti interessati, elaborati ogni 30 secondi. Anche prima degli avvisi viene verificata l'iscrizione. Chi ha lasciato il canale non riceve il messaggio; gli errori temporanei vengono ritentati. Non vengono inviati messaggi agli amministratori: consultano l'elenco nel bot.

Richieste con tipo, titolo e dettagli uguali (ignorando maiuscole e spazi ripetuti) vengono unite: ogni utente trova il titolo nelle proprie richieste. Non è prevista ricerca automatica sul disco né confronto approssimativo tra titoli.

Gestisci app permette aggiunta e modifica tramite una scheda JSON mostrata nel bot, e rimozione con conferma. Campi: `name`, `url`, `platforms`, `code`, `notes`. Piattaforme ammesse: `android`, `fire`, `ios`, `windows`, `mac`. `code` è una stringa, anche vuota. Non inserire credenziali personali nelle schede.

## Accesso e navigazione

Ogni comando, messaggio e callback verifica l'iscrizione al canale tramite `getChatMember`. Se Telegram non risponde, l'accesso resta bloccato. I vecchi pulsanti richiedono una nuova verifica; le funzioni amministrative controllano inoltre l'ID dell'utente. Il bot risponde soltanto in privato.

Ogni schermata interna usa un pulsante Indietro verso il menu genitore. Le schermate più profonde hanno anche Menu principale. Indietro annulla l'attesa corrente e riporta allo step precedente; nelle richieste mantiene la bozza. Il menu principale è la radice. La schermata di accesso negato mostra Apri il canale e Verifica accesso. I collegamenti esterni si aprono fuori dal bot e non hanno un menu gestibile dal bot.

L'iscrizione protegge le funzioni del bot, non impedisce di copiare link già ricevuti. La verifica non sostituisce l'autenticazione del servizio video.

## App iniziali e dati

Sono inseriti i nove collegamenti forniti dal gestore. Le sei app con codice Downloader sono elencate in Android e Fire TV Stick con nota di compatibilità da verificare: questa assegnazione è provvisoria, non una compatibilità certificata. I download non sono stati eseguiti e i collegamenti non sono stati verificati. Per iOS è mantenuto il link App Store con regione eg; per Mac il link Intel. Istruzioni specifiche si possono aggiungere alle note di ogni app.

Richieste, utenti interessati, app e avvisi risiedono in `data/cinema.sqlite3`. Le app iniziali vengono caricate una volta sola: rimuoverle non le fa ricomparire al riavvio. Eseguire backup del database a processo fermo e usare un disco persistente, eventualmente impostando `CINEMA_DB_PATH`. Le bozze di compilazione sono temporanee e si perdono al riavvio; premere /start per ricominciare. Nessun file di Manual Bot viene letto o modificato.

## Controlli

```sh
python -m unittest discover -s tests -v
python -m compileall -q .
```

I test usano Telegram simulato: navigazione, controllo iscrizione/ruoli, richieste, persistenza, avvisi e gestione app. Per la prova reale servono token e canale: avviare il bot, provare un iscritto e un non iscritto, uscire dal canale e premere un vecchio pulsante, quindi verificare app e cambio di stato di una richiesta.
