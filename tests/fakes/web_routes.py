"""Explicit links for the overview redirect and the retained progress endpoint."""
from urllib.parse import parse_qs, urlsplit


def action_id(location: str) -> str:
    parsed = urlsplit(location)
    return parse_qs(parsed.query)['aktion'][0] if parsed.query.startswith('aktion=') else parsed.path.rsplit('/', 1)[1]


def progress_link(location: str) -> str:
    return '/aktion/' + action_id(location)
