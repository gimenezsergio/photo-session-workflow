"""Orchestration for rating read, filtering, and in-memory manifest creation."""

from __future__ import annotations

from dataclasses import dataclass

from .paths import SessionReader
from .rating_filter import RatingFilter, RatingFilterResult, filter_assets_by_rating
from .relations import RelationResult
from .selection_manifest import (
    PreliminarySelectionManifest,
    build_preliminary_manifest,
)
from .xmp_rating import RatingReadResult, XmpRatingReader, read_relation_ratings


@dataclass(frozen=True, slots=True)
class RatedSelectionWorkflowResult:
    ratings: tuple[RatingReadResult, ...]
    selection: RatingFilterResult
    manifest: PreliminarySelectionManifest
    manifest_json: str


def build_rated_selection(
    reader: SessionReader,
    relations: RelationResult,
    *,
    xmp_reader: XmpRatingReader,
    rating_filter: RatingFilter,
) -> RatedSelectionWorkflowResult:
    ratings = read_relation_ratings(reader, relations, xmp_reader)
    selection = filter_assets_by_rating(relations, ratings, rating_filter)
    manifest = build_preliminary_manifest(selection)
    return RatedSelectionWorkflowResult(
        ratings,
        selection,
        manifest,
        manifest.to_json(),
    )
