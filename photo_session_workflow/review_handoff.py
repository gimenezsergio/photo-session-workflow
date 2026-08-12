"""Local review and explicit in-memory download handoff for Phase 0 packages."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from zipfile import BadZipFile, ZIP_STORED, ZipFile

from .confirmed_review_package import ConfirmedReviewPackageResult
from .paths import PathBoundaryError, WorkspaceWriter


class ReviewHandoffError(ValueError):
    """Raised when a review package or explicit download request is invalid."""


@dataclass(frozen=True, slots=True)
class ReviewAssetSummary:
    asset_id: str
    identifier_name: str
    rating: int
    preview_source: str
    proxy_member: str
    width_px: int
    height_px: int
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewPackageSummary:
    package_relative_path: str
    download_name: str
    size_bytes: int
    sha256: str
    schema_version: str
    selected_count: int
    contact_sheet_member: str
    members: tuple[str, ...]
    assets: tuple[ReviewAssetSummary, ...]
    warnings: tuple[str, ...]
    privacy_notices: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class ManualDownload:
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    content: bytes = field(repr=False)


_TOP_LEVEL_KEYS = {
    "schema_version",
    "selected_count",
    "contact_sheet_member",
    "assets",
    "warnings",
}
_ASSET_KEYS = {
    "asset_id",
    "identifier_name",
    "rating",
    "preview_source",
    "proxy_member",
    "width_px",
    "height_px",
    "warnings",
}
_PRIVACY_NOTICES = (
    "package_contains_identifiable_images",
    "sharing_requires_explicit_user_action",
    "no_automatic_external_transmission",
)


def _safe_relative_path(value: object, *, suffix: str | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewHandoffError("review package contains an unsafe relative path")
    posix = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or "\\" in value
        or posix == PurePosixPath(".")
    ):
        raise ReviewHandoffError("review package contains an unsafe relative path")
    if suffix is not None and posix.suffix.casefold() != suffix:
        raise ReviewHandoffError("review package path has an invalid extension")
    return posix.as_posix()


def _warning_codes(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or re.fullmatch(r"[a-z0-9_]+", item) is None
        for item in value
    ):
        raise ReviewHandoffError(f"{label} must contain sanitized codes")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise ReviewHandoffError(f"{label} contains duplicates")
    return result


def _positive_integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ReviewHandoffError(f"{label} must be a positive integer")
    return value


def _asset(value: object) -> ReviewAssetSummary:
    if not isinstance(value, dict) or set(value) != _ASSET_KEYS:
        raise ReviewHandoffError("review manifest asset fields are invalid")
    asset_id = value["asset_id"]
    identifier = value["identifier_name"]
    rating = value["rating"]
    source = value["preview_source"]
    if (
        not isinstance(asset_id, str)
        or not asset_id.startswith("asset:")
        or any(character.isspace() or ord(character) < 32 for character in asset_id)
        or "/" in asset_id
        or "\\" in asset_id
    ):
        raise ReviewHandoffError("review manifest asset id is invalid")
    if (
        not isinstance(identifier, str)
        or not identifier
        or identifier in {".", ".."}
        or "/" in identifier
        or "\\" in identifier
        or any(ord(character) < 32 for character in identifier)
    ):
        raise ReviewHandoffError("review manifest identifier is invalid")
    if not isinstance(rating, int) or isinstance(rating, bool) or rating not in range(1, 6):
        raise ReviewHandoffError("review manifest rating is invalid")
    if source != "lightroom_export":
        raise ReviewHandoffError("review manifest preview source is invalid")
    member = _safe_relative_path(value["proxy_member"], suffix=".jpg")
    if PurePosixPath(member).parent != PurePosixPath("images"):
        raise ReviewHandoffError("review manifest proxy member is invalid")
    return ReviewAssetSummary(
        asset_id,
        identifier,
        rating,
        source,
        member,
        _positive_integer(value["width_px"], label="proxy width"),
        _positive_integer(value["height_px"], label="proxy height"),
        _warning_codes(value["warnings"], label="asset warnings"),
    )


def _read_package(
    writer: WorkspaceWriter,
    relative_path: str,
    *,
    max_package_bytes: int,
) -> bytes:
    if (
        not isinstance(max_package_bytes, int)
        or isinstance(max_package_bytes, bool)
        or max_package_bytes < 1
    ):
        raise ReviewHandoffError("max_package_bytes must be a positive integer")
    path = _safe_relative_path(relative_path, suffix=".zip")
    try:
        payload = writer.read_bytes(path, max_bytes=max_package_bytes)
    except (OSError, PathBoundaryError) as exc:
        raise ReviewHandoffError("review package is unavailable") from exc
    if len(payload) > max_package_bytes:
        raise ReviewHandoffError("review package exceeds configured limit")
    return payload


def inspect_review_package(
    writer: WorkspaceWriter,
    package: ConfirmedReviewPackageResult,
    *,
    max_package_bytes: int,
) -> ReviewPackageSummary:
    """Validate package 0.3 and return a sanitized, image-free review summary."""

    if not isinstance(package, ConfirmedReviewPackageResult):
        raise ReviewHandoffError("confirmed review package result is required")
    relative_path = _safe_relative_path(package.relative_path, suffix=".zip")
    if (
        not isinstance(package.size_bytes, int)
        or isinstance(package.size_bytes, bool)
        or package.size_bytes < 1
        or not re.fullmatch(r"[0-9a-f]{64}", package.sha256)
    ):
        raise ReviewHandoffError("review package integrity metadata is invalid")
    payload = _read_package(
        writer,
        relative_path,
        max_package_bytes=max_package_bytes,
    )
    if len(payload) != package.size_bytes:
        raise ReviewHandoffError("review package size does not match")
    if hashlib.sha256(payload).hexdigest() != package.sha256:
        raise ReviewHandoffError("review package hash does not match")

    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            members = tuple(info.filename for info in infos)
            safe_members = tuple(_safe_relative_path(name) for name in members)
            if members != safe_members:
                raise ReviewHandoffError("review ZIP member path is not canonical")
            if len({name.casefold() for name in members}) != len(members):
                raise ReviewHandoffError("review ZIP contains duplicate members")
            if any(
                info.is_dir()
                or info.flag_bits & 0x1
                or info.compress_type != ZIP_STORED
                for info in infos
            ):
                raise ReviewHandoffError("review ZIP member format is invalid")
            if members != package.members:
                raise ReviewHandoffError("review ZIP members do not match package result")
            if not members or members[0] != "manifest.json":
                raise ReviewHandoffError("review ZIP manifest member is missing")
            raw_manifest = archive.read("manifest.json")
    except ReviewHandoffError:
        raise
    except (BadZipFile, KeyError, OSError, RuntimeError) as exc:
        raise ReviewHandoffError("review package ZIP is invalid") from exc

    try:
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewHandoffError("review manifest JSON is invalid") from exc
    if not isinstance(manifest, dict) or set(manifest) != _TOP_LEVEL_KEYS:
        raise ReviewHandoffError("review manifest fields are invalid")
    if manifest["schema_version"] != "0.3":
        raise ReviewHandoffError("review manifest schema is unsupported")
    selected_count = _positive_integer(
        manifest["selected_count"], label="selected_count"
    )
    contact_sheet = _safe_relative_path(manifest["contact_sheet_member"], suffix=".jpg")
    if contact_sheet != "contact-sheet.jpg":
        raise ReviewHandoffError("review contact sheet member is invalid")
    raw_assets = manifest["assets"]
    if not isinstance(raw_assets, list):
        raise ReviewHandoffError("review manifest assets must be a list")
    assets = tuple(_asset(item) for item in raw_assets)
    if len(assets) != selected_count:
        raise ReviewHandoffError("review manifest selected count does not match assets")
    asset_ids = tuple(item.asset_id for item in assets)
    proxy_members = tuple(item.proxy_member for item in assets)
    if len(set(asset_ids)) != len(asset_ids):
        raise ReviewHandoffError("review manifest contains duplicate assets")
    if len({name.casefold() for name in proxy_members}) != len(proxy_members):
        raise ReviewHandoffError("review manifest contains duplicate proxy members")
    expected_members = ("manifest.json", contact_sheet, *proxy_members)
    if members != expected_members:
        raise ReviewHandoffError("review manifest does not describe the ZIP members")
    warnings = _warning_codes(manifest["warnings"], label="package warnings")
    if raw_manifest.decode("utf-8") != package.manifest.to_json():
        raise ReviewHandoffError("review manifest does not match package result")

    return ReviewPackageSummary(
        relative_path,
        PurePosixPath(relative_path).name,
        len(payload),
        package.sha256,
        "0.3",
        selected_count,
        contact_sheet,
        members,
        assets,
        warnings,
        _PRIVACY_NOTICES,
    )


def prepare_manual_download(
    writer: WorkspaceWriter,
    review: ReviewPackageSummary,
    *,
    explicit_download: bool,
    max_package_bytes: int,
) -> ManualDownload:
    """Return verified ZIP bytes only after an explicit local user action."""

    if explicit_download is not True:
        raise ReviewHandoffError("manual download requires explicit user action")
    if not isinstance(review, ReviewPackageSummary):
        raise ReviewHandoffError("review package summary is required")
    payload = _read_package(
        writer,
        review.package_relative_path,
        max_package_bytes=max_package_bytes,
    )
    if len(payload) != review.size_bytes:
        raise ReviewHandoffError("review package changed after review")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != review.sha256:
        raise ReviewHandoffError("review package changed after review")
    return ManualDownload(
        review.download_name,
        "application/zip",
        len(payload),
        digest,
        payload,
    )
