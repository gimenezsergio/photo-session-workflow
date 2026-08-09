"""Deterministic in-memory preliminary manifest for a rated selection."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .rating_filter import RatingFilterResult


@dataclass(frozen=True, slots=True)
class ManifestFilter:
    minimum_rating: int | None
    exact_ratings: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PreliminaryManifestAsset:
    asset_id: str
    rating: int
    identifier_name: str
    xmp_relative_path: str | None
    jpg_candidate_relative_path: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreliminarySelectionManifest:
    schema_version: str
    applied_filter: ManifestFilter
    total_evaluated: int
    selected_count: int
    assets: tuple[PreliminaryManifestAsset, ...]

    def to_json(self) -> str:
        """Serialize deterministically without timestamps or filesystem writes."""

        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def _unique_warnings(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def build_preliminary_manifest(
    selection: RatingFilterResult,
) -> PreliminarySelectionManifest:
    assets: list[PreliminaryManifestAsset] = []
    for selected in selection.selected:
        asset = selected.asset
        rating_result = selected.rating_result
        images = asset.components_for("image")
        if len(images) == 1:
            jpg_candidate = images[0].source_entry.relative_path
            preview_warnings = ("jpg_candidate_unverified",)
        elif not images:
            jpg_candidate = None
            preview_warnings = ("jpg_candidate_missing",)
        else:
            jpg_candidate = None
            preview_warnings = ("jpg_candidate_ambiguous",)
        assets.append(
            PreliminaryManifestAsset(
                asset_id=asset.asset_id,
                rating=rating_result.rating,  # type: ignore[arg-type]
                identifier_name=asset.original_base_names[0],
                xmp_relative_path=rating_result.xmp_relative_path,
                jpg_candidate_relative_path=jpg_candidate,
                warnings=_unique_warnings(
                    (*rating_result.warnings, *preview_warnings)
                ),
            )
        )
    applied = selection.applied_filter
    return PreliminarySelectionManifest(
        schema_version="0.1",
        applied_filter=ManifestFilter(
            applied.minimum_rating,
            applied.exact_ratings,
        ),
        total_evaluated=selection.total_evaluated,
        selected_count=len(assets),
        assets=tuple(assets),
    )
