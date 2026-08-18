# Amazon → Telegram Bot

Bot che cerca automaticamente prodotti in offerta su Amazon (tramite Product
Advertising API 5.0) e li pubblica su un canale Telegram, ogni 4 ore, senza
intervento manuale.

## Struttura del progetto

- `config.py` — categorie/parole chiave da cercare, sconto minimo, ecc.
- `amazon_client.py` — interroga la PA-API di Amazon (SearchItems)
- `telegram_client.py` — pubblica il post sul canale Telegram
- `bot.py` — script principale che collega le due cose
- `.github/workflows/post_offers.yml` — automazione: esegue `bot.py` ogni 4 ore

## Setup — passo per passo

### 1. Crea un repository GitHub

Carica questa cartella su un repository GitHub (può essere privato).

### 2. Aggiungi i "Secrets" su GitHub

Vai su: repository → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**, e aggiungi questi 5 secrets:

| Nome secret | Dove trovarlo |
|---|---|
| `AMAZON_ACCESS_KEY` | Amazon Associates → Tools → Product Advertising API |
| `AMAZON_SECRET_KEY` | Stessa pagina (mostrata solo alla creazione, se l'hai persa devi rigenerarla) |
| `AMAZON_PARTNER_TAG` | Il tuo tracking ID/tag associato (es. `tuonome-21`) |
| `TELEGRAM_BOT_TOKEN` | Il token che ti ha dato @BotFather |
| `TELEGRAM_CHAT_ID` | `@nometuocanale` se il canale è pubblico, o l'ID numerico se privato |

### 3. Aggiungi il bot come amministratore del canale Telegram

Impostazioni canale → Amministratori → Aggiungi admin → cerca il tuo bot,
dagli il permesso di pubblicare messaggi.

### 4. Personalizza le categorie

Apri `config.py` e modifica `SEARCH_TERMS` con le categorie/parole chiave che
vuoi seguire, e `MIN_DISCOUNT_PERCENT` con lo sconto minimo sotto il quale non
vuoi pubblicare.

### 5. Attiva l'automazione

Il workflow in `.github/workflows/post_offers.yml` è già impostato per girare
ogni 4 ore automaticamente una volta che il repository è su GitHub — non devi
fare altro. Puoi anche lanciarlo a mano da GitHub: tab **Actions** → seleziona
il workflow → **Run workflow**.

### 6. (Opzionale) Testalo in locale prima

```bash
pip install -r requirements.txt

export AMAZON_ACCESS_KEY="xxx"
export AMAZON_SECRET_KEY="xxx"
export AMAZON_PARTNER_TAG="xxx"
export TELEGRAM_BOT_TOKEN="xxx"
export TELEGRAM_CHAT_ID="@nometuocanale"

python bot.py
```

## Note importanti

- **Non condividere mai** `AMAZON_SECRET_KEY` o `TELEGRAM_BOT_TOKEN` in chat,
  repository pubblici, o messaggi: chi li ottiene può usare le tue credenziali.
- Amazon collega il volume di richieste API alle vendite generate dal tuo
  tag affiliato: se per 30 giorni non maturano vendite qualificanti, l'accesso
  API può essere sospeso.
- La Product Advertising API 5.0 è in fase di dismissione da parte di Amazon
  a favore della nuova "Creators API": se in futuro le tue chiavi smettono di
  funzionare, controlla la pagina Associates per eventuali migrazioni richieste.
- Cambia la frequenza modificando la riga `cron` nel file del workflow (il
  formato è minuto-ora-giorno-mese-giorno_settimana, in UTC).
