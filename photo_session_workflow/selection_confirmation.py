"""Explicit, immutable user confirmation for a reduced review selection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterable

from .proxies import ProxyBatchResult, ProxyEntry


class SelectionConfirmationError(ValueError):
    """Raised when a draft or explicit confirmation is invalid."""


@dataclass(frozen=True, slots=True)
class SelectionCandidate:
    asset_id: str
    identifier_name: str
    rating: int
    preview_source: str
    source_relative_path: str
    source_sha256: str
    proxy_relative_path: str
    proxy_sha256: str


@dataclass(frozen=True, slots=True, init=False)
class SelectionDraft:
    candidates: tuple[SelectionCandidate, ...]
    selected_asset_ids: tuple[str, ...]
    candidate_count: int
    selected_count: int
    recommended_minimum: int
    recommended_maximum: int
    volume_status: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True, init=False)
class ConfirmedSelection:
    status: str
    selected: tuple[SelectionCandidate, ...]
    candidate_count: int
    selected_count: int
    recommended_minimum: int
    recommended_maximum: int
    volume_status: str
    warnings: tuple[str, ...]
    confirmation_digest: str

    @property
    def asset_ids(self) -> tuple[str, ...]:
        return tuple(item.asset_id for item in self.selected)


def _safe_relative_path(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    posix = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    return not (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
    )


def _candidate(entry: ProxyEntry) -> SelectionCandidate:
    if (
        entry.status not in {"generated", "reused"}
        or entry.error_code is not None
        or entry.proxy_relative_path is None
        or entry.sha256 is None
    ):
        raise SelectionConfirmationError(
            "selection candidates require complete generated proxies"
        )
    if not entry.asset_id or not entry.identifier_name:
        raise SelectionConfirmationError("selection candidate identity is invalid")
    if (
        not isinstance(entry.rating, int)
        or isinstance(entry.rating, bool)
        or entry.rating not in {1, 2, 3, 4, 5}
    ):
        raise SelectionConfirmationError("selection candidate rating is invalid")
    if entry.preview_source != "lightroom_export":
        raise SelectionConfirmationError("selection candidate preview source is invalid")
    if not _safe_relative_path(entry.source_relative_path):
        raise SelectionConfirmationError("selection candidate source path is invalid")
    if entry.source_sha256 is None or not re.fullmatch(
        r"[0-9a-f]{64}", entry.source_sha256
    ):
        raise SelectionConfirmationError("selection candidate source hash is invalid")
    if not _safe_relative_path(entry.proxy_relative_path):
        raise SelectionConfirmationError("selection candidate proxy path is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", entry.sha256):
        raise SelectionConfirmationError("selection candidate proxy hash is invalid")
    return SelectionCandidate(
        entry.asset_id,
        entry.identifier_name,
        entry.rating,
        entry.preview_source,
        PurePosixPath(entry.source_relative_path.replace("\\", "/")).as_posix(),
        entry.source_sha256,
        PurePosixPath(entry.proxy_relative_path.replace("\\", "/")).as_posix(),
        entry.sha256,
    )


def _ids(values: Iterable[str], *, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise SelectionConfirmationError(f"{label} must be an iterable of asset ids")
    try:
        result = tuple(values)
    except TypeError as exc:
        raise SelectionConfirmationError(
            f"{label} must be an iterable of asset ids"
        ) from exc
    if any(not isinstance(value, str) or not value for value in result):
        raise SelectionConfirmationError(f"{label} contains an invalid asset id")
    if len(set(result)) != len(result):
        raise SelectionConfirmationError(f"{label} contains duplicate asset ids")
    return result


def _volume(selected_count: int, minimum: int, maximum: int) -> tuple[str, tuple[str, ...]]:
    if selected_count < minimum:
        return "below_recommended", ("selection_below_recommended_range",)
    if selected_count > maximum:
        return "above_recommended", ("selection_above_recommended_range",)
    return "within_recommended", ()


def _draft(
    candidates: tuple[SelectionCandidate, ...],
    selected_ids: tuple[str, ...],
    *,
    recommended_minimum: int,
    recommended_maximum: int,
) -> SelectionDraft:
    status, warnings = _volume(
        len(selected_ids), recommended_minimum, recommended_maximum
    )
    draft = object.__new__(SelectionDraft)
    object.__setattr__(draft, "candidates", candidates)
    object.__setattr__(draft, "selected_asset_ids", selected_ids)
    object.__setattr__(draft, "candidate_count", len(candidates))
    object.__setattr__(draft, "selected_count", len(selected_ids))
    object.__setattr__(draft, "recommended_minimum", recommended_minimum)
    object.__setattr__(draft, "recommended_maximum", recommended_maximum)
    object.__setattr__(draft, "volume_status", status)
    object.__setattr__(draft, "warnings", warnings)
    return draft


def create_selection_draft(
    proxies: ProxyBatchResult,
    *,
    initially_selected_asset_ids: Iterable[str] | None = None,
    recommended_minimum: int = 12,
    recommended_maximum: int = 30,
) -> SelectionDraft:
    """Create a pure draft from a complete ordered proxy batch."""

    if (
        not isinstance(recommended_minimum, int)
        or isinstance(recommended_minimum, bool)
        or not isinstance(recommended_maximum, int)
        or isinstance(recommended_maximum, bool)
        or recommended_minimum < 1
        or recommended_maximum < recommended_minimum
    ):
        raise SelectionConfirmationError("recommended selection range is invalid")
    if not proxies.entries or not proxies.ready:
        raise SelectionConfirmationError(
            "selection draft requires a complete non-empty proxy batch"
        )
    candidates = tuple(_candidate(entry) for entry in proxies.entries)
    candidate_ids = tuple(item.asset_id for item in candidates)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise SelectionConfirmationError("selection candidates contain duplicate asset ids")
    proxy_paths = tuple(item.proxy_relative_path.casefold() for item in candidates)
    if len(set(proxy_paths)) != len(proxy_paths):
        raise SelectionConfirmationError("selection candidates contain duplicate proxy paths")

    if initially_selected_asset_ids is None:
        selected = candidate_ids
    else:
        requested = _ids(
            initially_selected_asset_ids,
            label="initial selection",
        )
        unknown = set(requested) - set(candidate_ids)
        if unknown:
            raise SelectionConfirmationError("initial selection contains an unknown asset")
        requested_set = set(requested)
        selected = tuple(value for value in candidate_ids if value in requested_set)
    return _draft(
        candidates,
        selected,
        recommended_minimum=recommended_minimum,
        recommended_maximum=recommended_maximum,
    )


def update_selection(
    draft: SelectionDraft,
    *,
    add_asset_ids: Iterable[str] = (),
    remove_asset_ids: Iterable[str] = (),
) -> SelectionDraft:
    """Return a new draft after explicit add/remove operations."""

    if not isinstance(draft, SelectionDraft):
        raise SelectionConfirmationError("selection draft is invalid")
    additions = _ids(add_asset_ids, label="selection additions")
    removals = _ids(remove_asset_ids, label="selection removals")
    if set(additions) & set(removals):
        raise SelectionConfirmationError(
            "the same asset cannot be added and removed in one update"
        )
    candidate_ids = tuple(item.asset_id for item in draft.candidates)
    known = set(candidate_ids)
    if (set(additions) | set(removals)) - known:
        raise SelectionConfirmationError("selection update contains an unknown asset")
    selected = (set(draft.selected_asset_ids) | set(additions)) - set(removals)
    ordered = tuple(value for value in candidate_ids if value in selected)
    return _draft(
        draft.candidates,
        ordered,
        recommended_minimum=draft.recommended_minimum,
        recommended_maximum=draft.recommended_maximum,
    )


def _digest(selected: tuple[SelectionCandidate, ...]) -> str:
    payload = [
        {
            "asset_id": item.asset_id,
            "identifier_name": item.identifier_name,
            "preview_source": item.preview_source,
            "source_relative_path": item.source_relative_path,
            "source_sha256": item.source_sha256,
            "proxy_relative_path": item.proxy_relative_path,
            "proxy_sha256": item.proxy_sha256,
            "rating": item.rating,
        }
        for item in selected
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def confirm_selection(
    draft: SelectionDraft,
    *,
    explicit_confirmation: bool,
) -> ConfirmedSelection:
    """Create a confirmation only after an explicit true user action."""

    if not isinstance(draft, SelectionDraft):
        raise SelectionConfirmationError("selection draft is invalid")
    if explicit_confirmation is not True:
        raise SelectionConfirmationError("selection requires explicit confirmation")
    selected_ids = set(draft.selected_asset_ids)
    selected = tuple(
        item for item in draft.candidates if item.asset_id in selected_ids
    )
    if not selected:
        raise SelectionConfirmationError("selection must contain at least one asset")
    confirmation = object.__new__(ConfirmedSelection)
    object.__setattr__(confirmation, "status", "confirmed")
    object.__setattr__(confirmation, "selected", selected)
    object.__setattr__(confirmation, "candidate_count", draft.candidate_count)
    object.__setattr__(confirmation, "selected_count", len(selected))
    object.__setattr__(
        confirmation, "recommended_minimum", draft.recommended_minimum
    )
    object.__setattr__(
        confirmation, "recommended_maximum", draft.recommended_maximum
    )
    object.__setattr__(confirmation, "volume_status", draft.volume_status)
    object.__setattr__(confirmation, "warnings", draft.warnings)
    object.__setattr__(confirmation, "confirmation_digest", _digest(selected))
    return confirmation


def validate_confirmed_selection(value: object) -> ConfirmedSelection:
    """Reject absent, malformed, or internally inconsistent confirmations."""

    if not isinstance(value, ConfirmedSelection) or value.status != "confirmed":
        raise SelectionConfirmationError("review package requires confirmed selection")
    if not value.selected or value.selected_count != len(value.selected):
        raise SelectionConfirmationError("confirmed selection is inconsistent")
    if value.confirmation_digest != _digest(value.selected):
        raise SelectionConfirmationError("confirmed selection digest is invalid")
    if len(set(value.asset_ids)) != len(value.asset_ids):
        raise SelectionConfirmationError("confirmed selection contains duplicate assets")
    if (
        value.candidate_count < value.selected_count
        or value.recommended_minimum < 1
        or value.recommended_maximum < value.recommended_minimum
    ):
        raise SelectionConfirmationError("confirmed selection range is inconsistent")
    volume_status, warnings = _volume(
        value.selected_count,
        value.recommended_minimum,
        value.recommended_maximum,
    )
    if value.volume_status != volume_status or value.warnings != warnings:
        raise SelectionConfirmationError("confirmed selection summary is inconsistent")
    return value
