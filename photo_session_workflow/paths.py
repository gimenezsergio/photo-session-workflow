"""Path boundaries and capability-specific filesystem access."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class PathBoundaryError(ValueError):
    """Raised when a path violates a configured filesystem boundary."""


def _is_reparse_point(path: Path) -> bool:
    """Return whether an existing path is a Windows reparse point."""

    try:
        attributes = path.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _existing_components(path: Path) -> tuple[Path, ...]:
    """Return existing components from the anchor through ``path``."""

    parts = path.parts
    if not parts:
        return ()
    current = Path(parts[0])
    components: list[Path] = [current]
    for part in parts[1:]:
        current = current / part
        if current.exists() or current.is_symlink():
            components.append(current)
    return tuple(components)


def reject_links_or_reparse_points(path: Path, *, label: str) -> None:
    """Reject detectable symlinks and Windows junction/reparse components."""

    for component in _existing_components(path):
        if component.is_symlink() or _is_reparse_point(component):
            raise PathBoundaryError(
                f"{label} must not traverse a symbolic link, junction, or reparse point"
            )


def canonical_directory(value: str | os.PathLike[str], *, label: str) -> Path:
    """Validate and resolve an absolute, existing directory without mutating it."""

    if not isinstance(value, (str, os.PathLike)):
        raise PathBoundaryError(f"{label} must be a filesystem path")
    raw_text = os.fspath(value)
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise PathBoundaryError(f"{label} must not be empty")
    if "\x00" in raw_text:
        raise PathBoundaryError(f"{label} contains an invalid null character")

    raw = Path(raw_text)
    if not raw.is_absolute():
        raise PathBoundaryError(f"{label} must be absolute")
    reject_links_or_reparse_points(raw, label=label)
    try:
        resolved = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PathBoundaryError(f"{label} must reference an existing directory") from exc
    if not resolved.is_dir():
        raise PathBoundaryError(f"{label} must reference a directory")
    return resolved


def _contains(parent: Path, child: Path) -> bool:
    """Return whether canonical ``parent`` contains canonical ``child``."""

    return child == parent or parent in child.parents


def _require_disjoint(left: Path, right: Path, *, left_label: str, right_label: str) -> None:
    if left == right:
        raise PathBoundaryError(f"{left_label} and {right_label} must not be equal")
    if _contains(left, right):
        raise PathBoundaryError(f"{right_label} must not be inside {left_label}")
    if _contains(right, left):
        raise PathBoundaryError(f"{left_label} must not be inside {right_label}")


@dataclass(frozen=True, slots=True, init=False)
class RootBoundaries:
    """Canonical, pairwise-disjoint roots for Phase 0."""

    session_root: Path
    workspace_root: Path
    repository_root: Path

    @classmethod
    def create(
        cls,
        *,
        session_root: str | os.PathLike[str],
        workspace_root: str | os.PathLike[str],
        repository_root: str | os.PathLike[str],
    ) -> "RootBoundaries":
        session = canonical_directory(session_root, label="session_root")
        workspace = canonical_directory(workspace_root, label="workspace_root")
        repository = canonical_directory(repository_root, label="repository_root")

        _require_disjoint(
            session, workspace, left_label="session_root", right_label="workspace_root"
        )
        _require_disjoint(
            workspace, repository, left_label="workspace_root", right_label="repository_root"
        )
        _require_disjoint(
            session, repository, left_label="session_root", right_label="repository_root"
        )

        if not os.access(session, os.R_OK):
            raise PathBoundaryError("session_root must be readable")
        if not os.access(workspace, os.R_OK | os.W_OK):
            raise PathBoundaryError("workspace_root must be readable and writable")
        if not os.access(repository, os.R_OK):
            raise PathBoundaryError("repository_root must be readable")

        boundaries = object.__new__(cls)
        object.__setattr__(boundaries, "session_root", session)
        object.__setattr__(boundaries, "workspace_root", workspace)
        object.__setattr__(boundaries, "repository_root", repository)
        return boundaries


class SessionReader:
    """Read-only capability for files below the configured session root."""

    __slots__ = ("_root",)

    def __init__(self, boundaries: RootBoundaries) -> None:
        self._root = boundaries.session_root

    def _existing_file(self, relative_path: str | os.PathLike[str]) -> Path:
        relative = Path(relative_path)
        if not os.fspath(relative_path) or relative.is_absolute():
            raise PathBoundaryError("session path must be a non-empty relative path")
        candidate = self._root / relative
        reject_links_or_reparse_points(candidate, label="session path")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PathBoundaryError("session path must reference an existing file") from exc
        if not _contains(self._root, resolved):
            raise PathBoundaryError("session path escapes session_root")
        if not resolved.is_file():
            raise PathBoundaryError("session path must reference a file")
        return resolved

    def open_binary(self, relative_path: str | os.PathLike[str]) -> BinaryIO:
        """Open an existing session file with an immutable read mode."""

        return self._existing_file(relative_path).open("rb")

    def read_bytes(self, relative_path: str | os.PathLike[str]) -> bytes:
        with self.open_binary(relative_path) as stream:
            return stream.read()


class WorkspaceWriter:
    """Write capability restricted to the configured private workspace."""

    __slots__ = ("_root",)

    def __init__(self, boundaries: RootBoundaries) -> None:
        self._root = boundaries.workspace_root

    @property
    def root(self) -> Path:
        return self._root

    def write_bytes(
        self,
        relative_path: str | os.PathLike[str],
        content: bytes,
        *,
        overwrite: bool = False,
    ) -> Path:
        relative = Path(relative_path)
        if not os.fspath(relative_path) or relative.is_absolute():
            raise PathBoundaryError("workspace path must be a non-empty relative path")
        destination = self._root / relative
        parent = destination.parent
        reject_links_or_reparse_points(parent, label="workspace path")
        try:
            resolved_parent = parent.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PathBoundaryError("workspace parent directory must already exist") from exc
        if not _contains(self._root, resolved_parent):
            raise PathBoundaryError("workspace path escapes workspace_root")
        resolved_destination = resolved_parent / destination.name
        mode = "wb" if overwrite else "xb"
        with resolved_destination.open(mode) as stream:
            stream.write(content)
        return resolved_destination
