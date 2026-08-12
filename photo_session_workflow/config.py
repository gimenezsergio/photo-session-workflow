"""Load the local Phase 0 path configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .exif import ExifConfigurationError, ExifToolSettings
from .contact_sheet import ContactSheetError, ContactSheetSettings
from .confirmed_review_package import ConfirmedReviewPackageLimits
from .manual_recommendations import ManualRecommendationSettings
from .paths import PathBoundaryError, RootBoundaries, SessionReader
from .proxies import ProxyConfigurationError, ProxySettings
from .review_package import ReviewPackageLimits


class ConfigurationError(ValueError):
    """Raised when the local configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Phase0Config:
    """Validated Phase 0 filesystem configuration."""

    boundaries: RootBoundaries
    exiftool: ExifToolSettings | None = None
    xmp_max_bytes: int = 262_144
    lightroom_export_relative_directory: str | None = None
    review_package_limits: ReviewPackageLimits = ReviewPackageLimits(
        25_000_000, 250_000_000
    )
    proxy_settings: ProxySettings = ProxySettings()
    contact_sheet_settings: ContactSheetSettings = ContactSheetSettings()
    confirmed_review_package_limits: ConfirmedReviewPackageLimits = (
        ConfirmedReviewPackageLimits()
    )
    manual_recommendation_settings: ManualRecommendationSettings = (
        ManualRecommendationSettings()
    )

    @property
    def session_root(self) -> Path:
        return self.boundaries.session_root

    @property
    def workspace_root(self) -> Path:
        return self.boundaries.workspace_root

    @property
    def repository_root(self) -> Path:
        return self.boundaries.repository_root


def load_config(config_path: str | os.PathLike[str]) -> Phase0Config:
    """Load a local JSON file and validate its three filesystem roots."""

    if not isinstance(config_path, (str, os.PathLike)) or not os.fspath(config_path):
        raise ConfigurationError("config_path must not be empty")
    path = Path(config_path)
    try:
        if path.is_symlink() or not path.is_file():
            raise ConfigurationError("config_path must reference a regular file")
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except ConfigurationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("config_path must contain valid UTF-8 JSON") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("paths"), dict):
        raise ConfigurationError("configuration must contain a paths object")
    paths = payload["paths"]
    required = ("session_root", "workspace_root", "repository_root")
    missing = [key for key in required if key not in paths]
    if missing:
        raise ConfigurationError(f"configuration is missing: {', '.join(missing)}")

    try:
        boundaries = RootBoundaries.create(
            session_root=paths["session_root"],
            workspace_root=paths["workspace_root"],
            repository_root=paths["repository_root"],
        )
    except (PathBoundaryError, TypeError) as exc:
        raise ConfigurationError(str(exc)) from exc
    exiftool_payload = payload.get("exiftool")
    if exiftool_payload is None:
        exiftool = None
    elif isinstance(exiftool_payload, dict):
        allowed = {"executable", "timeout_seconds", "max_output_bytes"}
        if set(exiftool_payload) - allowed:
            raise ConfigurationError("exiftool configuration contains unsupported keys")
        if "executable" not in exiftool_payload or "timeout_seconds" not in exiftool_payload:
            raise ConfigurationError(
                "exiftool configuration requires executable and timeout_seconds"
            )
        try:
            exiftool = ExifToolSettings.create(
                executable=exiftool_payload["executable"],
                timeout_seconds=exiftool_payload["timeout_seconds"],
                max_output_bytes=exiftool_payload.get("max_output_bytes", 65_536),
                boundaries=boundaries,
            )
        except (ExifConfigurationError, TypeError) as exc:
            raise ConfigurationError(str(exc)) from exc
    else:
        raise ConfigurationError("exiftool configuration must be an object")
    xmp_payload = payload.get("xmp", {})
    if not isinstance(xmp_payload, dict):
        raise ConfigurationError("xmp configuration must be an object")
    if set(xmp_payload) - {"max_bytes"}:
        raise ConfigurationError("xmp configuration contains unsupported keys")
    xmp_max_bytes = xmp_payload.get("max_bytes", 262_144)
    if (
        not isinstance(xmp_max_bytes, int)
        or isinstance(xmp_max_bytes, bool)
        or not 64 <= xmp_max_bytes <= 10_000_000
    ):
        raise ConfigurationError("xmp max_bytes must be between 64 and 10000000")
    export_relative_directory = payload.get("lightroom_export_relative_directory")
    if export_relative_directory is not None:
        if not isinstance(export_relative_directory, str):
            raise ConfigurationError(
                "lightroom_export_relative_directory must be a relative path"
            )
        try:
            SessionReader(boundaries).validate_lightroom_export_directory(
                export_relative_directory
            )
        except (PathBoundaryError, TypeError) as exc:
            raise ConfigurationError(str(exc)) from exc

    package_payload = payload.get("review_package", {})
    if not isinstance(package_payload, dict):
        raise ConfigurationError("review_package configuration must be an object")
    if set(package_payload) - {"max_jpg_bytes", "max_package_bytes"}:
        raise ConfigurationError("review_package configuration contains unsupported keys")
    try:
        package_limits = ReviewPackageLimits.create(
            max_jpg_bytes=package_payload.get("max_jpg_bytes", 25_000_000),
            max_package_bytes=package_payload.get(
                "max_package_bytes", 250_000_000
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(str(exc)) from exc

    proxy_payload = payload.get("proxy", {})
    if not isinstance(proxy_payload, dict):
        raise ConfigurationError("proxy configuration must be an object")
    proxy_allowed = {
        "long_edge_px",
        "jpeg_quality",
        "max_source_bytes",
        "max_source_pixels",
    }
    if set(proxy_payload) - proxy_allowed:
        raise ConfigurationError("proxy configuration contains unsupported keys")
    try:
        proxy_settings = ProxySettings.create(**proxy_payload)
    except (ProxyConfigurationError, TypeError) as exc:
        raise ConfigurationError(str(exc)) from exc

    contact_payload = payload.get("contact_sheet", {})
    if not isinstance(contact_payload, dict):
        raise ConfigurationError("contact_sheet configuration must be an object")
    contact_allowed = {
        "columns",
        "cell_width_px",
        "thumbnail_height_px",
        "label_height_px",
        "padding_px",
        "jpeg_quality",
        "max_output_pixels",
        "max_proxy_bytes",
    }
    if set(contact_payload) - contact_allowed:
        raise ConfigurationError(
            "contact_sheet configuration contains unsupported keys"
        )
    try:
        contact_settings = ContactSheetSettings.create(**contact_payload)
    except (ContactSheetError, TypeError) as exc:
        raise ConfigurationError(str(exc)) from exc

    confirmed_package_payload = payload.get("confirmed_review_package", {})
    if not isinstance(confirmed_package_payload, dict):
        raise ConfigurationError(
            "confirmed_review_package configuration must be an object"
        )
    confirmed_package_allowed = {
        "max_proxy_bytes",
        "max_contact_sheet_bytes",
        "max_package_bytes",
    }
    if set(confirmed_package_payload) - confirmed_package_allowed:
        raise ConfigurationError(
            "confirmed_review_package configuration contains unsupported keys"
        )
    try:
        confirmed_package_limits = ConfirmedReviewPackageLimits.create(
            **confirmed_package_payload
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(str(exc)) from exc

    recommendation_payload = payload.get("manual_recommendations", {})
    if not isinstance(recommendation_payload, dict):
        raise ConfigurationError("manual_recommendations configuration must be an object")
    if set(recommendation_payload) - {"database_relative_path"}:
        raise ConfigurationError(
            "manual_recommendations configuration contains unsupported keys"
        )
    try:
        recommendation_settings = ManualRecommendationSettings.create(
            **recommendation_payload
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(str(exc)) from exc
    return Phase0Config(
        boundaries=boundaries,
        exiftool=exiftool,
        xmp_max_bytes=xmp_max_bytes,
        lightroom_export_relative_directory=export_relative_directory,
        review_package_limits=package_limits,
        proxy_settings=proxy_settings,
        contact_sheet_settings=contact_settings,
        confirmed_review_package_limits=confirmed_package_limits,
        manual_recommendation_settings=recommendation_settings,
    )
