"""Pure deterministic filtering of logical assets by XMP rating."""

from __future__ import annotations

from dataclasses import dataclass

from .relations import LogicalAsset, RelationResult
from .xmp_rating import RatingReadResult


@dataclass(frozen=True, slots=True)
class RatingFilter:
    minimum_rating: int | None
    exact_ratings: tuple[int, ...]

    @classmethod
    def create(
        cls,
        *,
        minimum_rating: int | None = None,
        exact_ratings: set[int] | frozenset[int] | tuple[int, ...] | None = None,
    ) -> "RatingFilter":
        if minimum_rating is not None and exact_ratings is not None:
            raise ValueError("minimum_rating and exact_ratings are mutually exclusive")
        if exact_ratings is not None:
            if not isinstance(exact_ratings, (set, frozenset, tuple)):
                raise TypeError("exact_ratings must be a set or tuple")
            if not exact_ratings or any(
                isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5
                for value in exact_ratings
            ):
                raise ValueError("exact_ratings must contain values from 1 to 5")
            return cls(None, tuple(sorted(set(exact_ratings))))
        if (
            isinstance(minimum_rating, bool)
            or not isinstance(minimum_rating, int)
            or not 1 <= minimum_rating <= 5
        ):
            raise ValueError("minimum_rating must be between 1 and 5")
        return cls(minimum_rating, ())


@dataclass(frozen=True, slots=True)
class SelectedRatedAsset:
    asset: LogicalAsset
    rating_result: RatingReadResult


@dataclass(frozen=True, slots=True)
class ExcludedRatedAsset:
    asset: LogicalAsset
    rating_result: RatingReadResult
    reason: str


@dataclass(frozen=True, slots=True)
class RatingFilterResult:
    applied_filter: RatingFilter
    total_evaluated: int
    selected: tuple[SelectedRatedAsset, ...]
    excluded: tuple[ExcludedRatedAsset, ...]


def filter_assets_by_rating(
    relations: RelationResult,
    ratings: tuple[RatingReadResult, ...],
    applied_filter: RatingFilter,
) -> RatingFilterResult:
    """Filter without modifying ratings or asset order."""

    rating_by_asset = {result.asset_id: result for result in ratings}
    if len(rating_by_asset) != len(ratings):
        raise ValueError("rating results contain duplicate asset identifiers")
    known_asset_ids = {asset.asset_id for asset in relations.assets}
    if unknown_asset_ids := set(rating_by_asset).difference(known_asset_ids):
        raise ValueError("rating results contain unknown asset identifiers")
    selected: list[SelectedRatedAsset] = []
    excluded: list[ExcludedRatedAsset] = []
    for asset in relations.assets:
        rating_result = rating_by_asset.get(asset.asset_id)
        if rating_result is None:
            rating_result = RatingReadResult(
                asset.asset_id, None, "error", None, (), "rating_result_missing"
            )
        reason: str | None = None
        if asset.status == "ambiguous":
            reason = "asset_ambiguous"
        elif not (asset.components_for("raw") or asset.components_for("image")):
            reason = "photographic_file_missing"
        elif rating_result.status != "rated" or rating_result.rating is None:
            reason = f"status_{rating_result.status}"
        elif applied_filter.exact_ratings:
            if rating_result.rating not in applied_filter.exact_ratings:
                reason = "rating_not_in_exact_set"
        elif rating_result.rating < applied_filter.minimum_rating:  # type: ignore[operator]
            reason = "rating_below_minimum"
        if reason is None:
            selected.append(SelectedRatedAsset(asset, rating_result))
        else:
            excluded.append(ExcludedRatedAsset(asset, rating_result, reason))
    return RatingFilterResult(
        applied_filter,
        len(relations.assets),
        tuple(selected),
        tuple(excluded),
    )
