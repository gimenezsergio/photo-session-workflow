from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

from photo_session_workflow.manual_recommendations import (
    RECOMMENDATION_CATEGORIES,
    ManualRecommendationError,
    ManualRecommendationStore,
)
from photo_session_workflow.paths import RootBoundaries, WorkspaceWriter
from photo_session_workflow.review_handoff import (
    ReviewAssetSummary,
    ReviewPackageSummary,
)


class _Clock:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> str:
        self.index += 1
        return f"2026-08-12T12:00:{self.index:02d}.000000Z"


class ManualRecommendationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        parent = Path(self.temporary.name)
        self.session = parent / "session"
        self.workspace = parent / "workspace"
        self.repository = parent / "repository"
        for path in (self.session, self.workspace, self.repository):
            path.mkdir()
        boundaries = RootBoundaries.create(
            session_root=self.session,
            workspace_root=self.workspace,
            repository_root=self.repository,
        )
        self.writer = WorkspaceWriter(boundaries)
        self.clock = _Clock()
        self.review = self._review("a" * 64)
        self.store = ManualRecommendationStore(self.writer, clock=self.clock)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _review(package_hash: str) -> ReviewPackageSummary:
        assets = (
            ReviewAssetSummary(
                "asset:.:one",
                "one",
                5,
                "lightroom_export",
                "images/proxy-one.jpg",
                96,
                64,
                (),
            ),
            ReviewAssetSummary(
                "asset:.:two",
                "two",
                4,
                "lightroom_export",
                "images/proxy-two.jpg",
                90,
                60,
                (),
            ),
        )
        return ReviewPackageSummary(
            "review.zip",
            "review.zip",
            100,
            package_hash,
            "0.3",
            2,
            "contact-sheet.jpg",
            (
                "manifest.json",
                "contact-sheet.jpg",
                "images/proxy-one.jpg",
                "images/proxy-two.jpg",
            ),
            assets,
            (),
            (
                "package_contains_identifiable_images",
                "sharing_requires_explicit_user_action",
                "no_automatic_external_transmission",
            ),
        )

    def test_all_allowed_categories_can_be_recorded_manually(self) -> None:
        records = tuple(
            self.store.add(
                self.review,
                asset_id="asset:.:one",
                category=category,
                recommendation=f"Manual recommendation for {category}",
            )
            for category in sorted(RECOMMENDATION_CATEGORIES)
        )
        self.assertEqual(len(records), 7)
        self.assertTrue(all(item.status == "pending" for item in records))
        self.assertEqual(
            {item.category for item in self.store.list_for_review(self.review)},
            RECOMMENDATION_CATEGORIES,
        )

    def test_record_preserves_review_and_asset_identity(self) -> None:
        record = self.store.add(
            self.review,
            asset_id="asset:.:two",
            category="exposure",
            recommendation="  Raise exposure slightly.  ",
        )
        self.assertEqual(record.package_sha256, self.review.sha256)
        self.assertEqual(record.asset_id, "asset:.:two")
        self.assertEqual(record.identifier_name, "two")
        self.assertEqual(record.recommendation, "Raise exposure slightly.")
        self.assertRegex(record.recommendation_id, r"^[0-9a-f]{32}$")

    def test_status_changes_are_explicit_and_audited(self) -> None:
        record = self.store.add(
            self.review,
            asset_id="asset:.:one",
            category="color",
            recommendation="Reduce the green cast.",
        )
        confirmed = self.store.set_status(
            self.review,
            record.recommendation_id,
            status="confirmed",
            expected_status="pending",
            note="Approved during manual review.",
        )
        rejected = self.store.set_status(
            self.review,
            record.recommendation_id,
            status="rejected",
            expected_status="confirmed",
        )
        self.assertEqual(confirmed.status, "confirmed")
        self.assertEqual(rejected.status, "rejected")
        history = self.store.history(self.review, record.recommendation_id)
        self.assertEqual(
            tuple((item.previous_status, item.status) for item in history),
            ((None, "pending"), ("pending", "confirmed"), ("confirmed", "rejected")),
        )
        self.assertEqual(history[1].note, "Approved during manual review.")

    def test_initial_status_can_be_confirmed_or_rejected(self) -> None:
        confirmed = self.store.add(
            self.review,
            asset_id="asset:.:one",
            category="selection",
            recommendation="Keep this frame.",
            status="confirmed",
        )
        rejected = self.store.add(
            self.review,
            asset_id="asset:.:two",
            category="similarity",
            recommendation="Remove as duplicate.",
            status="rejected",
        )
        self.assertEqual(confirmed.status, "confirmed")
        self.assertEqual(rejected.status, "rejected")

    def test_unknown_asset_and_other_review_are_rejected(self) -> None:
        with self.assertRaisesRegex(ManualRecommendationError, "asset"):
            self.store.add(
                self.review,
                asset_id="asset:.:unknown",
                category="mask",
                recommendation="Add a mask.",
            )
        record = self.store.add(
            self.review,
            asset_id="asset:.:one",
            category="mask",
            recommendation="Add a subject mask.",
        )
        other = self._review("b" * 64)
        self.assertEqual(self.store.list_for_review(other), ())
        with self.assertRaisesRegex(ManualRecommendationError, "package"):
            self.store.set_status(
                other,
                record.recommendation_id,
                status="confirmed",
            )

    def test_invalid_categories_statuses_text_and_stale_updates_are_rejected(self) -> None:
        for category in ("", "unknown", "xmp_write", None):
            with self.subTest(category=category):
                with self.assertRaises(ManualRecommendationError):
                    self.store.add(
                        self.review,
                        asset_id="asset:.:one",
                        category=category,  # type: ignore[arg-type]
                        recommendation="Valid text.",
                    )
        for text in ("", "   ", "x" * 4_001, "bad\x00text"):
            with self.subTest(text=text[:10]):
                with self.assertRaises(ManualRecommendationError):
                    self.store.add(
                        self.review,
                        asset_id="asset:.:one",
                        category="exposure",
                        recommendation=text,
                    )
        record = self.store.add(
            self.review,
            asset_id="asset:.:one",
            category="exposure",
            recommendation="Valid text.",
        )
        with self.assertRaisesRegex(ManualRecommendationError, "concurrently"):
            self.store.set_status(
                self.review,
                record.recommendation_id,
                status="confirmed",
                expected_status="rejected",
            )
        with self.assertRaisesRegex(ManualRecommendationError, "already"):
            self.store.set_status(
                self.review,
                record.recommendation_id,
                status="pending",
            )

    def test_database_persists_only_inside_workspace(self) -> None:
        record = self.store.add(
            self.review,
            asset_id="asset:.:one",
            category="global_adjustment",
            recommendation="Lower highlights.",
        )
        reopened = ManualRecommendationStore(self.writer, clock=self.clock)
        self.assertEqual(reopened.list_for_review(self.review), (record,))
        self.assertEqual(reopened.database_relative_path, "state/recommendations.sqlite3")
        self.assertTrue((self.workspace / reopened.database_relative_path).is_file())
        self.assertFalse(any(self.session.iterdir()))
        self.assertFalse(any(self.repository.iterdir()))

    def test_source_session_is_unchanged(self) -> None:
        source = self.session / "synthetic.NEF"
        source.write_bytes(b"synthetic raw marker")
        before = (source.stat().st_size, hashlib.sha256(source.read_bytes()).hexdigest())
        record = self.store.add(
            self.review,
            asset_id="asset:.:one",
            category="mask",
            recommendation="Consider a background mask.",
        )
        self.store.set_status(
            self.review,
            record.recommendation_id,
            status="rejected",
        )
        after = (source.stat().st_size, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(before, after)

    def test_parameterized_text_cannot_change_schema_or_leak_paths(self) -> None:
        hostile_text = "'); DROP TABLE manual_recommendations; --"
        record = self.store.add(
            self.review,
            asset_id="asset:.:one",
            category="exposure",
            recommendation=hostile_text,
        )
        self.assertEqual(self.store.list_for_review(self.review), (record,))
        database = self.workspace / self.store.database_relative_path
        payload = database.read_bytes()
        self.assertNotIn(str(self.session).encode(), payload)
        self.assertNotIn(str(self.repository).encode(), payload)
        self.assertNotIn(b"GPS", payload)

    def test_database_path_escape_absolute_link_and_reparse_are_rejected(self) -> None:
        for invalid in ("", "../state.db", str(self.workspace / "state.db"), "state.txt"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ManualRecommendationError):
                    ManualRecommendationStore(
                        self.writer,
                        database_relative_path=invalid,
                    )
        with mock.patch(
            "photo_session_workflow.manual_recommendations.reject_links_or_reparse_points",
            side_effect=ManualRecommendationError("simulated reparse point"),
        ):
            with self.assertRaisesRegex(ManualRecommendationError, "reparse"):
                self.store.list_for_review(self.review)

    def test_models_are_immutable_and_store_exposes_no_apply_operation(self) -> None:
        record = self.store.add(
            self.review,
            asset_id="asset:.:one",
            category="mask",
            recommendation="Manual mask suggestion.",
        )
        with self.assertRaises(FrozenInstanceError):
            record.status = "confirmed"  # type: ignore[misc]
        forbidden = {"apply", "write_xmp", "update_lightroom", "delete"}
        self.assertTrue(forbidden.isdisjoint(dir(self.store)))


if __name__ == "__main__":
    unittest.main()
