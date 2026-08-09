"""Read-only filesystem inventory for a Phase 0 session."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


RECOGNIZED_EXTENSIONS = {
    ".nef": "raw",
    ".jpg": "image",
    ".jpeg": "image",
    ".xmp": "sidecar",
    ".acr": "auxiliary",
}
PROHIBITED_SUFFIXES = (".lrcat", ".lrcat-data", ".lrdata")


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """An admitted regular file, represented without an absolute path."""

    relative_path: str
    filename: str
    original_extension: str
    normalized_extension: str
    category: str
    size_bytes: int
    modified_at: str
    status: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InventoryNotice:
    """A safely reported ignored or rejected filesystem element."""

    relative_path: str
    filename: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class InventoryResult:
    """Immutable inventory result with separate media-type counts."""

    entries: tuple[InventoryEntry, ...]
    ignored: tuple[InventoryNotice, ...]
    rejected: tuple[InventoryNotice, ...]
    photo_count: int
    sidecar_count: int
    auxiliary_count: int
    warnings: tuple[str, ...]


def _relative_text(relative: PurePosixPath) -> str:
    return relative.as_posix()


def _sort_key(relative_path: str) -> tuple[str, str]:
    """Sort case-insensitively first, then by the original relative path."""

    return relative_path.casefold(), relative_path


def _stable_timestamp(modified_ns: int) -> str:
    seconds, nanoseconds = divmod(modified_ns, 1_000_000_000)
    base = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{nanoseconds:09d}Z"


def _stat_entry(entry: os.DirEntry[str]) -> os.stat_result:
    """Read filesystem metadata without following the entry."""

    return entry.stat(follow_symlinks=False)


def _is_reparse_stat(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _prohibited(name: str) -> bool:
    return name.casefold().endswith(PROHIBITED_SUFFIXES)


def _notice(relative: PurePosixPath, status: str, reason: str) -> InventoryNotice:
    return InventoryNotice(
        relative_path=_relative_text(relative),
        filename=relative.name,
        status=status,
        reason=reason,
    )


def _scan_directory(
    directory: Path,
) -> tuple[list[os.DirEntry[str]], bool]:
    """Collect visible entries and indicate an isolated enumeration error."""

    entries: list[os.DirEntry[str]] = []
    failed = False
    try:
        with os.scandir(directory) as iterator:
            while True:
                try:
                    entries.append(next(iterator))
                except StopIteration:
                    break
                except OSError:
                    failed = True
                    break
    except OSError:
        failed = True
    entries.sort(key=lambda item: (item.name.casefold(), item.name))
    return entries, failed


def _inventory_session(
    root: Path,
    *,
    recursive: bool,
    target_photo_count: int,
) -> InventoryResult:
    """Inventory a validated session root without reading file contents."""

    if not isinstance(recursive, bool):
        raise TypeError("recursive must be a boolean")
    if not isinstance(target_photo_count, int) or isinstance(target_photo_count, bool):
        raise TypeError("target_photo_count must be an integer")
    if target_photo_count < 1:
        raise ValueError("target_photo_count must be positive")

    admitted: list[InventoryEntry] = []
    ignored: list[InventoryNotice] = []
    rejected: list[InventoryNotice] = []
    pending: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath("."))]

    while pending:
        directory, relative_directory = pending.pop()
        children, enumeration_failed = _scan_directory(directory)
        if enumeration_failed:
            rejected.append(
                _notice(relative_directory, "rejected", "directory_enumeration_error")
            )

        directories: list[tuple[Path, PurePosixPath]] = []
        for child in children:
            relative = relative_directory / child.name
            if _prohibited(child.name):
                rejected.append(_notice(relative, "rejected", "lightroom_data_prohibited"))
                continue

            try:
                metadata = _stat_entry(child)
            except OSError:
                rejected.append(_notice(relative, "rejected", "metadata_unavailable"))
                continue

            if stat.S_ISLNK(metadata.st_mode) or _is_reparse_stat(metadata):
                rejected.append(_notice(relative, "rejected", "link_or_reparse_point"))
                continue

            if stat.S_ISDIR(metadata.st_mode):
                if recursive:
                    directories.append((Path(child.path), relative))
                else:
                    ignored.append(_notice(relative, "ignored", "recursion_disabled"))
                continue

            if not stat.S_ISREG(metadata.st_mode):
                rejected.append(_notice(relative, "rejected", "unsupported_filesystem_type"))
                continue

            original_extension = Path(child.name).suffix
            normalized_extension = original_extension.casefold()
            category = RECOGNIZED_EXTENSIONS.get(normalized_extension)
            if category is None:
                ignored.append(_notice(relative, "ignored", "unsupported_extension"))
                continue

            try:
                modified_at = _stable_timestamp(metadata.st_mtime_ns)
            except (OSError, OverflowError, ValueError):
                rejected.append(_notice(relative, "rejected", "metadata_unavailable"))
                continue
            admitted.append(
                InventoryEntry(
                    relative_path=_relative_text(relative),
                    filename=child.name,
                    original_extension=original_extension,
                    normalized_extension=normalized_extension,
                    category=category,
                    size_bytes=metadata.st_size,
                    modified_at=modified_at,
                    status="admitted",
                    warnings=(),
                )
            )

        # Reverse push preserves the documented ascending directory traversal.
        for item in reversed(directories):
            pending.append(item)

    admitted.sort(key=lambda item: _sort_key(item.relative_path))
    ignored.sort(key=lambda item: _sort_key(item.relative_path))
    rejected.sort(key=lambda item: _sort_key(item.relative_path))

    photo_count = sum(item.category in {"raw", "image"} for item in admitted)
    sidecar_count = sum(item.category == "sidecar" for item in admitted)
    auxiliary_count = sum(item.category == "auxiliary" for item in admitted)
    warnings = (
        ("photo_volume_exceeds_target",)
        if photo_count > target_photo_count
        else ()
    )
    return InventoryResult(
        entries=tuple(admitted),
        ignored=tuple(ignored),
        rejected=tuple(rejected),
        photo_count=photo_count,
        sidecar_count=sidecar_count,
        auxiliary_count=auxiliary_count,
        warnings=warnings,
    )
