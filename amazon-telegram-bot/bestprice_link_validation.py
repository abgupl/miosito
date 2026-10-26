"""Conservative validation for Amazon offer links supplied manually.

Does not fetch Amazon, resolve short links, or depend on Creators API.
"""
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({'amazon.it', 'www.amazon.it', 'amzn.to', 'www.amzn.to', 'link.amazon', 'www.link.amazon'})


def valid_amazon_link(value):
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == 'https' and url.hostname in ALLOWED_HOSTS
                and url.username is None and url.password is None
                and url.port in (None, 443) and bool(url.path and url.path != '/'))
    except (ValueError, AttributeError):
        return False
