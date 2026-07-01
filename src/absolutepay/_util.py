"""Small internal helpers shared by the client and resources."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote as _urlquote
from urllib.parse import urlencode


def qs(params: Mapping[str, Any]) -> str:
    """Build a ``?a=1&b=2`` query string from defined values (skips ``None``)."""
    pairs = [(k, v) for k, v in params.items() if v is not None]
    return f"?{urlencode(pairs)}" if pairs else ""


def path_seg(value: str) -> str:
    """URL-encode a single path segment (no slashes pass through)."""
    return _urlquote(str(value), safe="")


def clean(body: Mapping[str, Any]) -> dict[str, Any]:
    """Drop ``None`` values from a request body (optional fields left unset)."""
    return {k: v for k, v in body.items() if v is not None}
