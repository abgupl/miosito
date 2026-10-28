# BestPrice24h — Telegram bot

Il punto di ingresso del progetto è `manual_bot.py`. Gestisce pubblicazione
manuale, post programmati, automazioni, raccolte, cronologia, immagini e
integrazione TikTok. Le funzioni sono contenute nello stesso file.

## Struttura

- `manual_bot.py`: bot Telegram e API HTTP delle offerte.
- `requirements.txt`: dipendenze Python utilizzate dal bot.
- `assets/`: loghi e font per le immagini.
- `sito-web/`: sito che legge le offerte dall'API `/api/offerte` del bot.

## Avvio

Usare Python 3.11 o successivo. Dalla cartella `amazon-telegram-bot`:

```bash
pip install -r requirements.txt
python manual_bot.py
```

Configurare le variabili d'ambiente nel servizio che ospita il bot
(ad esempio Railway):

| Variabile | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot, obbligatorio |
| `TELEGRAM_CHAT_ID` | Canale Telegram principale, obbligatorio |
| `ADMIN_TELEGRAM_ID` | ID Telegram dell'amministratore |
| `TELEGRAM_CHAT_ID_CASA` | Canale CASA; predefinito `@BestPrice24hCasa` |
| `AMAZON_PARTNER_TAG` | Tag affiliato Amazon; accetta anche `AMAZON_ASSOCIATE_TAG` |
| `CLUB_DB_PATH` | Percorso del database SQLite; predefinito `club.db` |
| `COMMUNITY_URL` | Link facoltativo alla community |
| `PORT` | Porta del server HTTP per le API |
| `RAILWAY_PUBLIC_DOMAIN` | Dominio pubblico usato per gli URL delle immagini |

Aggiungere il bot come amministratore dei canali con permesso di pubblicazione.
Conservare il database su un volume persistente per mantenere impostazioni,
cronologia e post programmati. Conservare la configurazione d'ambiente già
utilizzata dal servizio.

Il comando di avvio del servizio deve essere `python manual_bot.py`, eseguito
dalla cartella del bot. Non è necessario un workflow GitHub Actions per avviarlo:
le automazioni e la pianificazione sono gestite dal processo del bot.

### Pubblicazione automatica su TikTok tramite Buffer

Il bot può programmare due post fotografici TikTok al giorno, ciascuno con due
offerte già pubblicate sul canale TECH, appartenenti alla stessa categoria e
approvate nuovamente dal filtro qualità della modalità Selettiva.
Configura queste variabili su Railway:

| Variabile | Valore |
|---|---|
| `BUFFER_API_KEY` | Chiave API personale generata da Buffer |
| `BUFFER_TIKTOK_CHANNEL_ID` | ID del canale TikTok restituito dalla Buffer API |
| `TIKTOK_POST_TIMES` | Orari italiani separati da virgola, predefinito `12:30,20:30` |
| `TIKTOK_AUTO_ENABLED` | `1` per attivare, `0` per sospendere; predefinito `1` |
| `TIKTOK_MIN_DISCOUNT` | Sconto minimo corrente; predefinito `20` |

`RAILWAY_PUBLIC_DOMAIN` viene fornita automaticamente da Railway e serve a
Buffer per scaricare la locandina. Il comando amministratore `/tiktok_test`
genera un'anteprima su Telegram senza pubblicarla e senza consumare lo slot.


### Pannello amministratore TikTok

Nel menu principale del bot: **🎵 AUTOMAZIONE TIKTOK**. Permette di mettere
in pausa gli invii, scegliere una coppia di orari italiani (11:30/19:30,
12:30/20:30 oppure 13:00/21:00), impostare lo sconto minimo e consultare gli
ultimi otto tentativi. Il filtro resta Selettiva. Le impostazioni sono persistenti
nel database: le variabili di orario e sconto inizializzano solo il primo avvio.
`TIKTOK_AUTO_ENABLED=0` resta un blocco generale Railway.

L'anteprima, anche via `/tiktok_test` nella chat privata amministratore,
invia immagine e descrizione completa separatamente, senza pubblicare.
La pausa non cancella post già affidati a Buffer o una richiesta già in corso.
Lo stato “programmato” indica l'accettazione da Buffer, non la pubblicazione
confermata da TikTok. Il pulsante **APRI BUFFER** consente il controllo finale.
Il limite giornaliero resta due anche dopo un cambio di orari.
