"""Private, metadata-minimized JPEG proxies from declared Lightroom exports."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import PurePosixPath

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from .lightroom_exports import (
    LightroomExportResolution,
    LightroomExportResolutionResult,
)
from .paths import PathBoundaryError, SessionReader, WorkspaceWriter


class ProxyConfigurationError(ValueError):
    """Raised when proxy limits or rendering settings are invalid."""


@dataclass(frozen=True, slots=True)
class ProxySettings:
    long_edge_px: int = 2048
    jpeg_quality: int = 85
    max_source_bytes: int = 25_000_000
    max_source_pixels: int = 100_000_000

    @classmethod
    def create(
        cls,
        *,
        long_edge_px: int = 2048,
        jpeg_quality: int = 85,
        max_source_bytes: int = 25_000_000,
        max_source_pixels: int = 100_000_000,
    ) -> "ProxySettings":
        values = {
            "long_edge_px": (long_edge_px, 64, 16_384),
            "jpeg_quality": (jpeg_quality, 1, 95),
            "max_source_bytes": (max_source_bytes, 1, 1_000_000_000),
            "max_source_pixels": (max_source_pixels, 1, 500_000_000),
        }
        for name, (value, minimum, maximum) in values.items():
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not minimum <= value <= maximum
            ):
                raise ProxyConfigurationError(
                    f"{name} must be an integer between {minimum} and {maximum}"
                )
        return cls(long_edge_px, jpeg_quality, max_source_bytes, max_source_pixels)


@dataclass(frozen=True, slots=True)
class ProxyEntry:
    asset_id: str
    identifier_name: str
    rating: int
    preview_source: str
    source_relative_path: str
    status: str
    proxy_relative_path: str | None
    width_px: int | None
    height_px: int | None
    size_bytes: int | None
    sha256: str | None
    warnings: tuple[str, ...]
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ProxyBatchResult:
    entries: tuple[ProxyEntry, ...]
    generated_count: int
    reused_count: int
    error_count: int

    @property
    def ready(self) -> bool:
        return bool(self.entries) and self.error_count == 0


def _safe_output_name(asset_id: str, payload: bytes) -> str:
    identity = hashlib.sha256(asset_id.encode("utf-8")).hexdigest()[:16]
    content = hashlib.sha256(payload).hexdigest()[:16]
    return f"proxy-{identity}-{content}.jpg"


def _srgb_profile() -> tuple[ImageCms.ImageCmsProfile, bytes]:
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    return profile, profile.tobytes()


def _render_proxy(
    source: bytes,
    settings: ProxySettings,
) -> tuple[bytes, int, int, tuple[str, ...]]:
    warnings: list[str] = []
    try:
        with Image.open(io.BytesIO(source)) as opened:
            if opened.format != "JPEG":
                raise ValueError("source_not_jpeg")
            width, height = opened.size
            if width < 1 or height < 1 or width * height > settings.max_source_pixels:
                raise ValueError("source_pixel_limit_exceeded")
            orientation = opened.getexif().get(274, 1)
            image = ImageOps.exif_transpose(opened)
            image.load()
            if orientation not in (None, 1):
                warnings.append("exif_orientation_applied")

            srgb, srgb_bytes = _srgb_profile()
            embedded_profile = opened.info.get("icc_profile")
            if embedded_profile:
                try:
                    source_profile = ImageCms.ImageCmsProfile(
                        io.BytesIO(embedded_profile)
                    )
                    image = ImageCms.profileToProfile(
                        image,
                        source_profile,
                        srgb,
                        outputMode="RGB",
                    )
                except (ImageCms.PyCMSError, OSError, TypeError, ValueError) as exc:
                    raise ValueError("invalid_embedded_color_profile") from exc
                warnings.append("embedded_profile_converted_to_srgb")
            else:
                if image.mode not in {"RGB", "L"}:
                    raise ValueError("color_profile_required_for_non_rgb_source")
                image = image.convert("RGB")
                warnings.append("source_profile_missing_assumed_srgb")

            image.thumbnail(
                (settings.long_edge_px, settings.long_edge_px),
                Image.Resampling.LANCZOS,
                reducing_gap=3.0,
            )
            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=settings.jpeg_quality,
                optimize=False,
                progressive=False,
                subsampling=2,
                icc_profile=srgb_bytes,
            )
            rendered = output.getvalue()
    except (Image.DecompressionBombError, UnidentifiedImageError) as exc:
        raise ValueError("invalid_jpeg") from exc
    except (OSError, SyntaxError) as exc:
        raise ValueError("jpeg_decode_error") from exc

    try:
        with Image.open(io.BytesIO(rendered)) as verification:
            verification.load()
            if verification.format != "JPEG" or verification.mode != "RGB":
                raise ValueError("proxy_validation_failed")
            if verification.getexif():
                raise ValueError("proxy_contains_exif")
            output_width, output_height = verification.size
            if max(output_width, output_height) > settings.long_edge_px:
                raise ValueError("proxy_dimension_limit_exceeded")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("proxy_validation_failed") from exc

    warnings.append("source_metadata_removed_by_reencoding")
    return rendered, output_width, output_height, tuple(warnings)


def _error_entry(
    item: LightroomExportResolution,
    error_code: str,
) -> ProxyEntry:
    source = item.export.relative_path if item.export is not None else ""
    return ProxyEntry(
        item.asset_id,
        item.identifier_name,
        item.rating,
        "lightroom_export",
        source,
        "error",
        None,
        None,
        None,
        None,
        None,
        item.warnings,
        error_code,
    )


def generate_proxies(
    reader: SessionReader,
    writer: WorkspaceWriter,
    *,
    export_relative_directory: str,
    resolutions: LightroomExportResolutionResult,
    settings: ProxySettings,
    destination_relative_directory: str = "proxies",
) -> ProxyBatchResult:
    """Generate deterministic proxies for exactly the selected export resolutions."""

    destination = PurePosixPath(destination_relative_directory.replace("\\", "/"))
    if (
        not destination_relative_directory
        or destination.is_absolute()
        or destination == PurePosixPath(".")
        or ".." in destination.parts
    ):
        raise ProxyConfigurationError(
            "proxy destination must be a non-empty relative directory"
        )
    writer.ensure_directory(destination.as_posix())

    entries: list[ProxyEntry] = []
    for item in resolutions.resolutions:
        if item.status != "resolved" or item.export is None:
            entries.append(_error_entry(item, f"lightroom_export_{item.status}"))
            continue
        try:
            source = reader.read_lightroom_export(
                export_relative_directory,
                item.export.relative_path,
                max_bytes=settings.max_source_bytes,
            )
        except (OSError, PathBoundaryError):
            entries.append(_error_entry(item, "source_read_error"))
            continue
        if len(source) > settings.max_source_bytes:
            entries.append(_error_entry(item, "source_too_large"))
            continue
        try:
            rendered, width, height, render_warnings = _render_proxy(source, settings)
        except ValueError as exc:
            code = str(exc)
            allowed = {
                "source_not_jpeg",
                "source_pixel_limit_exceeded",
                "invalid_embedded_color_profile",
                "color_profile_required_for_non_rgb_source",
                "invalid_jpeg",
                "jpeg_decode_error",
                "proxy_validation_failed",
                "proxy_contains_exif",
                "proxy_dimension_limit_exceeded",
            }
            entries.append(
                _error_entry(item, code if code in allowed else "proxy_generation_error")
            )
            continue

        relative_path = (
            destination / _safe_output_name(item.asset_id, rendered)
        ).as_posix()
        digest = hashlib.sha256(rendered).hexdigest()
        status = "generated"
        try:
            writer.publish_bytes_atomically(relative_path, rendered)
        except FileExistsError:
            try:
                existing = writer.read_bytes(
                    relative_path,
                    max_bytes=len(rendered),
                )
            except (OSError, PathBoundaryError):
                entries.append(_error_entry(item, "existing_proxy_unreadable"))
                continue
            if existing != rendered:
                entries.append(_error_entry(item, "existing_proxy_conflict"))
                continue
            status = "reused"
        except (OSError, PathBoundaryError):
            entries.append(_error_entry(item, "proxy_publication_error"))
            continue
        source_warnings = tuple(
            warning
            for warning in item.warnings
            if warning != "embedded_metadata_policy_depends_on_lightroom_export"
        )
        entries.append(
            ProxyEntry(
                item.asset_id,
                item.identifier_name,
                item.rating,
                "lightroom_export",
                item.export.relative_path,
                status,
                relative_path,
                width,
                height,
                len(rendered),
                digest,
                tuple(dict.fromkeys((*source_warnings, *render_warnings))),
                None,
            )
        )

    result = tuple(entries)
    return ProxyBatchResult(
        result,
        sum(item.status == "generated" for item in result),
        sum(item.status == "reused" for item in result),
        sum(item.status == "error" for item in result),
    )
