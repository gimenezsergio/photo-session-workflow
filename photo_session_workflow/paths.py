"""Path boundaries and capability-specific filesystem access."""

from __future__ import annotations

import os
import hashlib
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from .exif import ExifReadResult, ExifSourceSelection, ExifToolAdapter
    from .inventory import InventoryResult
    from .lightroom_exports import LightroomExportInventory
    from .xmp_rating import RatingReadResult, RatingSourceSelection, XmpRatingReader


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


def _binary_content(content: object) -> bytes:
    """Copy explicitly supported binary inputs before touching the filesystem."""

    if isinstance(content, bytes):
        return content
    if isinstance(content, (bytearray, memoryview)):
        return bytes(content)
    raise TypeError("content must be bytes, bytearray, or memoryview")


def _write_stream(stream: BinaryIO, content: bytes) -> None:
    """Write and synchronize a complete binary payload."""

    stream.write(content)
    stream.flush()
    os.fsync(stream.fileno())


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
        if any(
            part.casefold().endswith((".lrcat", ".lrcat-data", ".lrdata"))
            for part in relative.parts
        ):
            raise PathBoundaryError("Lightroom catalog data is prohibited")
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

    def fingerprint_file(
        self,
        relative_path: str | os.PathLike[str],
        *,
        chunk_size: int = 1_048_576,
    ) -> tuple[int, int, str]:
        """Return size, mtime nanoseconds and SHA-256 with bounded memory."""

        if (
            not isinstance(chunk_size, int)
            or isinstance(chunk_size, bool)
            or not 4_096 <= chunk_size <= 16_777_216
        ):
            raise ValueError("chunk_size must be between 4096 and 16777216")
        digest = hashlib.sha256()
        size = 0
        source = self._existing_file(relative_path)
        try:
            before = source.stat(follow_symlinks=False)
        except OSError as exc:
            raise PathBoundaryError("session file metadata is unavailable") from exc
        with source.open("rb") as stream:
            while True:
                block = stream.read(chunk_size)
                if not block:
                    break
                size += len(block)
                digest.update(block)
        try:
            after = source.stat(follow_symlinks=False)
        except OSError as exc:
            raise PathBoundaryError("session file metadata is unavailable") from exc
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or size != after.st_size
        ):
            raise PathBoundaryError("session file changed during fingerprint")
        return size, after.st_mtime_ns, digest.hexdigest()

    def inventory(
        self,
        *,
        recursive: bool = True,
        target_photo_count: int = 200,
    ) -> "InventoryResult":
        """Return an immutable metadata-only inventory of the session."""

        from .inventory import _inventory_session

        return _inventory_session(
            self._root,
            recursive=recursive,
            target_photo_count=target_photo_count,
        )

    def _validated_export_directory(
        self, relative_directory: str | os.PathLike[str]
    ) -> Path:
        relative = Path(relative_directory)
        if (
            not os.fspath(relative_directory)
            or relative.is_absolute()
            or bool(relative.drive)
            or relative == Path(".")
            or ".." in relative.parts
        ):
            raise PathBoundaryError(
                "lightroom export directory must be a non-empty relative subdirectory"
            )
        candidate = self._root / relative
        reject_links_or_reparse_points(candidate, label="lightroom export directory")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PathBoundaryError(
                "lightroom export directory must reference an existing directory"
            ) from exc
        if not _contains(self._root, resolved) or resolved == self._root:
            raise PathBoundaryError("lightroom export directory escapes session_root")
        if not resolved.is_dir():
            raise PathBoundaryError("lightroom export directory must reference a directory")
        return resolved

    def validate_lightroom_export_directory(
        self, relative_directory: str | os.PathLike[str]
    ) -> None:
        """Validate a declared export directory without exposing its absolute path."""

        self._validated_export_directory(relative_directory)

    def inventory_lightroom_exports(
        self, relative_directory: str | os.PathLike[str]
    ) -> "LightroomExportInventory":
        """Inventory only direct JPG/JPEG children of the declared export directory."""

        from .lightroom_exports import _inventory_lightroom_export_directory

        directory = self._validated_export_directory(relative_directory)
        return _inventory_lightroom_export_directory(directory, Path(relative_directory))

    def read_lightroom_export(
        self,
        relative_directory: str | os.PathLike[str],
        relative_path: str | os.PathLike[str],
        *,
        max_bytes: int,
    ) -> bytes:
        """Read one revalidated export with an explicit upper bound."""

        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        export_root = self._validated_export_directory(relative_directory)
        source = self._existing_file(relative_path)
        if source.parent != export_root:
            raise PathBoundaryError("export file must be a direct child of export directory")
        if source.suffix.casefold() not in {".jpg", ".jpeg"}:
            raise PathBoundaryError("export file must be JPG or JPEG")
        with source.open("rb") as stream:
            return stream.read(max_bytes + 1)

    def _read_exif_with(
        self,
        adapter: "ExifToolAdapter",
        selection: "ExifSourceSelection",
    ) -> "ExifReadResult":
        """Validate a selected source before handing it to the trusted adapter."""

        if selection.relative_path is None:
            raise PathBoundaryError("EXIF source must be a relative session file")
        source = self._existing_file(selection.relative_path)
        return adapter._read_validated_path(source, selection)

    def _read_xmp_rating_with(
        self,
        xmp_reader: "XmpRatingReader",
        selection: "RatingSourceSelection",
    ) -> "RatingReadResult":
        """Open one validated XMP sidecar for the trusted bounded parser."""

        if selection.relative_path is None:
            raise PathBoundaryError("XMP source must be a relative session file")
        source = self._existing_file(selection.relative_path)
        with source.open("rb") as stream:
            return xmp_reader._read_validated_stream(stream, selection)


class WorkspaceWriter:
    """Write capability restricted to the configured private workspace."""

    __slots__ = ("_root",)

    def __init__(self, boundaries: RootBoundaries) -> None:
        self._root = boundaries.workspace_root

    @property
    def root(self) -> Path:
        return self._root

    def ensure_directory(
        self, relative_path: str | os.PathLike[str]
    ) -> None:
        """Create and validate a directory contained by the private workspace."""

        relative = Path(relative_path)
        if (
            not os.fspath(relative_path)
            or relative.is_absolute()
            or bool(relative.drive)
            or relative == Path(".")
            or ".." in relative.parts
        ):
            raise PathBoundaryError(
                "workspace directory must be a non-empty relative subdirectory"
            )
        destination = self._root / relative
        reject_links_or_reparse_points(destination, label="workspace directory")
        try:
            unresolved = destination.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise PathBoundaryError("workspace directory is invalid") from exc
        if not _contains(self._root, unresolved):
            raise PathBoundaryError("workspace directory escapes workspace_root")
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PathBoundaryError("workspace directory could not be created") from exc
        reject_links_or_reparse_points(destination, label="workspace directory")
        try:
            resolved = destination.resolve(strict=True)
            mode = destination.stat(follow_symlinks=False).st_mode
        except (OSError, RuntimeError) as exc:
            raise PathBoundaryError("workspace directory is invalid") from exc
        if not _contains(self._root, resolved) or not stat.S_ISDIR(mode):
            raise PathBoundaryError("workspace directory is invalid")

    def read_bytes(
        self,
        relative_path: str | os.PathLike[str],
        *,
        max_bytes: int,
    ) -> bytes:
        """Read one regular workspace file with an explicit upper bound."""

        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        relative = Path(relative_path)
        if not os.fspath(relative_path) or relative.is_absolute() or ".." in relative.parts:
            raise PathBoundaryError("workspace path must be a non-empty relative path")
        candidate = self._root / relative
        reject_links_or_reparse_points(candidate, label="workspace path")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PathBoundaryError("workspace path must reference an existing file") from exc
        if not _contains(self._root, resolved):
            raise PathBoundaryError("workspace path escapes workspace_root")
        try:
            mode = candidate.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise PathBoundaryError("workspace path is invalid") from exc
        if not stat.S_ISREG(mode):
            raise PathBoundaryError("workspace path must reference a regular file")
        with resolved.open("rb") as stream:
            return stream.read(max_bytes + 1)

    def write_bytes(
        self,
        relative_path: str | os.PathLike[str],
        content: bytes | bytearray | memoryview,
        *,
        overwrite: bool = False,
    ) -> Path:
        payload = _binary_content(content)
        relative = Path(relative_path)
        if not os.fspath(relative_path) or relative.is_absolute():
            raise PathBoundaryError("workspace path must be a non-empty relative path")
        destination = self._root / relative
        parent = destination.parent
        resolved_parent = self._validated_parent(parent)
        resolved_destination = self._validated_destination(
            resolved_parent / destination.name,
            require_regular=overwrite,
        )

        if overwrite:
            return self._replace_atomically(
                resolved_parent,
                resolved_destination,
                payload,
            )
        return self._create_exclusively(resolved_parent, resolved_destination, payload)

    def publish_bytes_atomically(
        self,
        relative_path: str | os.PathLike[str],
        content: bytes | bytearray | memoryview,
    ) -> Path:
        """Publish a new file atomically without replacing an existing destination."""

        payload = _binary_content(content)
        relative = Path(relative_path)
        if not os.fspath(relative_path) or relative.is_absolute():
            raise PathBoundaryError("workspace path must be a non-empty relative path")
        destination = self._root / relative
        parent = self._validated_parent(destination.parent)
        destination = self._validated_destination(
            parent / destination.name, require_regular=False
        )
        if os.path.lexists(destination):
            raise FileExistsError("workspace destination already exists")

        descriptor = -1
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                _write_stream(stream, payload)

            final_parent = self._validated_parent(destination.parent)
            if final_parent != parent:
                raise PathBoundaryError("workspace parent changed before publication")
            final_destination = self._validated_destination(
                final_parent / destination.name, require_regular=False
            )
            if os.path.lexists(final_destination):
                raise FileExistsError("workspace destination already exists")
            os.link(temporary_path, final_destination, follow_symlinks=False)
            try:
                temporary_path.unlink()
            except OSError:
                try:
                    final_destination.unlink()
                finally:
                    raise
            temporary_path = None
            return final_destination
        finally:
            if descriptor != -1:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    def _validated_parent(self, parent: Path) -> Path:
        reject_links_or_reparse_points(parent, label="workspace path")
        try:
            resolved_parent = parent.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise PathBoundaryError("workspace parent directory must already exist") from exc
        if not _contains(self._root, resolved_parent):
            raise PathBoundaryError("workspace path escapes workspace_root")
        if not stat.S_ISDIR(parent.stat(follow_symlinks=False).st_mode):
            raise PathBoundaryError("workspace parent must be a regular directory")
        return resolved_parent

    def _validated_destination(
        self,
        destination: Path,
        *,
        require_regular: bool,
    ) -> Path:
        reject_links_or_reparse_points(destination, label="workspace destination")
        exists = os.path.lexists(destination)
        if exists:
            try:
                resolved = destination.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise PathBoundaryError("workspace destination is invalid") from exc
            if not _contains(self._root, resolved):
                raise PathBoundaryError("workspace destination escapes workspace_root")
            try:
                mode = destination.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise PathBoundaryError("workspace destination is invalid") from exc
            if not stat.S_ISREG(mode):
                raise PathBoundaryError(
                    "existing workspace destination must be a regular file"
                )
            return resolved

        resolved = destination.resolve(strict=False)
        if not _contains(self._root, resolved):
            raise PathBoundaryError("workspace destination escapes workspace_root")
        if require_regular:
            raise PathBoundaryError(
                "overwrite=True requires an existing regular workspace file"
            )
        return resolved

    def _create_exclusively(
        self,
        expected_parent: Path,
        destination: Path,
        payload: bytes,
    ) -> Path:
        current_parent = self._validated_parent(destination.parent)
        if current_parent != expected_parent:
            raise PathBoundaryError("workspace parent changed before writing")
        destination = self._validated_destination(
            current_parent / destination.name,
            require_regular=False,
        )
        created = False
        try:
            stream = destination.open("xb")
            created = True
            with stream:
                _write_stream(stream, payload)
        except BaseException:
            if created:
                try:
                    destination.unlink()
                except OSError:
                    pass
            raise
        return destination

    def _replace_atomically(
        self,
        expected_parent: Path,
        destination: Path,
        payload: bytes,
    ) -> Path:
        current_parent = self._validated_parent(destination.parent)
        if current_parent != expected_parent:
            raise PathBoundaryError("workspace parent changed before writing")
        destination = self._validated_destination(
            current_parent / destination.name,
            require_regular=True,
        )

        descriptor = -1
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=current_parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                _write_stream(stream, payload)

            final_parent = self._validated_parent(destination.parent)
            if final_parent != current_parent:
                raise PathBoundaryError("workspace parent changed before replacement")
            final_destination = self._validated_destination(
                final_parent / destination.name,
                require_regular=True,
            )
            os.replace(temporary_path, final_destination)
            temporary_path = None
            return final_destination
        finally:
            if descriptor != -1:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
