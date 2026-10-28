# Stato dello sviluppo V2

## Completato

- Estrazione di 34 funzioni operative nei tre moduli di invio.
- Menu iniziale con scelta canale e impostazioni generali.
- Selezione indipendente per amministratore e accessi per canale.
- Canali aggiuntivi configurabili senza duplicare il bot.
- Destinazione fissata nella bozza e nella coda, mai in una variabile globale mutabile.
- Cronologia, consultazione/modifica dei programmati e repost filtrati per destinazione.
- Intervallo multiplo/repost, fascia oraria, periodo repost e tag affiliato per canale.
- Pubblicazione singola attraverso la coda, con controllo degli slot del canale.
- Rifiuto di schermate di altri canali, anteprime scadute e ID fuori dal canale selezionato.
- Protezione dei job contro un secondo invio della stessa riga e contro annullamenti tardivi.
- 26 test superati, inclusa un'integrazione con handler Telegram reali e invii simulati.

## Limiti di questa fase

- Nessun deploy o invio reale eseguito; il servizio precedente rimane invariato.
- Nessuna migrazione del database di produzione eseguita.
- Gestione amministratori e aggiunta canali tramite variabili d'ambiente.
- Il repost avvia un lotto su richiesta, non una nuova ricerca ricorrente autonoma.
- TikTok, rubriche e altre integrazioni storiche non sono ancora nel nuovo menu.
- Servizi condivisi di lettura Amazon, rendering, monitoraggio e pianificazione
  restano nel coordinatore. I moduli ricevono esplicitamente il parametro
  `servizi`, senza import circolari. L'eventuale successiva estrazione della
  pubblicazione condivisa va eseguita mantenendo questi controlli di destinazione.

Configurazione, comportamento e istruzioni di prova sono descritti in [README.md](README.md).
