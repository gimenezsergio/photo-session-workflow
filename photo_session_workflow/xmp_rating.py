"""Read only Adobe XMP ratings from unambiguous sidecars."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import BinaryIO

from .paths import PathBoundaryError, SessionReader
from .relations import LogicalAsset, RelationResult


XMP_NAMESPACE = "http://ns.adobe.com/xap/1.0/"
RDF_NAMESPACE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RATING_NAME = f"{{{XMP_NAMESPACE}}}Rating"
DESCRIPTION_NAME = f"{{{RDF_NAMESPACE}}}Description"
ALLOWED_RATING_TEXT = {"-1", "0", "1", "2", "3", "4", "5"}


@dataclass(frozen=True, slots=True)
class RatingSourceSelection:
    asset_id: str
    status: str
    relative_path: str | None


@dataclass(frozen=True, slots=True)
class RatingReadResult:
    asset_id: str
    rating: int | None
    status: str
    xmp_relative_path: str | None
    warnings: tuple[str, ...]
    error_code: str | None


def select_rating_sidecar(asset: LogicalAsset) -> RatingSourceSelection:
    sidecars = asset.components_for("sidecar")
    if len(sidecars) > 1:
        return RatingSourceSelection(asset.asset_id, "skipped_ambiguous_sidecar", None)
    if asset.status == "ambiguous":
        return RatingSourceSelection(asset.asset_id, "skipped_ambiguous_asset", None)
    if not (asset.components_for("raw") or asset.components_for("image")):
        return RatingSourceSelection(
            asset.asset_id, "skipped_no_photographic_file", None
        )
    if not sidecars:
        return RatingSourceSelection(asset.asset_id, "missing", None)
    return RatingSourceSelection(
        asset.asset_id,
        "selected",
        sidecars[0].source_entry.relative_path,
    )


def _rating_values(root: ET.Element) -> list[str]:
    values: list[str] = []
    for description in root.iter(DESCRIPTION_NAME):
        if RATING_NAME in description.attrib:
            values.append(description.attrib[RATING_NAME].strip())
    for element in root.iter(RATING_NAME):
        values.append((element.text or "").strip())
    return values


def _interpret_rating(
    selection: RatingSourceSelection, root: ET.Element
) -> RatingReadResult:
    values = _rating_values(root)
    common_warnings = ("xmp_last_saved_state_only",)
    if not values:
        return RatingReadResult(
            selection.asset_id,
            None,
            "missing",
            selection.relative_path,
            ("rating_missing", *common_warnings),
            None,
        )
    if any(value not in ALLOWED_RATING_TEXT for value in values):
        return RatingReadResult(
            selection.asset_id,
            None,
            "invalid",
            selection.relative_path,
            ("rating_value_invalid", *common_warnings),
            None,
        )
    unique_values = set(values)
    if len(unique_values) != 1:
        return RatingReadResult(
            selection.asset_id,
            None,
            "invalid",
            selection.relative_path,
            ("rating_values_conflict", *common_warnings),
            None,
        )
    rating = int(values[0])
    duplicate_warning = ("duplicate_rating_values",) if len(values) > 1 else ()
    if rating == -1:
        status = "rejected"
    elif rating == 0:
        status = "unrated"
    else:
        status = "rated"
    return RatingReadResult(
        selection.asset_id,
        rating,
        status,
        selection.relative_path,
        (*duplicate_warning, *common_warnings),
        None,
    )


class XmpRatingReader:
    """Bounded XMP reader that exposes only normalized rating results."""

    __slots__ = ("max_bytes",)

    def __init__(self, *, max_bytes: int = 262_144) -> None:
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or not 64 <= max_bytes <= 10_000_000
        ):
            raise ValueError("XMP max_bytes must be between 64 and 10000000")
        self.max_bytes = max_bytes

    def read_asset(
        self, reader: SessionReader, asset: LogicalAsset
    ) -> RatingReadResult:
        selection = select_rating_sidecar(asset)
        if selection.status == "missing":
            return RatingReadResult(
                selection.asset_id,
                None,
                "missing",
                None,
                ("xmp_missing",),
                None,
            )
        if selection.status != "selected":
            return RatingReadResult(
                selection.asset_id,
                None,
                selection.status,
                None,
                (),
                None,
            )
        try:
            return reader._read_xmp_rating_with(self, selection)
        except PathBoundaryError:
            return self._error(selection, "xmp_unavailable")
        except OSError:
            return self._error(selection, "xmp_read_error")

    def _read_validated_stream(
        self, stream: BinaryIO, selection: RatingSourceSelection
    ) -> RatingReadResult:
        payload = stream.read(self.max_bytes + 1)
        if len(payload) > self.max_bytes:
            return self._error(selection, "xmp_too_large")
        markup_probe = payload.upper().replace(b"\x00", b"")
        if b"<!DOCTYPE" in markup_probe:
            return self._error(selection, "xmp_doctype_forbidden")
        if b"<!ENTITY" in markup_probe:
            return self._error(selection, "xmp_entity_forbidden")
        try:
            root = ET.fromstring(payload)
        except ET.ParseError:
            return self._error(selection, "xmp_xml_invalid")
        return _interpret_rating(selection, root)

    @staticmethod
    def _error(selection: RatingSourceSelection, code: str) -> RatingReadResult:
        return RatingReadResult(
            selection.asset_id,
            None,
            "error",
            selection.relative_path,
            (),
            code,
        )


def read_relation_ratings(
    reader: SessionReader,
    relations: RelationResult,
    xmp_reader: XmpRatingReader,
) -> tuple[RatingReadResult, ...]:
    """Read every asset independently while preserving relation order."""

    return tuple(xmp_reader.read_asset(reader, asset) for asset in relations.assets)
