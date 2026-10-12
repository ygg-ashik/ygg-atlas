"""Breakdown label masking, applied once before labels leave the atlas tools.

The caller's policy decides per label class: cleared (labels shown), a mask
mode, or nothing (suppressed). A failing policy or a malformed mode suppresses.
"""

from typing import Any

import structlog

from app.atlas.masking import CATEGORY, CLEARANCE_FOR_CLASS, MaskMode, mask_breakdown
from app.atlas.policy import ResourcePolicy
from app.atlas.tools.audit import record_masking
from app.config import get_settings

logger = structlog.get_logger()


def _well_formed(mode: MaskMode | None) -> bool:
    """A mode object of the wrong shape suppresses (fail closed)."""
    if mode is None:
        return False
    try:
        name, size = mode.mode, mode.bucket_size
    except Exception:
        return False
    # The protocol types them str and int; a policy may hand over any shape.
    return (
        isinstance(name, str) and isinstance(size, int) and not isinstance(size, bool)  # pyright: ignore[reportUnnecessaryIsInstance]
    )


def _settings_pseudonym_key() -> str:
    """The deployment's pseudonym key, read lazily at mask time.

    A missing or empty setting reads as "", which masking turns into
    `suppress` (fail closed).
    """
    return get_settings().atlas_pseudonym_key.strip()


class LabelMasker:
    """Masks one caller's breakdown labels and records it for the audit row."""

    def __init__(self, policy: ResourcePolicy, pseudonym_key: str | None) -> None:
        self._policy = policy
        self._pseudonym_key = pseudonym_key  # None: read from settings at mask time

    def mask(
        self, rows: list[dict[str, Any]], label_class: str | None
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Mask breakdown labels once, before they leave the kernel.

        Returns the result fields and the provenance masking. A metric without
        a label class is treated as an unknown class: suppressed.
        """
        label_class = label_class or ""
        cleared, mode = (
            (False, None) if label_class == CATEGORY else self._mask_inputs(label_class)
        )
        masked = mask_breakdown(
            rows,
            label_class,
            cleared=cleared,
            mode=mode,
            key=self._key() if mode is not None else "",
        )
        result: dict[str, Any] = {"rows": masked.rows}
        if masked.suppressed_rows is not None:
            result["suppressed_rows"] = masked.suppressed_rows
        if masked.others_covers is not None:
            result["others_covers"] = masked.others_covers
        if masked.applied is None:
            return result, None
        record_masking(
            {
                "label_class": label_class,
                "mode": masked.applied,
                "rows_in": len(rows),
                "rows_out": len(masked.rows),
            }
        )
        return result, {"label_class": label_class, "mode": masked.applied}

    def _mask_inputs(self, label_class: str) -> tuple[bool, MaskMode | None]:
        """(cleared, mode) for a label class. A failing policy suppresses."""
        clearance = CLEARANCE_FOR_CLASS.get(label_class)
        if clearance is None:  # category (never masked) or unknown (suppressed)
            return False, None
        try:
            if self._policy.has_clearance(clearance):
                return True, None
            mode = self._policy.mask_mode(label_class)
        except Exception:
            logger.exception("atlas.policy_error", label_class=label_class)
            return False, None
        if mode is not None and not _well_formed(mode):
            # The label class only: never the mode's (possibly sensitive) fields.
            logger.warning("atlas.mask_mode_malformed", label_class=label_class)
            return False, None
        return False, mode

    def _key(self) -> str:
        if self._pseudonym_key is not None:
            return self._pseudonym_key
        return _settings_pseudonym_key()
