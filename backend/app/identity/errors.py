"""Identity failures, mapped to HTTP status codes by identity.dependencies."""


class UnauthenticatedError(Exception):
    """401: the caller is not (or no longer) signed in."""


class ForbiddenError(Exception):
    """403: the caller is known but may not use atlas."""


class IdentityUnavailableError(Exception):
    """503: the identity provider is unreachable; the caller's session is fine."""
