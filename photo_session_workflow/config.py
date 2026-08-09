"""Load the local Phase 0 path configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .exif import ExifConfigurationError, ExifToolSettings
from .paths import PathBoundaryError, RootBoundaries


class ConfigurationError(ValueError):
    """Raised when the local configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Phase0Config:
    """Validated Phase 0 filesystem configuration."""

    boundaries: RootBoundaries
    exiftool: ExifToolSettings | None = None

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
    return Phase0Config(boundaries, exiftool)
