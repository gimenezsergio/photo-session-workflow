"""Read-only integrity snapshots and comparison for Phase 0 source boundaries."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath

from .inventory import InventoryEntry, InventoryResult, RECOGNIZED_EXTENSIONS
from .lightroom_exports import LightroomExportEntry, LightroomExportInventory
from .paths import PathBoundaryError, SessionReader


class SourceIntegrityError(ValueError):
    """Raised for invalid inventory input or a source changed during capture."""


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    relative_path: str
    source_kind: str
    normalized_extension: str
    size_bytes: int
    modified_at: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceIntegritySnapshot:
    entries: tuple[SourceFingerprint, ...]
    source_count: int
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class SourceIntegrityChange:
    relative_path: str
    change: str


@dataclass(frozen=True, slots=True)
class SourceIntegrityReport:
    unchanged: bool
    before_count: int
    after_count: int
    added: tuple[SourceIntegrityChange, ...]
    missing: tuple[SourceIntegrityChange, ...]
    changed: tuple[SourceIntegrityChange, ...]


@dataclass(frozen=True, slots=True)
class RepositoryHygieneReport:
    clean: bool
    tracked_count: int
    prohibited_paths: tuple[str, ...]


_PROHIBITED_TRACKED_SUFFIXES = (
    ".nef",
    ".cr2",
    ".cr3",
    ".arw",
    ".raf",
    ".dng",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".xmp",
    ".acr",
    ".lrcat",
    ".lrcat-data",
    ".lrdata",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".sqlite-journal",
    ".sqlite3-journal",
    ".db-journal",
    ".sqlite-wal",
    ".sqlite3-wal",
    ".db-wal",
    ".sqlite-shm",
    ".sqlite3-shm",
    ".db-shm",
    ".zip",
)


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SourceIntegrityError("source path must be a non-empty relative path")
    posix = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or posix == PurePosixPath(".")
        or ".." in posix.parts
        or "\\" in value
    ):
        raise SourceIntegrityError("source path must remain relative")
    return posix.as_posix()


def _session_entry(entry: InventoryEntry) -> tuple[str, str, str, int, str]:
    if (
        not isinstance(entry, InventoryEntry)
        or entry.status != "admitted"
        or entry.normalized_extension not in RECOGNIZED_EXTENSIONS
        or entry.category != RECOGNIZED_EXTENSIONS[entry.normalized_extension]
        or not isinstance(entry.size_bytes, int)
        or isinstance(entry.size_bytes, bool)
        or entry.size_bytes < 0
        or not isinstance(entry.modified_at, str)
        or not entry.modified_at.endswith("Z")
    ):
        raise SourceIntegrityError("session inventory entry is invalid")
    return (
        _safe_relative(entry.relative_path),
        "session",
        entry.normalized_extension,
        entry.size_bytes,
        entry.modified_at,
    )


def _export_entry(entry: LightroomExportEntry) -> tuple[str, str, str, int, str]:
    if (
        not isinstance(entry, LightroomExportEntry)
        or entry.normalized_extension not in {".jpg", ".jpeg"}
        or not isinstance(entry.size_bytes, int)
        or isinstance(entry.size_bytes, bool)
        or entry.size_bytes < 0
        or not isinstance(entry.modified_at, str)
        or not entry.modified_at.endswith("Z")
    ):
        raise SourceIntegrityError("Lightroom export inventory entry is invalid")
    return (
        _safe_relative(entry.relative_path),
        "lightroom_export",
        entry.normalized_extension,
        entry.size_bytes,
        entry.modified_at,
    )


def _sort_key(value: tuple[str, str, str, int, str]) -> tuple[str, str]:
    return value[0].casefold(), value[0]


def _snapshot_digest(entries: tuple[SourceFingerprint, ...]) -> str:
    payload = json.dumps(
        [asdict(entry) for entry in entries],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stable_timestamp(modified_ns: int) -> str:
    seconds, nanoseconds = divmod(modified_ns, 1_000_000_000)
    try:
        base = datetime.fromtimestamp(seconds, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise SourceIntegrityError("source timestamp is invalid") from exc
    return f"{base}.{nanoseconds:09d}Z"


def capture_source_integrity(
    reader: SessionReader,
    inventory: InventoryResult,
    *,
    lightroom_exports: LightroomExportInventory | None = None,
    chunk_size: int = 1_048_576,
) -> SourceIntegritySnapshot:
    """Hash admitted sources without opening ignored or prohibited entries."""

    if not isinstance(reader, SessionReader):
        raise SourceIntegrityError("session reader capability is required")
    if not isinstance(inventory, InventoryResult):
        raise SourceIntegrityError("session inventory result is required")
    candidates = [_session_entry(entry) for entry in inventory.entries]
    if lightroom_exports is not None:
        if not isinstance(lightroom_exports, LightroomExportInventory):
            raise SourceIntegrityError("Lightroom export inventory is invalid")
        candidates.extend(_export_entry(entry) for entry in lightroom_exports.entries)
    candidates.sort(key=_sort_key)
    paths = tuple(item[0] for item in candidates)
    if len({path.casefold() for path in paths}) != len(paths):
        raise SourceIntegrityError("source inventories contain duplicate paths")

    fingerprints: list[SourceFingerprint] = []
    for relative_path, source_kind, extension, expected_size, modified_at in candidates:
        if relative_path.casefold().endswith((".lrcat", ".lrcat-data", ".lrdata")):
            raise SourceIntegrityError("Lightroom catalog data is prohibited")
        try:
            size, modified_ns, digest = reader.fingerprint_file(
                relative_path,
                chunk_size=chunk_size,
            )
        except (OSError, PathBoundaryError, ValueError) as exc:
            raise SourceIntegrityError("source could not be fingerprinted") from exc
        if size != expected_size or _stable_timestamp(modified_ns) != modified_at:
            raise SourceIntegrityError("source metadata changed since inventory")
        fingerprints.append(
            SourceFingerprint(
                relative_path,
                source_kind,
                extension,
                size,
                modified_at,
                digest,
            )
        )
    values = tuple(fingerprints)
    return SourceIntegritySnapshot(values, len(values), _snapshot_digest(values))


def _validated_snapshot(snapshot: SourceIntegritySnapshot) -> dict[str, SourceFingerprint]:
    if (
        not isinstance(snapshot, SourceIntegritySnapshot)
        or snapshot.source_count != len(snapshot.entries)
        or not re.fullmatch(r"[0-9a-f]{64}", snapshot.snapshot_sha256)
        or snapshot.snapshot_sha256 != _snapshot_digest(snapshot.entries)
    ):
        raise SourceIntegrityError("source integrity snapshot is invalid")
    result: dict[str, SourceFingerprint] = {}
    for entry in snapshot.entries:
        path = _safe_relative(entry.relative_path)
        key = path.casefold()
        if key in result:
            raise SourceIntegrityError("source integrity snapshot has duplicate paths")
        if (
            entry.source_kind not in {"session", "lightroom_export"}
            or entry.normalized_extension
            not in {*RECOGNIZED_EXTENSIONS, ".jpeg"}
            or not isinstance(entry.size_bytes, int)
            or isinstance(entry.size_bytes, bool)
            or entry.size_bytes < 0
            or not re.fullmatch(r"[0-9a-f]{64}", entry.sha256)
        ):
            raise SourceIntegrityError("source fingerprint is invalid")
        result[key] = entry
    return result


def compare_source_integrity(
    before: SourceIntegritySnapshot,
    after: SourceIntegritySnapshot,
) -> SourceIntegrityReport:
    """Report additions, removals and metadata/content changes by relative path."""

    before_by_path = _validated_snapshot(before)
    after_by_path = _validated_snapshot(after)
    before_keys = set(before_by_path)
    after_keys = set(after_by_path)
    added = tuple(
        SourceIntegrityChange(after_by_path[key].relative_path, "added")
        for key in sorted(after_keys - before_keys)
    )
    missing = tuple(
        SourceIntegrityChange(before_by_path[key].relative_path, "missing")
        for key in sorted(before_keys - after_keys)
    )
    changed = tuple(
        SourceIntegrityChange(before_by_path[key].relative_path, "changed")
        for key in sorted(before_keys & after_keys)
        if before_by_path[key] != after_by_path[key]
    )
    return SourceIntegrityReport(
        not added and not missing and not changed,
        before.source_count,
        after.source_count,
        added,
        missing,
        changed,
    )


def require_unchanged_sources(report: SourceIntegrityReport) -> None:
    if not isinstance(report, SourceIntegrityReport):
        raise SourceIntegrityError("source integrity report is required")
    if not report.unchanged:
        raise SourceIntegrityError("source integrity verification failed")


def check_repository_hygiene(tracked_paths: tuple[str, ...]) -> RepositoryHygieneReport:
    """Validate an externally supplied `git ls-files` result without running Git."""

    if not isinstance(tracked_paths, tuple):
        raise SourceIntegrityError("tracked paths must be an immutable tuple")
    normalized = tuple(_safe_relative(path) for path in tracked_paths)
    if len({path.casefold() for path in normalized}) != len(normalized):
        raise SourceIntegrityError("tracked paths contain duplicates")
    prohibited_values: list[str] = []
    for path in sorted(normalized, key=lambda item: (item.casefold(), item)):
        lowered = path.casefold()
        components = tuple(part.casefold() for part in PurePosixPath(path).parts)
        if (
            lowered.endswith(_PROHIBITED_TRACKED_SUFFIXES)
            or any(part in {"config.local.json", "config.local.yaml", ".env"} for part in components)
            or any(part.endswith((".lrcat-data", ".lrdata")) for part in components)
        ):
            prohibited_values.append(path)
    prohibited = tuple(prohibited_values)
    return RepositoryHygieneReport(not prohibited, len(normalized), prohibited)
