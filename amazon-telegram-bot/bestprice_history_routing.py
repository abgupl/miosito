"""Explicit channel filters for the history screen.

Unknown channels must not be interpreted as TECH.  The 'tutti' view
is intentionally cross-channel; other filters resolve through the registry.
"""
from bestprice_publishing import resolve_destination


def history_target(db_path, selected, *, tech_id, casa_id):
    selected = str(selected or '').strip()
    if selected == 'tutti':
        return None
    aliases = {'tech': tech_id, 'casa': casa_id}
    destination = aliases.get(selected, selected)
    return resolve_destination(db_path, destination).chat_id


def history_matches(chat_id, target):
    return bool(str(chat_id or '').strip()) and (target is None or str(chat_id) == str(target))
