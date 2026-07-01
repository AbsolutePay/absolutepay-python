"""Exceptions raised by the client."""

from __future__ import annotations


class AbsolutePayError(Exception):
    """Raised when the API returns a non-2xx response (or a request fails at the network layer).

    Carries the RFC-7807 problem-details fields returned by the API so callers can branch on
    the failure. Use the `is_auth` / `is_rate_limited` helpers for the common cases, and
    include `request_id` when reporting an issue to support.

    Attributes:
        status: HTTP status code (e.g. `401`, `429`, `500`). `0` indicates a network/transport
            failure before any HTTP response was received.
        code: Short, stable machine-readable error code (e.g. `"insufficient_scope"`,
            `"network_error"`). Prefer branching on this over the human-readable message.
        detail: Optional longer human-readable explanation of what went wrong, or `None`.
        request_id: Server request id (`x-request-id` header) for support/correlation, or
            `None` if the response carried none.

    Args:
        status: HTTP status code (`0` for a network failure).
        code: Machine-readable error code.
        title: Short human-readable summary; used as the exception message.
        detail: Optional longer explanation. Defaults to `None`.
        request_id: Optional server request id. Defaults to `None`.
    """

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
        """Whether this is a rate-limit error.

        Returns:
            `True` for HTTP `429` (too many requests) — back off and retry after a moment.
        """
        return self.status == 429

    @property
    def is_auth(self) -> bool:
        """Whether this is an authentication/authorization failure.

        Returns:
            `True` for HTTP `401`/`403` — bad or insufficient credentials, a missing scope,
            or an invalid request signature.
        """
        return self.status in (401, 403)


class WebhookSignatureError(Exception):
    """Raised when an inbound webhook fails signature or freshness (replay-window) verification.

    Thrown by `absolutepay.webhooks.construct_event` when the HMAC signature does not match,
    when a required signature/timestamp header is missing, or when the timestamp falls outside
    the tolerance window. Treat it as "reject this webhook" — respond with a 4xx and do not
    process the payload.
    """
