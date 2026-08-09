"""Separate non-recursive inventory and resolution of declared Lightroom exports."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .rating_filter import RatingFilterResult


@dataclass(frozen=True, slots=True)
class LightroomExportEntry:
    relative_path: str
    filename: str
    original_extension: str
    normalized_extension: str
    size_bytes: int
    modified_at: str


@dataclass(frozen=True, slots=True)
class LightroomExportNotice:
    relative_path: str
    filename: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class LightroomExportInventory:
    entries: tuple[LightroomExportEntry, ...]
    ignored: tuple[LightroomExportNotice, ...]
    rejected: tuple[LightroomExportNotice, ...]


@dataclass(frozen=True, slots=True)
class LightroomExportResolution:
    asset_id: str
    identifier_name: str
    rating: int
    xmp_relative_path: str | None
    status: str
    export: LightroomExportEntry | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LightroomExportResolutionResult:
    resolutions: tuple[LightroomExportResolution, ...]
    resolved_count: int
    missing_count: int
    ambiguous_count: int
    invalid_count: int

    @property
    def ready(self) -> bool:
        return all(item.status == "resolved" for item in self.resolutions)


def _timestamp(modified_ns: int) -> str:
    seconds, nanoseconds = divmod(modified_ns, 1_000_000_000)
    base = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{nanoseconds:09d}Z"


def _relative(prefix: Path, name: str) -> str:
    return (PurePosixPath(*prefix.parts) / name).as_posix()


def _inventory_lightroom_export_directory(
    directory: Path, relative_prefix: Path
) -> LightroomExportInventory:
    """Inventory direct children only; the validated absolute root is never returned."""

    entries: list[LightroomExportEntry] = []
    ignored: list[LightroomExportNotice] = []
    rejected: list[LightroomExportNotice] = []
    try:
        with os.scandir(directory) as iterator:
            children = sorted(iterator, key=lambda item: (item.name.casefold(), item.name))
    except OSError:
        return LightroomExportInventory(
            (), (), (LightroomExportNotice(".", ".", "rejected", "directory_enumeration_error"),)
        )

    for child in children:
        relative_path = _relative(relative_prefix, child.name)
        try:
            metadata = child.stat(follow_symlinks=False)
        except OSError:
            rejected.append(
                LightroomExportNotice(
                    relative_path, child.name, "rejected", "metadata_unavailable"
                )
            )
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or bool(
            attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            rejected.append(
                LightroomExportNotice(
                    relative_path, child.name, "rejected", "link_or_reparse_point"
                )
            )
            continue
        if stat.S_ISDIR(metadata.st_mode):
            ignored.append(
                LightroomExportNotice(
                    relative_path, child.name, "ignored", "recursion_disabled"
                )
            )
            continue
        if not stat.S_ISREG(metadata.st_mode):
            rejected.append(
                LightroomExportNotice(
                    relative_path, child.name, "rejected", "unsupported_filesystem_type"
                )
            )
            continue
        extension = Path(child.name).suffix
        normalized = extension.casefold()
        if normalized not in {".jpg", ".jpeg"}:
            ignored.append(
                LightroomExportNotice(
                    relative_path, child.name, "ignored", "not_jpg_export"
                )
            )
            continue
        try:
            modified_at = _timestamp(metadata.st_mtime_ns)
        except (OverflowError, OSError, ValueError):
            rejected.append(
                LightroomExportNotice(
                    relative_path, child.name, "rejected", "metadata_unavailable"
                )
            )
            continue
        entries.append(
            LightroomExportEntry(
                relative_path,
                child.name,
                extension,
                normalized,
                metadata.st_size,
                modified_at,
            )
        )
    return LightroomExportInventory(tuple(entries), tuple(ignored), tuple(rejected))


def _base_name(filename: str) -> str:
    extension = Path(filename).suffix
    return filename[: -len(extension)]


def resolve_lightroom_exports(
    selection: RatingFilterResult,
    inventory: LightroomExportInventory,
) -> LightroomExportResolutionResult:
    """Resolve selected assets by exact case-folded base name without suffix guesses."""

    candidates: dict[str, list[LightroomExportEntry]] = {}
    invalid: dict[str, list[LightroomExportNotice]] = {}
    for entry in inventory.entries:
        candidates.setdefault(_base_name(entry.filename).casefold(), []).append(entry)
    for notice in inventory.rejected:
        if Path(notice.filename).suffix.casefold() in {".jpg", ".jpeg"}:
            invalid.setdefault(_base_name(notice.filename).casefold(), []).append(notice)

    resolutions: list[LightroomExportResolution] = []
    for selected in selection.selected:
        asset = selected.asset
        rating = selected.rating_result.rating
        key = asset.normalized_base_name
        matches = candidates.get(key, [])
        invalid_matches = invalid.get(key, [])
        if invalid_matches:
            status, export, warnings = "invalid", None, ("lightroom_export_invalid",)
        elif not matches:
            status, export, warnings = "missing", None, ("lightroom_export_missing",)
        elif len(matches) > 1:
            status, export, warnings = "ambiguous", None, ("lightroom_export_ambiguous",)
        else:
            status, export, warnings = (
                "resolved",
                matches[0],
                (
                    "lightroom_export_user_declared",
                    "lightroom_export_provenance_unverified",
                    "embedded_metadata_policy_depends_on_lightroom_export",
                ),
            )
        resolutions.append(
            LightroomExportResolution(
                asset.asset_id,
                asset.original_base_names[0],
                rating,  # type: ignore[arg-type]
                selected.rating_result.xmp_relative_path,
                status,
                export,
                warnings,
            )
        )
    resolutions_tuple = tuple(resolutions)
    return LightroomExportResolutionResult(
        resolutions_tuple,
        sum(item.status == "resolved" for item in resolutions_tuple),
        sum(item.status == "missing" for item in resolutions_tuple),
        sum(item.status == "ambiguous" for item in resolutions_tuple),
        sum(item.status == "invalid" for item in resolutions_tuple),
    )
