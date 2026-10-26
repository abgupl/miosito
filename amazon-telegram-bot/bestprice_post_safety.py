"""Validate destination before editing existing Telegram offer posts."""
from bestprice_publishing import resolve_destination


def require_post_destination(db_path, chat_id):
    """Never edit a post on an implicit default channel."""
    return resolve_destination(db_path, chat_id).chat_id
