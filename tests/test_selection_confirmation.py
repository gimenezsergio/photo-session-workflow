from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

from photo_session_workflow.lightroom_exports import (
    LightroomExportEntry,
    LightroomExportResolution,
    LightroomExportResolutionResult,
)
from photo_session_workflow.paths import RootBoundaries, SessionReader, WorkspaceWriter
from photo_session_workflow.proxies import ProxyBatchResult, ProxyEntry
from photo_session_workflow.review_package import (
    ReviewPackageConfirmationError,
    ReviewPackageLimits,
    generate_review_package,
)
from photo_session_workflow.selection_confirmation import (
    SelectionConfirmationError,
    confirm_selection,
    create_selection_draft,
    update_selection,
    validate_confirmed_selection,
)


class SelectionConfirmationTests(unittest.TestCase):
    def _entry(
        self,
        index: int,
        *,
        status: str = "generated",
        asset_id: str | None = None,
        proxy_path: str | None = None,
        source_path: str | None = None,
    ) -> ProxyEntry:
        identifier = f"photo-{index:03d}"
        identity = asset_id or f"asset:.:{identifier}"
        return ProxyEntry(
            identity,
            identifier,
            5,
            "lightroom_export",
            source_path or f"export-app/{identifier}.jpg",
            hashlib.sha256(f"source:{identity}".encode()).hexdigest(),
            status,
            proxy_path or f"proxies/{identifier}.jpg",
            100,
            80,
            1000,
            hashlib.sha256(identity.encode()).hexdigest(),
            (),
            None if status in {"generated", "reused"} else "synthetic_error",
        )

    def _batch(self, count: int) -> ProxyBatchResult:
        entries = tuple(self._entry(index) for index in range(count))
        return ProxyBatchResult(entries, count, 0, 0)

    def test_draft_starts_with_all_candidates_in_stable_order(self) -> None:
        draft = create_selection_draft(self._batch(5))
        self.assertEqual(draft.candidate_count, 5)
        self.assertEqual(draft.selected_count, 5)
        self.assertEqual(
            draft.selected_asset_ids,
            tuple(f"asset:.:photo-{index:03d}" for index in range(5)),
        )
        self.assertEqual(draft.volume_status, "below_recommended")
        self.assertEqual(draft.warnings, ("selection_below_recommended_range",))

    def test_five_image_session_can_be_explicitly_confirmed(self) -> None:
        draft = create_selection_draft(self._batch(5))
        confirmed = confirm_selection(draft, explicit_confirmation=True)
        self.assertEqual(confirmed.status, "confirmed")
        self.assertEqual(confirmed.selected_count, 5)
        self.assertEqual(confirmed.volume_status, "below_recommended")
        self.assertEqual(len(confirmed.confirmation_digest), 64)

    def test_remove_and_readd_return_new_drafts_without_mutation(self) -> None:
        original = create_selection_draft(self._batch(3))
        removed = update_selection(
            original,
            remove_asset_ids=("asset:.:photo-001",),
        )
        restored = update_selection(
            removed,
            add_asset_ids=("asset:.:photo-001",),
        )
        self.assertEqual(original.selected_count, 3)
        self.assertEqual(removed.selected_count, 2)
        self.assertEqual(restored.selected_asset_ids, original.selected_asset_ids)
        with self.assertRaises(FrozenInstanceError):
            original.selected_count = 1  # type: ignore[misc]

    def test_initial_subset_is_reordered_to_candidate_order(self) -> None:
        draft = create_selection_draft(
            self._batch(4),
            initially_selected_asset_ids=(
                "asset:.:photo-003",
                "asset:.:photo-001",
            ),
        )
        self.assertEqual(
            draft.selected_asset_ids,
            ("asset:.:photo-001", "asset:.:photo-003"),
        )

    def test_recommended_range_is_informative_not_blocking(self) -> None:
        below = confirm_selection(
            create_selection_draft(self._batch(5)), explicit_confirmation=True
        )
        within = confirm_selection(
            create_selection_draft(self._batch(12)), explicit_confirmation=True
        )
        above = confirm_selection(
            create_selection_draft(self._batch(31)), explicit_confirmation=True
        )
        self.assertEqual(below.volume_status, "below_recommended")
        self.assertEqual(within.volume_status, "within_recommended")
        self.assertEqual(above.volume_status, "above_recommended")

    def test_false_or_missing_intent_and_empty_selection_are_rejected(self) -> None:
        draft = create_selection_draft(self._batch(2))
        with self.assertRaisesRegex(SelectionConfirmationError, "explicit"):
            confirm_selection(draft, explicit_confirmation=False)
        empty = update_selection(
            draft,
            remove_asset_ids=draft.selected_asset_ids,
        )
        self.assertEqual(empty.selected_count, 0)
        with self.assertRaisesRegex(SelectionConfirmationError, "at least one"):
            confirm_selection(empty, explicit_confirmation=True)

    def test_unknown_duplicate_and_conflicting_updates_are_rejected(self) -> None:
        draft = create_selection_draft(self._batch(2))
        with self.assertRaisesRegex(SelectionConfirmationError, "unknown"):
            update_selection(draft, add_asset_ids=("asset:unknown",))
        with self.assertRaisesRegex(SelectionConfirmationError, "duplicate"):
            update_selection(
                draft,
                remove_asset_ids=("asset:.:photo-000", "asset:.:photo-000"),
            )
        with self.assertRaisesRegex(SelectionConfirmationError, "same asset"):
            update_selection(
                draft,
                add_asset_ids=("asset:.:photo-000",),
                remove_asset_ids=("asset:.:photo-000",),
            )

    def test_incomplete_duplicate_or_unsafe_candidates_are_rejected(self) -> None:
        incomplete = ProxyBatchResult((self._entry(0, status="error"),), 0, 0, 1)
        with self.assertRaisesRegex(SelectionConfirmationError, "complete"):
            create_selection_draft(incomplete)
        duplicate_ids = ProxyBatchResult(
            (
                self._entry(0, asset_id="duplicate"),
                self._entry(1, asset_id="duplicate"),
            ),
            2,
            0,
            0,
        )
        with self.assertRaisesRegex(SelectionConfirmationError, "duplicate asset"):
            create_selection_draft(duplicate_ids)
        duplicate_paths = ProxyBatchResult(
            (
                self._entry(0, proxy_path="proxies/same.jpg"),
                self._entry(1, proxy_path="proxies/SAME.jpg"),
            ),
            2,
            0,
            0,
        )
        with self.assertRaisesRegex(SelectionConfirmationError, "duplicate proxy"):
            create_selection_draft(duplicate_paths)
        unsafe = ProxyBatchResult(
            (self._entry(0, proxy_path="../private.jpg"),),
            1,
            0,
            0,
        )
        with self.assertRaisesRegex(SelectionConfirmationError, "proxy path"):
            create_selection_draft(unsafe)

    def test_confirmation_is_deterministic_and_contains_no_absolute_paths(self) -> None:
        first = confirm_selection(
            create_selection_draft(self._batch(3)), explicit_confirmation=True
        )
        second = confirm_selection(
            create_selection_draft(self._batch(3)), explicit_confirmation=True
        )
        self.assertEqual(first, second)
        self.assertEqual(first.confirmation_digest, second.confirmation_digest)
        serialized = repr(first)
        self.assertNotIn("C:\\", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertIs(validate_confirmed_selection(first), first)

    def test_invalid_recommended_range_is_rejected(self) -> None:
        for minimum, maximum in ((0, 30), (31, 30), (True, 30)):
            with self.subTest(minimum=minimum, maximum=maximum):
                with self.assertRaisesRegex(SelectionConfirmationError, "range"):
                    create_selection_draft(
                        self._batch(1),
                        recommended_minimum=minimum,  # type: ignore[arg-type]
                        recommended_maximum=maximum,
                    )


class ConfirmedPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        parent = Path(self.temporary.name)
        self.session = parent / "session"
        self.workspace = parent / "workspace"
        self.repository = parent / "repository"
        self.export = self.session / "export-app"
        for path in (self.session, self.workspace, self.repository, self.export):
            path.mkdir()
        boundaries = RootBoundaries.create(
            session_root=self.session,
            workspace_root=self.workspace,
            repository_root=self.repository,
        )
        self.reader = SessionReader(boundaries)
        self.writer = WorkspaceWriter(boundaries)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _inputs(self, count: int):
        resolutions = []
        proxies = []
        for index in range(count):
            identifier = f"photo-{index:03d}"
            filename = f"{identifier}.jpg"
            payload = f"synthetic export {index}".encode()
            (self.export / filename).write_bytes(payload)
            asset_id = f"asset:.:{identifier}"
            export = LightroomExportEntry(
                f"export-app/{filename}",
                filename,
                ".jpg",
                ".jpg",
                len(payload),
                "2026-01-01T00:00:00.000000000Z",
            )
            resolutions.append(
                LightroomExportResolution(
                    asset_id,
                    identifier,
                    5,
                    f"{identifier}.xmp",
                    "resolved",
                    export,
                    (),
                )
            )
            proxies.append(
                ProxyEntry(
                    asset_id,
                    identifier,
                    5,
                    "lightroom_export",
                    export.relative_path,
                    hashlib.sha256(payload).hexdigest(),
                    "generated",
                    f"proxies/{identifier}.jpg",
                    100,
                    80,
                    1000,
                    hashlib.sha256(asset_id.encode()).hexdigest(),
                    (),
                    None,
                )
            )
        values = tuple(resolutions)
        return (
            LightroomExportResolutionResult(values, len(values), 0, 0, 0),
            ProxyBatchResult(tuple(proxies), len(proxies), 0, 0),
        )

    def _limits(self):
        return ReviewPackageLimits.create(
            max_jpg_bytes=1000,
            max_package_bytes=10000,
        )

    def test_package_without_confirmation_is_blocked_before_read_or_write(self) -> None:
        resolutions, _ = self._inputs(1)
        with mock.patch(
            "photo_session_workflow.paths.SessionReader.read_lightroom_export",
            autospec=True,
            side_effect=AssertionError("must not read"),
        ):
            with self.assertRaisesRegex(ReviewPackageConfirmationError, "confirmed"):
                generate_review_package(
                    self.reader,
                    self.writer,
                    export_relative_directory="export-app",
                    resolutions=resolutions,
                    destination_relative_path="review.zip",
                    limits=self._limits(),
                )
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_package_contains_exactly_confirmed_subset(self) -> None:
        resolutions, proxies = self._inputs(3)
        draft = create_selection_draft(proxies)
        draft = update_selection(
            draft,
            remove_asset_ids=("asset:.:photo-001",),
        )
        confirmation = confirm_selection(draft, explicit_confirmation=True)
        result = generate_review_package(
            self.reader,
            self.writer,
            export_relative_directory="export-app",
            resolutions=resolutions,
            destination_relative_path="review.zip",
            limits=self._limits(),
            confirmation=confirmation,
        )
        self.assertEqual(result.manifest.selected_count, 2)
        self.assertEqual(
            tuple(item.asset_id for item in result.manifest.assets),
            ("asset:.:photo-000", "asset:.:photo-002"),
        )
        with ZipFile(io.BytesIO((self.workspace / "review.zip").read_bytes())) as archive:
            self.assertEqual(
                archive.namelist(),
                [
                    "manifest.json",
                    "images/photo-000.jpg",
                    "images/photo-002.jpg",
                ],
            )

    def test_stale_confirmation_is_blocked_before_read_or_write(self) -> None:
        resolutions, proxies = self._inputs(1)
        entry = proxies.entries[0]
        stale = ProxyBatchResult(
            (
                ProxyEntry(
                    entry.asset_id,
                    entry.identifier_name,
                    entry.rating,
                    entry.preview_source,
                    "export-app/different.jpg",
                    entry.source_sha256,
                    entry.status,
                    entry.proxy_relative_path,
                    entry.width_px,
                    entry.height_px,
                    entry.size_bytes,
                    entry.sha256,
                    entry.warnings,
                    entry.error_code,
                ),
            ),
            1,
            0,
            0,
        )
        confirmation = confirm_selection(
            create_selection_draft(stale), explicit_confirmation=True
        )
        with mock.patch(
            "photo_session_workflow.paths.SessionReader.read_lightroom_export",
            autospec=True,
            side_effect=AssertionError("must not read"),
        ):
            with self.assertRaisesRegex(ReviewPackageConfirmationError, "matches"):
                generate_review_package(
                    self.reader,
                    self.writer,
                    export_relative_directory="export-app",
                    resolutions=resolutions,
                    destination_relative_path="review.zip",
                    limits=self._limits(),
                    confirmation=confirmation,
                )
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_export_changed_after_proxy_is_blocked_before_publication(self) -> None:
        resolutions, proxies = self._inputs(1)
        confirmation = confirm_selection(
            create_selection_draft(proxies), explicit_confirmation=True
        )
        (self.export / "photo-000.jpg").write_bytes(b"changed after proxy generation")
        with self.assertRaisesRegex(ReviewPackageConfirmationError, "changed"):
            generate_review_package(
                self.reader,
                self.writer,
                export_relative_directory="export-app",
                resolutions=resolutions,
                destination_relative_path="review.zip",
                limits=self._limits(),
                confirmation=confirmation,
            )
        self.assertEqual(list(self.workspace.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
