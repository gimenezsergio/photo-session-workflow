"""Deterministic local review manifest and ZIP from declared Lightroom exports."""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath, PureWindowsPath
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from .lightroom_exports import (
    LightroomExportResolution,
    LightroomExportResolutionResult,
)
from .paths import SessionReader, WorkspaceWriter
from .selection_confirmation import (
    ConfirmedSelection,
    SelectionConfirmationError,
    validate_confirmed_selection,
)


class ReviewPackageError(ValueError):
    """Base class for sanitized package failures."""


class ReviewPackageIncompleteError(ReviewPackageError):
    """Raised before reading images when any selected export is unresolved."""

    def __init__(self, failures: tuple[tuple[str, str], ...]) -> None:
        super().__init__("all selected assets require one valid Lightroom export")
        self.failures = failures


class ReviewPackageLimitError(ReviewPackageError):
    """Raised when an individual image or the complete package exceeds its limit."""


class ReviewPackageConfirmationError(ReviewPackageError):
    """Raised before reading exports when explicit confirmation is absent or stale."""


@dataclass(frozen=True, slots=True)
class ReviewPackageLimits:
    max_jpg_bytes: int
    max_package_bytes: int

    @classmethod
    def create(
        cls,
        *,
        max_jpg_bytes: int = 25_000_000,
        max_package_bytes: int = 250_000_000,
    ) -> "ReviewPackageLimits":
        for name, value in (
            ("max_jpg_bytes", max_jpg_bytes),
            ("max_package_bytes", max_package_bytes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if max_package_bytes < max_jpg_bytes:
            raise ValueError("max_package_bytes must not be smaller than max_jpg_bytes")
        return cls(max_jpg_bytes, max_package_bytes)


@dataclass(frozen=True, slots=True)
class ReviewManifestAsset:
    asset_id: str
    identifier_name: str
    rating: int
    xmp_relative_path: str | None
    preview_source: str
    preview_relative_path: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewManifest:
    schema_version: str
    selected_count: int
    assets: tuple[ReviewManifestAsset, ...]

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class ReviewPackageResult:
    relative_path: str
    size_bytes: int
    sha256: str
    manifest: ReviewManifest
    members: tuple[str, ...]


def build_review_manifest(
    resolutions: LightroomExportResolutionResult,
) -> ReviewManifest:
    failures = tuple(
        (item.identifier_name, item.status)
        for item in resolutions.resolutions
        if item.status != "resolved"
    )
    if failures:
        raise ReviewPackageIncompleteError(failures)
    assets = tuple(
        ReviewManifestAsset(
            item.asset_id,
            item.identifier_name,
            item.rating,
            item.xmp_relative_path,
            "lightroom_export",
            item.export.relative_path,  # type: ignore[union-attr]
            item.warnings,
        )
        for item in resolutions.resolutions
    )
    return ReviewManifest("0.2", len(assets), assets)


def _safe_image_member(resolution: LightroomExportResolution) -> str:
    filename = resolution.export.filename  # type: ignore[union-attr]
    posix = PurePosixPath(filename)
    windows = PureWindowsPath(filename)
    if (
        not filename
        or filename in {".", ".."}
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or posix.name != filename
        or "\\" in filename
        or posix.suffix.casefold() not in {".jpg", ".jpeg"}
    ):
        raise ReviewPackageError("unsafe Lightroom export filename")
    return f"images/{filename}"


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    return info


def generate_review_package(
    reader: SessionReader,
    writer: WorkspaceWriter,
    *,
    export_relative_directory: str,
    resolutions: LightroomExportResolutionResult,
    destination_relative_path: str,
    limits: ReviewPackageLimits,
    confirmation: ConfirmedSelection | None = None,
) -> ReviewPackageResult:
    """Build completely in memory, then exclusively publish one atomic ZIP."""

    safe_destination = _relative_result(destination_relative_path)
    confirmed_resolutions, validated_confirmation = _confirmed_resolutions(
        resolutions, confirmation
    )
    manifest = build_review_manifest(confirmed_resolutions)
    manifest_bytes = manifest.to_json().encode("utf-8")
    if len(manifest_bytes) > limits.max_package_bytes:
        raise ReviewPackageLimitError("manifest exceeds package size limit")

    resolved = sorted(
        confirmed_resolutions.resolutions,
        key=lambda item: (item.asset_id.casefold(), item.asset_id),
    )
    member_names = [_safe_image_member(item) for item in resolved]
    if len({name.casefold() for name in member_names}) != len(member_names):
        raise ReviewPackageError("ZIP image names are not unique")

    confirmed_candidates = {
        item.asset_id: item for item in validated_confirmation.selected
    }
    images: list[tuple[str, bytes]] = []
    projected_size = len(manifest_bytes)
    for item, member_name in zip(resolved, member_names):
        remaining_package_bytes = limits.max_package_bytes - projected_size
        if remaining_package_bytes < 1:
            raise ReviewPackageLimitError("selected images exceed package size limit")
        read_limit = min(limits.max_jpg_bytes, remaining_package_bytes)
        payload = reader.read_lightroom_export(
            export_relative_directory,
            item.export.relative_path,  # type: ignore[union-attr]
            max_bytes=read_limit,
        )
        if len(payload) > read_limit:
            if read_limit == limits.max_jpg_bytes:
                raise ReviewPackageLimitError(
                    f"JPG exceeds individual limit: {item.identifier_name}"
                )
            raise ReviewPackageLimitError("selected images exceed package size limit")
        candidate = confirmed_candidates[item.asset_id]
        if hashlib.sha256(payload).hexdigest() != candidate.source_sha256:
            raise ReviewPackageConfirmationError(
                "confirmed Lightroom export changed after proxy generation"
            )
        projected_size += len(payload)
        images.append((member_name, payload))

    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED, allowZip64=True) as archive:
        archive.writestr(_zip_info("manifest.json"), manifest_bytes)
        for member_name, payload in images:
            archive.writestr(_zip_info(member_name), payload)
    package = buffer.getvalue()
    if len(package) > limits.max_package_bytes:
        raise ReviewPackageLimitError("ZIP exceeds package size limit")

    writer.publish_bytes_atomically(safe_destination, package)
    return ReviewPackageResult(
        safe_destination,
        len(package),
        hashlib.sha256(package).hexdigest(),
        manifest,
        ("manifest.json", *member_names),
    )


def _confirmed_resolutions(
    resolutions: LightroomExportResolutionResult,
    confirmation: ConfirmedSelection | None,
) -> tuple[LightroomExportResolutionResult, ConfirmedSelection]:
    try:
        validated = validate_confirmed_selection(confirmation)
    except SelectionConfirmationError as exc:
        raise ReviewPackageConfirmationError(str(exc)) from exc
    by_id: dict[str, LightroomExportResolution] = {}
    for item in resolutions.resolutions:
        if item.asset_id in by_id:
            raise ReviewPackageConfirmationError(
                "export resolutions contain duplicate asset ids"
            )
        by_id[item.asset_id] = item

    selected: list[LightroomExportResolution] = []
    for candidate in validated.selected:
        resolution = by_id.get(candidate.asset_id)
        if resolution is None:
            raise ReviewPackageConfirmationError(
                "confirmed asset is absent from export resolutions"
            )
        if resolution.status != "resolved" or resolution.export is None:
            raise ReviewPackageConfirmationError(
                "confirmed asset no longer has a resolved export"
            )
        if (
            resolution.identifier_name != candidate.identifier_name
            or resolution.rating != candidate.rating
            or resolution.export.relative_path != candidate.source_relative_path
        ):
            raise ReviewPackageConfirmationError(
                "confirmed asset no longer matches its export resolution"
            )
        selected.append(resolution)
    values = tuple(selected)
    return LightroomExportResolutionResult(values, len(values), 0, 0, 0), validated


def _relative_result(value: str | os.PathLike[str]) -> str:
    """Return a safe relative POSIX result without exposing the workspace root."""

    text = os.fspath(value)
    posix = PurePosixPath(text.replace("\\", "/"))
    windows = PureWindowsPath(text)
    if not text or posix.is_absolute() or windows.is_absolute() or ".." in posix.parts:
        raise ReviewPackageError("package destination must be relative")
    return posix.as_posix()
