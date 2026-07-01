"""Exceptions raised by the client."""

from __future__ import annotations


class AbsolutePayError(Exception):
    """Raised when the API returns a non-2xx response. Carries the problem+json fields."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(title or code or f"HTTP {status}")
        self.status = status
        self.code = code
        self.detail = detail
        self.request_id = request_id

    @property
    def is_rate_limited(self) -> bool:
        """429 — too many requests; back off and retry after a moment."""
        return self.status == 429

    @property
    def is_auth(self) -> bool:
        """401/403 — bad/insufficient credentials, missing scope, or invalid request signature."""
        return self.status in (401, 403)


class WebhookSignatureError(Exception):
    """Raised when an inbound webhook fails signature or freshness verification."""
