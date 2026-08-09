"""Controlled, read-only EXIF extraction through a local ExifTool executable."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .paths import (
    PathBoundaryError,
    RootBoundaries,
    SessionReader,
    _contains,
    reject_links_or_reparse_points,
)
from .relations import LogicalAsset


REQUESTED_TAGS = (
    "DateTimeOriginal",
    "CreateDate",
    "Make",
    "Model",
    "LensModel",
    "LensID",
    "Lens",
    "ExposureTime",
    "FNumber",
    "ISO",
    "FocalLength",
    "ImageWidth",
    "ExifImageWidth",
    "ImageHeight",
    "ExifImageHeight",
    "Orientation",
)
FIXED_READ_ARGUMENTS = ("-json", "-n", *(f"-{tag}" for tag in REQUESTED_TAGS))
_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)+$")
_METADATA_FIELDS = (
    "captured_at",
    "manufacturer",
    "camera_model",
    "lens",
    "exposure_time_seconds",
    "aperture_f_number",
    "iso",
    "focal_length_mm",
    "width_px",
    "height_px",
    "orientation",
)


class ExifConfigurationError(ValueError):
    """Raised for invalid ExifTool configuration without exposing its path."""


@dataclass(frozen=True, slots=True)
class ExifToolSettings:
    """Validated internal settings; the executable path is never a UI result."""

    executable: Path
    timeout_seconds: float
    max_output_bytes: int

    @classmethod
    def create(
        cls,
        *,
        executable: str | os.PathLike[str],
        timeout_seconds: float,
        max_output_bytes: int,
        boundaries: RootBoundaries,
    ) -> "ExifToolSettings":
        if not isinstance(executable, (str, os.PathLike)) or not os.fspath(executable):
            raise ExifConfigurationError("ExifTool executable path must not be empty")
        raw = Path(executable)
        if not raw.is_absolute():
            raise ExifConfigurationError("ExifTool executable path must be absolute")
        if "=" in os.fspath(raw):
            raise ExifConfigurationError("ExifTool executable path contains an unsupported character")
        try:
            reject_links_or_reparse_points(raw, label="ExifTool executable")
            resolved = raw.resolve(strict=True)
            metadata = raw.stat(follow_symlinks=False)
        except (OSError, RuntimeError, PathBoundaryError) as exc:
            raise ExifConfigurationError("ExifTool executable must be available") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise ExifConfigurationError("ExifTool executable must be a regular file")
        if _contains(boundaries.session_root, resolved):
            raise ExifConfigurationError("ExifTool executable must be outside session_root")
        if _contains(boundaries.workspace_root, resolved):
            raise ExifConfigurationError("ExifTool executable must be outside workspace_root")
        if _contains(boundaries.repository_root, resolved):
            raise ExifConfigurationError("ExifTool executable must be outside repository_root")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not 0.1 <= float(timeout_seconds) <= 120.0
        ):
            raise ExifConfigurationError("ExifTool timeout must be between 0.1 and 120 seconds")
        if (
            not isinstance(max_output_bytes, int)
            or isinstance(max_output_bytes, bool)
            or not 1024 <= max_output_bytes <= 10_000_000
        ):
            raise ExifConfigurationError(
                "ExifTool max output must be between 1024 and 10000000 bytes"
            )
        return cls(resolved, float(timeout_seconds), max_output_bytes)


@dataclass(frozen=True, slots=True)
class ExifToolInfo:
    available: bool
    version: str | None
    status: str


@dataclass(frozen=True, slots=True)
class ExifMetadata:
    captured_at: str | None = None
    manufacturer: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    exposure_time_seconds: float | None = None
    aperture_f_number: float | None = None
    iso: int | None = None
    focal_length_mm: float | None = None
    width_px: int | None = None
    height_px: int | None = None
    orientation: int | None = None


@dataclass(frozen=True, slots=True)
class ExifSourceSelection:
    asset_id: str
    status: str
    relative_path: str | None
    role: str | None


@dataclass(frozen=True, slots=True)
class ExifReadResult:
    asset_id: str
    status: str
    source_relative_path: str | None
    source_role: str | None
    metadata: ExifMetadata | None
    warnings: tuple[str, ...]
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


ProcessRunner = Callable[[tuple[str, ...], float, int], ProcessResult]


def select_exif_source(asset: LogicalAsset) -> ExifSourceSelection:
    """Choose one unambiguous photographic component without filesystem access."""

    if asset.status == "ambiguous":
        return ExifSourceSelection(asset.asset_id, "skipped_ambiguous", None, None)
    raw = asset.components_for("raw")
    images = asset.components_for("image")
    if len(raw) == 1:
        selected = raw[0]
    elif not raw and len(images) == 1:
        selected = images[0]
    else:
        return ExifSourceSelection(
            asset.asset_id,
            "skipped_no_photographic_file",
            None,
            None,
        )
    return ExifSourceSelection(
        asset.asset_id,
        "selected",
        selected.source_entry.relative_path,
        selected.role,
    )


def _drain_limited(stream: object, buffer: bytearray, limit: int) -> None:
    try:
        while True:
            chunk = stream.read(8192)  # type: ignore[attr-defined]
            if not chunk:
                break
            remaining = limit + 1 - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
    finally:
        stream.close()  # type: ignore[attr-defined]


def _default_runner(
    arguments: tuple[str, ...], timeout: float, max_capture_bytes: int
) -> ProcessResult:
    process = subprocess.Popen(
        list(arguments),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise OSError("ExifTool output pipes are unavailable")
    stdout = bytearray()
    stderr = bytearray()
    threads = (
        threading.Thread(
            target=_drain_limited,
            args=(process.stdout, stdout, max_capture_bytes),
            daemon=True,
        ),
        threading.Thread(
            target=_drain_limited,
            args=(process.stderr, stderr, max_capture_bytes),
            daemon=True,
        ),
    )
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise
    finally:
        for thread in threads:
            thread.join()
    return ProcessResult(returncode, bytes(stdout), bytes(stderr))


def _safe_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 256:
        return None
    return normalized


def _safe_float(value: object, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    if not minimum <= normalized <= maximum:
        return None
    return normalized


def _safe_int(value: object, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not minimum <= value <= maximum:
        return None
    return value


def _capture_datetime(payload: dict[str, object]) -> str | None:
    for tag in ("DateTimeOriginal", "CreateDate"):
        value = _safe_string(payload.get(tag))
        if value is None:
            continue
        for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, pattern).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                pass
    return None


def _first_string(payload: dict[str, object], tags: tuple[str, ...]) -> str | None:
    for tag in tags:
        value = _safe_string(payload.get(tag))
        if value is not None:
            return value
    return None


def _first_int(
    payload: dict[str, object], tags: tuple[str, ...], minimum: int, maximum: int
) -> int | None:
    for tag in tags:
        value = _safe_int(payload.get(tag), minimum, maximum)
        if value is not None:
            return value
    return None


def _metadata_from_payload(payload: dict[str, object]) -> tuple[ExifMetadata, tuple[str, ...]]:
    values: dict[str, object | None] = {
        "captured_at": _capture_datetime(payload),
        "manufacturer": _safe_string(payload.get("Make")),
        "camera_model": _safe_string(payload.get("Model")),
        "lens": _first_string(payload, ("LensModel", "LensID", "Lens")),
        "exposure_time_seconds": _safe_float(payload.get("ExposureTime"), 0.000000001, 86400),
        "aperture_f_number": _safe_float(payload.get("FNumber"), 0.1, 128),
        "iso": _safe_int(payload.get("ISO"), 1, 6_553_600),
        "focal_length_mm": _safe_float(payload.get("FocalLength"), 0.1, 10_000),
        "width_px": _first_int(payload, ("ImageWidth", "ExifImageWidth"), 1, 1_000_000),
        "height_px": _first_int(payload, ("ImageHeight", "ExifImageHeight"), 1, 1_000_000),
        "orientation": _safe_int(payload.get("Orientation"), 1, 8),
    }
    warnings: list[str] = []
    for field_name, value in values.items():
        if value is None:
            warnings.append(f"{field_name}_unavailable")
    return ExifMetadata(**values), tuple(warnings)  # type: ignore[arg-type]


class ExifToolAdapter:
    """Trusted adapter that constructs only fixed read-only ExifTool commands."""

    __slots__ = ("_settings", "_runner")

    def __init__(
        self,
        settings: ExifToolSettings,
        *,
        runner: ProcessRunner = _default_runner,
    ) -> None:
        self._settings = settings
        self._runner = runner

    def info(self) -> ExifToolInfo:
        try:
            executable = self._validated_executable()
            result = self._runner(
                (os.fspath(executable), "-ver"),
                self._settings.timeout_seconds,
                128,
            )
        except (ExifConfigurationError, FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return ExifToolInfo(False, None, "unavailable")
        if result.returncode != 0 or len(result.stdout) > 128:
            return ExifToolInfo(False, None, "error")
        try:
            version = result.stdout.decode("ascii").strip()
        except UnicodeDecodeError:
            return ExifToolInfo(False, None, "error")
        if not _VERSION_PATTERN.fullmatch(version):
            return ExifToolInfo(False, None, "error")
        return ExifToolInfo(True, version, "available")

    def read_asset(self, reader: SessionReader, asset: LogicalAsset) -> ExifReadResult:
        selection = select_exif_source(asset)
        if selection.status != "selected":
            return ExifReadResult(
                asset_id=selection.asset_id,
                status=selection.status,
                source_relative_path=None,
                source_role=None,
                metadata=None,
                warnings=(),
                error_code=None,
            )
        try:
            return reader._read_exif_with(self, selection)
        except PathBoundaryError:
            return self._error(selection, "source_unavailable")

    def _validated_executable(self) -> Path:
        configured = self._settings.executable
        try:
            reject_links_or_reparse_points(configured, label="ExifTool executable")
            resolved = configured.resolve(strict=True)
            metadata = configured.stat(follow_symlinks=False)
        except (OSError, RuntimeError, PathBoundaryError) as exc:
            raise ExifConfigurationError("ExifTool executable is unavailable") from exc
        if resolved != configured or not stat.S_ISREG(metadata.st_mode):
            raise ExifConfigurationError("ExifTool executable is unavailable")
        return resolved

    def _read_validated_path(
        self, source: Path, selection: ExifSourceSelection
    ) -> ExifReadResult:
        if "=" in os.fspath(source):
            return self._error(selection, "source_name_not_supported")
        try:
            executable = self._validated_executable()
            arguments = (
                os.fspath(executable),
                *FIXED_READ_ARGUMENTS,
                os.fspath(source),
            )
            result = self._runner(
                arguments,
                self._settings.timeout_seconds,
                self._settings.max_output_bytes,
            )
        except subprocess.TimeoutExpired:
            return self._error(selection, "exiftool_timeout")
        except (ExifConfigurationError, FileNotFoundError, OSError):
            return self._error(selection, "exiftool_unavailable")
        if result.returncode != 0:
            return self._error(selection, "exiftool_exit_error")
        if (
            len(result.stdout) > self._settings.max_output_bytes
            or len(result.stderr) > self._settings.max_output_bytes
        ):
            return self._error(selection, "exiftool_output_too_large")
        try:
            decoded = result.stdout.decode("utf-8")
            parsed = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._error(selection, "exiftool_json_invalid")
        if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
            code = "exiftool_result_empty" if parsed == [] else "exiftool_result_count_invalid"
            return self._error(selection, code)

        metadata, warnings = _metadata_from_payload(parsed[0])
        available_count = sum(
            getattr(metadata, field_name) is not None for field_name in _METADATA_FIELDS
        )
        if available_count == 0:
            status = "unavailable"
        elif available_count == 11:
            status = "complete"
        else:
            status = "partial"
        return ExifReadResult(
            asset_id=selection.asset_id,
            status=status,
            source_relative_path=selection.relative_path,
            source_role=selection.role,
            metadata=metadata,
            warnings=warnings,
            error_code=None,
        )

    @staticmethod
    def _error(selection: ExifSourceSelection, code: str) -> ExifReadResult:
        return ExifReadResult(
            asset_id=selection.asset_id,
            status="error",
            source_relative_path=selection.relative_path,
            source_role=selection.role,
            metadata=None,
            warnings=(),
            error_code=code,
        )
