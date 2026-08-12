"""Deterministic contact sheets built only from private generated proxies."""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass
from pathlib import PurePosixPath

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from .paths import PathBoundaryError, WorkspaceWriter
from .proxies import ProxyBatchResult, ProxyEntry, _srgb_profile


class ContactSheetError(ValueError):
    """Raised for invalid settings or incomplete proxy inputs."""


@dataclass(frozen=True, slots=True)
class ContactSheetSettings:
    columns: int = 4
    cell_width_px: int = 520
    thumbnail_height_px: int = 360
    label_height_px: int = 58
    padding_px: int = 12
    jpeg_quality: int = 85
    max_output_pixels: int = 100_000_000
    max_proxy_bytes: int = 10_000_000

    @classmethod
    def create(
        cls,
        *,
        columns: int = 4,
        cell_width_px: int = 520,
        thumbnail_height_px: int = 360,
        label_height_px: int = 58,
        padding_px: int = 12,
        jpeg_quality: int = 85,
        max_output_pixels: int = 100_000_000,
        max_proxy_bytes: int = 10_000_000,
    ) -> "ContactSheetSettings":
        ranges = {
            "columns": (columns, 1, 12),
            "cell_width_px": (cell_width_px, 128, 2048),
            "thumbnail_height_px": (thumbnail_height_px, 96, 2048),
            "label_height_px": (label_height_px, 24, 256),
            "padding_px": (padding_px, 0, 128),
            "jpeg_quality": (jpeg_quality, 1, 95),
            "max_output_pixels": (max_output_pixels, 1, 500_000_000),
            "max_proxy_bytes": (max_proxy_bytes, 1, 100_000_000),
        }
        for name, (value, minimum, maximum) in ranges.items():
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not minimum <= value <= maximum
            ):
                raise ContactSheetError(
                    f"{name} must be an integer between {minimum} and {maximum}"
                )
        return cls(
            columns,
            cell_width_px,
            thumbnail_height_px,
            label_height_px,
            padding_px,
            jpeg_quality,
            max_output_pixels,
            max_proxy_bytes,
        )


@dataclass(frozen=True, slots=True)
class ContactSheetResult:
    relative_path: str
    asset_count: int
    width_px: int
    height_px: int
    size_bytes: int
    sha256: str
    status: str
    warnings: tuple[str, ...]


def _ready_entries(proxies: ProxyBatchResult) -> tuple[ProxyEntry, ...]:
    if not proxies.entries:
        raise ContactSheetError("contact sheet requires at least one proxy")
    failures = tuple(
        entry.identifier_name
        for entry in proxies.entries
        if entry.status not in {"generated", "reused"}
        or entry.proxy_relative_path is None
        or entry.sha256 is None
    )
    if failures:
        raise ContactSheetError("contact sheet requires a complete proxy batch")
    return proxies.entries


def _load_proxy(
    writer: WorkspaceWriter,
    entry: ProxyEntry,
    settings: ContactSheetSettings,
) -> Image.Image:
    payload = writer.read_bytes(
        entry.proxy_relative_path,  # type: ignore[arg-type]
        max_bytes=settings.max_proxy_bytes,
    )
    if len(payload) > settings.max_proxy_bytes:
        raise ContactSheetError("proxy exceeds contact sheet input limit")
    if hashlib.sha256(payload).hexdigest() != entry.sha256:
        raise ContactSheetError("proxy hash does not match its immutable result")
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            if opened.format != "JPEG":
                raise ContactSheetError("contact sheet input must be JPEG")
            opened.load()
            return opened.convert("RGB")
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError) as exc:
        raise ContactSheetError("contact sheet proxy is invalid") from exc


def _fit_thumbnail(image: Image.Image, width: int, height: int) -> Image.Image:
    thumbnail = image.copy()
    thumbnail.thumbnail((width, height), Image.Resampling.LANCZOS, reducing_gap=3.0)
    return thumbnail


def generate_contact_sheet(
    writer: WorkspaceWriter,
    *,
    proxies: ProxyBatchResult,
    settings: ContactSheetSettings,
    destination_relative_directory: str = "contact-sheets",
) -> ContactSheetResult:
    """Create one labeled sheet from a complete batch of generated proxies."""

    entries = _ready_entries(proxies)
    destination = PurePosixPath(destination_relative_directory.replace("\\", "/"))
    if (
        not destination_relative_directory
        or destination.is_absolute()
        or destination == PurePosixPath(".")
        or ".." in destination.parts
    ):
        raise ContactSheetError(
            "contact sheet destination must be a non-empty relative directory"
        )
    writer.ensure_directory(destination.as_posix())

    rows = math.ceil(len(entries) / settings.columns)
    cell_height = (
        settings.padding_px
        + settings.thumbnail_height_px
        + settings.padding_px
        + settings.label_height_px
    )
    width = settings.columns * settings.cell_width_px
    height = rows * cell_height
    if width * height > settings.max_output_pixels:
        raise ContactSheetError("contact sheet exceeds configured pixel limit")

    canvas = Image.new("RGB", (width, height), color=(28, 28, 28))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    thumb_width = settings.cell_width_px - 2 * settings.padding_px
    for index, entry in enumerate(entries):
        image = _load_proxy(writer, entry, settings)
        thumbnail = _fit_thumbnail(
            image,
            thumb_width,
            settings.thumbnail_height_px,
        )
        column = index % settings.columns
        row = index // settings.columns
        cell_x = column * settings.cell_width_px
        cell_y = row * cell_height
        image_x = cell_x + (settings.cell_width_px - thumbnail.width) // 2
        image_y = cell_y + settings.padding_px + (
            settings.thumbnail_height_px - thumbnail.height
        ) // 2
        canvas.paste(thumbnail, (image_x, image_y))
        label_y = cell_y + settings.padding_px + settings.thumbnail_height_px + 4
        label = (
            f"{entry.identifier_name}\n"
            f"rating: {entry.rating} | lightroom_export"
        )
        draw.multiline_text(
            (cell_x + settings.padding_px, label_y),
            label,
            font=font,
            fill=(240, 240, 240),
            spacing=2,
        )

    _, srgb = _srgb_profile()
    output = io.BytesIO()
    canvas.save(
        output,
        format="JPEG",
        quality=settings.jpeg_quality,
        optimize=False,
        progressive=False,
        subsampling=2,
        icc_profile=srgb,
    )
    payload = output.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    relative_path = (destination / f"contact-sheet-{digest[:20]}.jpg").as_posix()
    status = "generated"
    try:
        writer.publish_bytes_atomically(relative_path, payload)
    except FileExistsError:
        try:
            existing = writer.read_bytes(relative_path, max_bytes=len(payload))
        except (OSError, PathBoundaryError) as exc:
            raise ContactSheetError("existing contact sheet is unreadable") from exc
        if existing != payload:
            raise ContactSheetError("existing contact sheet conflicts with result")
        status = "reused"
    except (OSError, PathBoundaryError) as exc:
        raise ContactSheetError("contact sheet could not be published") from exc

    return ContactSheetResult(
        relative_path,
        len(entries),
        width,
        height,
        len(payload),
        digest,
        status,
        (
            "contact_sheet_built_from_private_proxies",
            "preview_source_lightroom_export",
            "no_source_metadata_copied",
        ),
    )
