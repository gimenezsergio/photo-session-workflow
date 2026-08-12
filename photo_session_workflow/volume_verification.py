"""Measured synthetic/authorized Phase 0 workflow verification up to 200 photos."""

from __future__ import annotations

import os
import math
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from .confirmed_review_package import (
    ConfirmedReviewPackageLimits,
    generate_confirmed_review_package,
)
from .contact_sheet import ContactSheetSettings, generate_contact_sheet
from .integrity import (
    SourceIntegrityReport,
    capture_source_integrity,
    compare_source_integrity,
    require_unchanged_sources,
)
from .lightroom_exports import resolve_lightroom_exports
from .paths import SessionReader, WorkspaceWriter
from .proxies import ProxySettings, generate_proxies
from .rated_selection import build_rated_selection
from .rating_filter import RatingFilter
from .relations import relate_inventory
from .selection_confirmation import confirm_selection, create_selection_draft
from .xmp_rating import XmpRatingReader


class VolumeVerificationError(ValueError):
    """Raised when the measured Phase 0 flow cannot satisfy its invariants."""


@dataclass(frozen=True, slots=True)
class StageMeasurement:
    stage: str
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class VolumeVerificationReport:
    completed: bool
    target_photo_count: int
    inventoried_photo_count: int
    sidecar_count: int
    auxiliary_count: int
    logical_asset_count: int
    rated_selection_count: int
    proxy_count: int
    overview_contact_sheet_count: int
    confirmed_selection_count: int
    package_selected_count: int
    source_count: int
    source_bytes: int
    workspace_artifact_count_before: int
    workspace_artifact_count_after: int
    workspace_bytes_before: int
    workspace_bytes_after: int
    workspace_added_bytes: int
    package_relative_path: str
    package_size_bytes: int
    package_sha256: str
    source_integrity: SourceIntegrityReport
    stages: tuple[StageMeasurement, ...]
    total_elapsed_seconds: float
    warnings: tuple[str, ...]


_T = TypeVar("_T")


def _measure(
    stages: list[StageMeasurement],
    stage: str,
    operation: Callable[[], _T],
    clock: Callable[[], float],
) -> _T:
    start = clock()
    result = operation()
    end = clock()
    if (
        not isinstance(start, (int, float))
        or isinstance(start, bool)
        or not isinstance(end, (int, float))
        or isinstance(end, bool)
        or not math.isfinite(float(start))
        or not math.isfinite(float(end))
        or end < start
    ):
        raise VolumeVerificationError("performance clock returned invalid values")
    stages.append(StageMeasurement(stage, float(end - start)))
    return result


def _workspace_usage(root: Path) -> tuple[int, int]:
    pending = [root]
    files = 0
    total = 0
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                children = tuple(iterator)
        except OSError as exc:
            raise VolumeVerificationError("workspace usage could not be measured") from exc
        for child in children:
            try:
                metadata = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise VolumeVerificationError(
                    "workspace artifact metadata is unavailable"
                ) from exc
            attributes = getattr(metadata, "st_file_attributes", 0)
            if stat.S_ISLNK(metadata.st_mode) or bool(
                attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise VolumeVerificationError(
                    "workspace usage encountered a link or reparse point"
                )
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(Path(child.path))
            elif stat.S_ISREG(metadata.st_mode):
                files += 1
                total += metadata.st_size
            else:
                raise VolumeVerificationError(
                    "workspace usage encountered an unsupported filesystem type"
                )
    return files, total


def run_volume_verification(
    reader: SessionReader,
    writer: WorkspaceWriter,
    *,
    export_relative_directory: str,
    confirmed_asset_ids: tuple[str, ...],
    proxy_settings: ProxySettings,
    contact_sheet_settings: ContactSheetSettings,
    package_limits: ConfirmedReviewPackageLimits,
    package_relative_path: str = "phase-0-volume-review.zip",
    target_photo_count: int = 200,
    minimum_rating: int = 1,
    xmp_max_bytes: int = 262_144,
    explicit_confirmation: bool,
    clock: Callable[[], float] = time.perf_counter,
) -> VolumeVerificationReport:
    """Run the existing Phase 0 stages and report measured objective evidence."""

    if not isinstance(reader, SessionReader) or not isinstance(writer, WorkspaceWriter):
        raise VolumeVerificationError("filesystem capabilities are invalid")
    if not callable(clock):
        raise VolumeVerificationError("performance clock must be callable")
    if (
        not isinstance(target_photo_count, int)
        or isinstance(target_photo_count, bool)
        or target_photo_count < 1
        or target_photo_count > 200
    ):
        raise VolumeVerificationError("target_photo_count must be between 1 and 200")
    if (
        not isinstance(confirmed_asset_ids, tuple)
        or not confirmed_asset_ids
        or any(not isinstance(value, str) or not value for value in confirmed_asset_ids)
        or len(set(confirmed_asset_ids)) != len(confirmed_asset_ids)
    ):
        raise VolumeVerificationError("confirmed_asset_ids must be a unique non-empty tuple")

    stages: list[StageMeasurement] = []
    total_start = clock()
    if (
        not isinstance(total_start, (int, float))
        or isinstance(total_start, bool)
        or not math.isfinite(float(total_start))
    ):
        raise VolumeVerificationError("performance clock returned invalid values")
    artifacts_before, bytes_before = _measure(
        stages,
        "workspace_usage_before",
        lambda: _workspace_usage(writer.root),
        clock,
    )
    inventory = _measure(
        stages,
        "inventory",
        lambda: reader.inventory(
            recursive=False,
            target_photo_count=target_photo_count,
        ),
        clock,
    )
    relations = _measure(
        stages,
        "relations",
        lambda: relate_inventory(inventory),
        clock,
    )
    rated = _measure(
        stages,
        "rating_selection",
        lambda: build_rated_selection(
            reader,
            relations,
            xmp_reader=XmpRatingReader(max_bytes=xmp_max_bytes),
            rating_filter=RatingFilter.create(minimum_rating=minimum_rating),
        ),
        clock,
    )

    def inventory_and_resolve_exports():
        export_inventory = reader.inventory_lightroom_exports(
            export_relative_directory
        )
        resolutions = resolve_lightroom_exports(rated.selection, export_inventory)
        return export_inventory, resolutions

    export_inventory, resolutions = _measure(
        stages,
        "lightroom_exports",
        inventory_and_resolve_exports,
        clock,
    )
    before_integrity = _measure(
        stages,
        "source_integrity_before",
        lambda: capture_source_integrity(
            reader,
            inventory,
            lightroom_exports=export_inventory,
        ),
        clock,
    )
    proxies = _measure(
        stages,
        "proxies",
        lambda: generate_proxies(
            reader,
            writer,
            export_relative_directory=export_relative_directory,
            resolutions=resolutions,
            settings=proxy_settings,
        ),
        clock,
    )
    overview_sheet = _measure(
        stages,
        "overview_contact_sheet",
        lambda: generate_contact_sheet(
            writer,
            proxies=proxies,
            settings=contact_sheet_settings,
        ),
        clock,
    )

    def confirmation_stage():
        draft = create_selection_draft(
            proxies,
            initially_selected_asset_ids=confirmed_asset_ids,
        )
        return confirm_selection(
            draft,
            explicit_confirmation=explicit_confirmation,
        )

    confirmation = _measure(
        stages,
        "selection_confirmation",
        confirmation_stage,
        clock,
    )
    package = _measure(
        stages,
        "confirmed_review_package",
        lambda: generate_confirmed_review_package(
            writer,
            proxies=proxies,
            confirmation=confirmation,
            contact_sheet_settings=contact_sheet_settings,
            destination_relative_path=package_relative_path,
            limits=package_limits,
        ),
        clock,
    )

    def after_snapshot():
        after_inventory = reader.inventory(
            recursive=False,
            target_photo_count=target_photo_count,
        )
        after_exports = reader.inventory_lightroom_exports(
            export_relative_directory
        )
        return capture_source_integrity(
            reader,
            after_inventory,
            lightroom_exports=after_exports,
        )

    after_integrity = _measure(
        stages,
        "source_integrity_after",
        after_snapshot,
        clock,
    )
    integrity = compare_source_integrity(before_integrity, after_integrity)
    require_unchanged_sources(integrity)
    artifacts_after, bytes_after = _measure(
        stages,
        "workspace_usage_after",
        lambda: _workspace_usage(writer.root),
        clock,
    )
    total_end = clock()
    if (
        not isinstance(total_end, (int, float))
        or isinstance(total_end, bool)
        or not math.isfinite(float(total_end))
        or total_end < total_start
    ):
        raise VolumeVerificationError("performance clock returned invalid values")

    failures: list[str] = []
    if inventory.photo_count > target_photo_count:
        failures.append("photo_count_exceeds_target")
    if not resolutions.ready:
        failures.append("lightroom_exports_incomplete")
    if not proxies.ready:
        failures.append("proxy_batch_incomplete")
    if proxies.generated_count + proxies.reused_count >= inventory.photo_count:
        failures.append("all_session_photos_prepared_individually")
    if overview_sheet.asset_count != len(rated.selection.selected):
        failures.append("overview_contact_sheet_count_mismatch")
    if package.manifest.selected_count != confirmation.selected_count:
        failures.append("package_selection_count_mismatch")
    if package.manifest.selected_count >= inventory.photo_count:
        failures.append("package_not_reduced")
    if artifacts_after < artifacts_before or bytes_after < bytes_before:
        failures.append("workspace_artifacts_were_removed")
    if failures:
        raise VolumeVerificationError(
            "volume objective invariants failed: " + ",".join(failures)
        )

    warnings = tuple(
        dict.fromkeys(
            (
                *inventory.warnings,
                *confirmation.warnings,
                "performance_results_depend_on_local_hardware",
                "synthetic_results_do_not_validate_real_nef_decoding",
            )
        )
    )
    return VolumeVerificationReport(
        True,
        target_photo_count,
        inventory.photo_count,
        inventory.sidecar_count,
        inventory.auxiliary_count,
        len(relations.assets),
        len(rated.selection.selected),
        proxies.generated_count + proxies.reused_count,
        overview_sheet.asset_count,
        confirmation.selected_count,
        package.manifest.selected_count,
        before_integrity.source_count,
        sum(entry.size_bytes for entry in before_integrity.entries),
        artifacts_before,
        artifacts_after,
        bytes_before,
        bytes_after,
        bytes_after - bytes_before,
        package.relative_path,
        package.size_bytes,
        package.sha256,
        integrity,
        tuple(stages),
        float(total_end - total_start),
        warnings,
    )
