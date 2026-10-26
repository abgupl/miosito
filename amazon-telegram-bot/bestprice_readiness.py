"""Controlli fail-closed prima di eseguire un'automazione BestPrice24h.

La ricerca nel bot corrente e' disabilitata: nessuno slot deve essere consumato
finche' non viene collegata una fonte reale di offerte.
"""
import bestprice_channels as registry
import bestprice_scheduler as scheduler


class AutomationNotReady(RuntimeError):
    pass


def assess(db_path, channel, config, *, source_available=False, dynamic_supported=False):
    """Return (ready, reason, record). No network requests or database writes."""
    if not channel or not str(channel).strip():
        return False, 'Canale non selezionato', None
    record = next((r for r in registry.channels(db_path)
                   if str(channel) in (str(r['chat_id']), str(r.get('legacy_key') or ''))), None)
    if record is None:
        return False, 'Canale inesistente o disattivato', None
    if not source_available:
        return False, 'Ricerca offerte non disponibile: Creators API disabilitata', record
    if not scheduler.eligible(record, config, allow_dynamic=dynamic_supported):
        return False, 'Automazione disattivata, categorie mancanti o canale non ancora integrato', record
    return True, 'Pronto', record


def require_ready(db_path, channel, config, **kwargs):
    ready, reason, record = assess(db_path, channel, config, **kwargs)
    if not ready:
        raise AutomationNotReady(reason)
    return record
