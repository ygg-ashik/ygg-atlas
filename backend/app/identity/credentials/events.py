"""The credential_events row every token change is staged with."""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from app.identity.api_tokens import CredentialActor
from app.identity.models import CredentialEvent


class EventStamper:
    """Builds credential_events rows stamped with the service's clock."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    def event(
        self,
        event: str,
        actor: CredentialActor,
        *,
        user_id: UUID | None,
        token_id: UUID | None = None,
        client_id: str | None = None,
        details: dict[str, Any],
    ) -> CredentialEvent:
        return CredentialEvent(
            at=self._clock(),
            event=event,
            user_id=user_id,
            actor_user_id=actor.user_id,
            via=actor.via,
            token_id=token_id,
            client_id=client_id,
            details=details,
        )
