"""Canonical Phase 0 package from an explicitly confirmed proxy selection."""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath, PureWindowsPath
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from .contact_sheet import (
    ContactSheetError,
    ContactSheetSettings,
    generate_contact_sheet,
)
from .paths import PathBoundaryError, WorkspaceWriter
from .proxies import ProxyBatchResult, ProxyEntry
from .selection_confirmation import (
    ConfirmedSelection,
    SelectionCandidate,
    SelectionConfirmationError,
    validate_confirmed_selection,
)


class ConfirmedReviewPackageError(ValueError):
    """Raised for sanitized validation or publication failures."""


class ConfirmedReviewPackageLimitError(ConfirmedReviewPackageError):
    """Raised before publication when configured package limits are exceeded."""


@dataclass(frozen=True, slots=True)
class ConfirmedReviewPackageLimits:
    max_proxy_bytes: int = 10_000_000
    max_contact_sheet_bytes: int = 50_000_000
    max_package_bytes: int = 250_000_000

    @classmethod
    def create(
        cls,
        *,
        max_proxy_bytes: int = 10_000_000,
        max_contact_sheet_bytes: int = 50_000_000,
        max_package_bytes: int = 250_000_000,
    ) -> "ConfirmedReviewPackageLimits":
        for name, value in (
            ("max_proxy_bytes", max_proxy_bytes),
            ("max_contact_sheet_bytes", max_contact_sheet_bytes),
            ("max_package_bytes", max_package_bytes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if max_package_bytes < max(max_proxy_bytes, max_contact_sheet_bytes):
            raise ValueError(
                "max_package_bytes must not be smaller than an individual limit"
            )
        return cls(max_proxy_bytes, max_contact_sheet_bytes, max_package_bytes)


@dataclass(frozen=True, slots=True)
class ConfirmedManifestAsset:
    asset_id: str
    identifier_name: str
    rating: int
    preview_source: str
    proxy_member: str
    width_px: int
    height_px: int
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfirmedReviewManifest:
    schema_version: str
    selected_count: int
    contact_sheet_member: str
    assets: tuple[ConfirmedManifestAsset, ...]
    warnings: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class ConfirmedReviewPackageResult:
    relative_path: str
    size_bytes: int
    sha256: str
    manifest: ConfirmedReviewManifest
    members: tuple[str, ...]
    contact_sheet_relative_path: str


def _relative_destination(value: str | os.PathLike[str]) -> str:
    text = os.fspath(value)
    posix = PurePosixPath(text.replace("\\", "/"))
    windows = PureWindowsPath(text)
    if (
        not text
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or posix.suffix.casefold() != ".zip"
    ):
        raise ConfirmedReviewPackageError(
            "confirmed package destination must be a relative ZIP path"
        )
    return posix.as_posix()


def _safe_proxy_member(candidate: SelectionCandidate) -> str:
    filename = PurePosixPath(candidate.proxy_relative_path).name
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
        or posix.suffix.casefold() != ".jpg"
    ):
        raise ConfirmedReviewPackageError("confirmed proxy filename is unsafe")
    return f"images/{filename}"


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    return info


def _confirmed_proxy_batch(
    proxies: ProxyBatchResult,
    confirmation: ConfirmedSelection,
) -> ProxyBatchResult:
    by_id: dict[str, ProxyEntry] = {}
    for entry in proxies.entries:
        if entry.asset_id in by_id:
            raise ConfirmedReviewPackageError(
                "proxy batch contains duplicate asset ids"
            )
        by_id[entry.asset_id] = entry

    selected: list[ProxyEntry] = []
    for candidate in confirmation.selected:
        entry = by_id.get(candidate.asset_id)
        if entry is None:
            raise ConfirmedReviewPackageError(
                "confirmed asset is absent from proxy batch"
            )
        if (
            entry.status not in {"generated", "reused"}
            or entry.error_code is not None
            or entry.identifier_name != candidate.identifier_name
            or entry.rating != candidate.rating
            or entry.preview_source != candidate.preview_source
            or entry.source_relative_path != candidate.source_relative_path
            or entry.source_sha256 != candidate.source_sha256
            or entry.proxy_relative_path != candidate.proxy_relative_path
            or entry.sha256 != candidate.proxy_sha256
            or entry.width_px != candidate.proxy_width_px
            or entry.height_px != candidate.proxy_height_px
            or entry.size_bytes != candidate.proxy_size_bytes
        ):
            raise ConfirmedReviewPackageError(
                "confirmed asset no longer matches its proxy result"
            )
        selected.append(entry)
    values = tuple(selected)
    return ProxyBatchResult(
        values,
        sum(item.status == "generated" for item in values),
        sum(item.status == "reused" for item in values),
        0,
    )


def _read_verified(
    writer: WorkspaceWriter,
    *,
    relative_path: str,
    expected_sha256: str,
    max_bytes: int,
    label: str,
) -> bytes:
    try:
        payload = writer.read_bytes(relative_path, max_bytes=max_bytes)
    except (OSError, PathBoundaryError) as exc:
        raise ConfirmedReviewPackageError(f"{label} is unavailable") from exc
    if len(payload) > max_bytes:
        raise ConfirmedReviewPackageLimitError(f"{label} exceeds configured limit")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ConfirmedReviewPackageError(f"{label} hash does not match")
    return payload


def generate_confirmed_review_package(
    writer: WorkspaceWriter,
    *,
    proxies: ProxyBatchResult,
    confirmation: ConfirmedSelection,
    contact_sheet_settings: ContactSheetSettings,
    destination_relative_path: str,
    limits: ConfirmedReviewPackageLimits,
) -> ConfirmedReviewPackageResult:
    """Generate the canonical local package without reading the source session."""

    destination = _relative_destination(destination_relative_path)
    try:
        validated = validate_confirmed_selection(confirmation)
    except SelectionConfirmationError as exc:
        raise ConfirmedReviewPackageError(str(exc)) from exc
    selected_proxies = _confirmed_proxy_batch(proxies, validated)
    try:
        contact_sheet = generate_contact_sheet(
            writer,
            proxies=selected_proxies,
            settings=contact_sheet_settings,
            destination_relative_directory="contact-sheets/confirmed",
        )
    except ContactSheetError as exc:
        raise ConfirmedReviewPackageError(
            "confirmed contact sheet could not be generated"
        ) from exc
    contact_payload = _read_verified(
        writer,
        relative_path=contact_sheet.relative_path,
        expected_sha256=contact_sheet.sha256,
        max_bytes=limits.max_contact_sheet_bytes,
        label="confirmed contact sheet",
    )

    candidates = {item.asset_id: item for item in validated.selected}
    proxy_members: list[tuple[str, ProxyEntry, bytes]] = []
    manifest_assets: list[ConfirmedManifestAsset] = []
    projected_size = len(contact_payload)
    for entry in selected_proxies.entries:
        candidate = candidates[entry.asset_id]
        member = _safe_proxy_member(candidate)
        remaining = limits.max_package_bytes - projected_size
        if remaining < 1:
            raise ConfirmedReviewPackageLimitError(
                "confirmed proxies exceed package limit"
            )
        read_limit = min(limits.max_proxy_bytes, remaining)
        payload = _read_verified(
            writer,
            relative_path=candidate.proxy_relative_path,
            expected_sha256=candidate.proxy_sha256,
            max_bytes=read_limit,
            label="confirmed proxy",
        )
        projected_size += len(payload)
        proxy_members.append((member, entry, payload))
        manifest_assets.append(
            ConfirmedManifestAsset(
                entry.asset_id,
                entry.identifier_name,
                entry.rating,
                entry.preview_source,
                member,
                entry.width_px,  # type: ignore[arg-type]
                entry.height_px,  # type: ignore[arg-type]
                entry.warnings,
            )
        )
    member_names = [member for member, _, _ in proxy_members]
    if len({name.casefold() for name in member_names}) != len(member_names):
        raise ConfirmedReviewPackageError("confirmed proxy members are not unique")

    manifest = ConfirmedReviewManifest(
        "0.3",
        len(manifest_assets),
        "contact-sheet.jpg",
        tuple(manifest_assets),
        (
            "proxies_contain_identifiable_images",
            "manual_external_sharing_requires_user_action",
            "no_automatic_transmission",
        ),
    )
    manifest_bytes = manifest.to_json().encode("utf-8")
    projected_size += len(manifest_bytes)
    if projected_size > limits.max_package_bytes:
        raise ConfirmedReviewPackageLimitError(
            "confirmed package content exceeds configured limit"
        )

    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED, allowZip64=True) as archive:
        archive.writestr(_zip_info("manifest.json"), manifest_bytes)
        archive.writestr(_zip_info("contact-sheet.jpg"), contact_payload)
        for member, _, payload in proxy_members:
            archive.writestr(_zip_info(member), payload)
    package = buffer.getvalue()
    if len(package) > limits.max_package_bytes:
        raise ConfirmedReviewPackageLimitError(
            "confirmed ZIP exceeds configured limit"
        )
    try:
        writer.publish_bytes_atomically(destination, package)
    except FileExistsError:
        raise
    except (OSError, PathBoundaryError) as exc:
        raise ConfirmedReviewPackageError(
            "confirmed package could not be published"
        ) from exc
    return ConfirmedReviewPackageResult(
        destination,
        len(package),
        hashlib.sha256(package).hexdigest(),
        manifest,
        ("manifest.json", "contact-sheet.jpg", *member_names),
        contact_sheet.relative_path,
    )
