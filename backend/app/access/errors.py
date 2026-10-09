"""Access failures. Each carries the HTTP status the API maps it to."""

from typing import ClassVar


class AccessError(Exception):
    """Base class for access failures; subclasses set their HTTP status."""

    status_code: ClassVar[int] = 400


class AccessDeniedError(AccessError):
    """403: the caller may not do this."""

    status_code: ClassVar[int] = 403


class NotFoundError(AccessError):
    """404: the user, group, grant or resource does not exist."""

    status_code: ClassVar[int] = 404


class ConflictError(AccessError):
    """409: the change conflicts with the current state."""

    status_code: ClassVar[int] = 409


class InvalidChangeError(AccessError):
    """422: the requested change is not valid."""

    status_code: ClassVar[int] = 422


class PolicyUnavailableError(AccessError):
    """503: the policy could not be evaluated, so everything is denied (spec §12).

    `str(exc)` is the business message clients see; `reason` is the internal
    cause, for logs only.
    """

    status_code: ClassVar[int] = 503
    PUBLIC_MESSAGE: ClassVar[str] = "The access check is unavailable right now."

    def __init__(self, reason: str = "") -> None:
        super().__init__(self.PUBLIC_MESSAGE)
        self.reason = reason
