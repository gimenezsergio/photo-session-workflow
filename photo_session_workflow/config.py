"""Load the local Phase 0 path configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .exif import ExifConfigurationError, ExifToolSettings
from .paths import PathBoundaryError, RootBoundaries, SessionReader
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
    return Phase0Config(
        boundaries,
        exiftool,
        xmp_max_bytes,
        export_relative_directory,
        package_limits,
    )
