from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DIRECT_LINK_SEGMENT = re.compile(r"^[A-Za-z0-9_]+$")
_STARTAPP_VALUE = re.compile(r"^(?:order|listing)_[0-9a-fA-F]{32}$")


def validate_telegram_direct_link(value: str | None) -> str | None:
    """Return a valid Telegram Mini App direct link, or None for any other URL."""
    if not value:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None

    path_parts = parsed.path.split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "t.me"
        or parsed.fragment
        or len(path_parts) != 3
        or path_parts[0] != ""
        or not _DIRECT_LINK_SEGMENT.fullmatch(path_parts[1])
        or not _DIRECT_LINK_SEGMENT.fullmatch(path_parts[2])
    ):
        return None

    return candidate


def telegram_direct_link_with_startapp(
    value: str | None,
    *,
    startapp: str,
) -> str | None:
    """Validate a direct link and set a supported order/listing startapp value."""
    direct_link = validate_telegram_direct_link(value)
    if direct_link is None or not _STARTAPP_VALUE.fullmatch(startapp):
        return None

    parsed = urlsplit(direct_link)
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "startapp"
    ]
    query.append(("startapp", startapp))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), "")
    )
