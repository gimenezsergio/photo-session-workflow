from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import warnings
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from photo_session_workflow.confirmed_review_package import (
    ConfirmedManifestAsset,
    ConfirmedReviewManifest,
    ConfirmedReviewPackageResult,
)
from photo_session_workflow.paths import RootBoundaries, WorkspaceWriter
from photo_session_workflow.review_handoff import (
    ReviewHandoffError,
    inspect_review_package,
    prepare_manual_download,
)


class ReviewHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        parent = Path(self.temporary.name)
        session = parent / "session"
        self.workspace = parent / "workspace"
        repository = parent / "repository"
        for path in (session, self.workspace, repository):
            path.mkdir()
        boundaries = RootBoundaries.create(
            session_root=session,
            workspace_root=self.workspace,
            repository_root=repository,
        )
        self.writer = WorkspaceWriter(boundaries)
        self.limit = 1_000_000

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _manifest() -> ConfirmedReviewManifest:
        assets = (
            ConfirmedManifestAsset(
                "asset:.:one",
                "one",
                5,
                "lightroom_export",
                "images/proxy-one.jpg",
                96,
                64,
                ("source_metadata_removed_by_reencoding",),
            ),
            ConfirmedManifestAsset(
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
        return ConfirmedReviewManifest(
            "0.3",
            2,
            "contact-sheet.jpg",
            assets,
            (
                "proxies_contain_identifiable_images",
                "manual_external_sharing_requires_user_action",
                "no_automatic_transmission",
            ),
        )

    @staticmethod
    def _info(name: str) -> ZipInfo:
        info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_STORED
        return info

    def _package(
        self,
        *,
        relative_path: str = "review.zip",
        manifest: ConfirmedReviewManifest | None = None,
        members: tuple[str, ...] | None = None,
        duplicate: str | None = None,
    ) -> tuple[ConfirmedReviewPackageResult, bytes]:
        manifest = manifest or self._manifest()
        members = members or (
            "manifest.json",
            "contact-sheet.jpg",
            *(asset.proxy_member for asset in manifest.assets),
        )
        buffer = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
                for name in members:
                    if name == "manifest.json":
                        payload = manifest.to_json().encode("utf-8")
                    elif name == "contact-sheet.jpg":
                        payload = b"synthetic contact sheet"
                    else:
                        payload = f"synthetic {name}".encode("utf-8")
                    archive.writestr(self._info(name), payload)
                if duplicate is not None:
                    archive.writestr(self._info(duplicate), b"duplicate")
        payload = buffer.getvalue()
        self.writer.publish_bytes_atomically(relative_path, payload)
        result_members = members if duplicate is None else (*members, duplicate)
        result = ConfirmedReviewPackageResult(
            relative_path,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            manifest,
            result_members,
            "contact-sheets/confirmed/synthetic.jpg",
        )
        return result, payload

    def test_inspection_returns_sanitized_review_summary(self) -> None:
        package, _ = self._package()
        summary = inspect_review_package(
            self.writer,
            package,
            max_package_bytes=self.limit,
        )
        self.assertEqual(summary.schema_version, "0.3")
        self.assertEqual(summary.selected_count, 2)
        self.assertEqual(summary.download_name, "review.zip")
        self.assertEqual(
            tuple((item.identifier_name, item.rating) for item in summary.assets),
            (("one", 5), ("two", 4)),
        )
        self.assertIn("package_contains_identifiable_images", summary.privacy_notices)

    def test_summary_json_contains_no_images_or_absolute_paths(self) -> None:
        package, _ = self._package()
        summary = inspect_review_package(
            self.writer,
            package,
            max_package_bytes=self.limit,
        )
        serialized = summary.to_json()
        parsed = json.loads(serialized)
        self.assertEqual(parsed["selected_count"], 2)
        self.assertNotIn(str(self.workspace), serialized)
        self.assertNotIn("synthetic contact sheet", serialized)
        self.assertNotIn("content", serialized)

    def test_explicit_download_returns_exact_verified_zip_in_memory(self) -> None:
        package, expected = self._package()
        summary = inspect_review_package(
            self.writer,
            package,
            max_package_bytes=self.limit,
        )
        download = prepare_manual_download(
            self.writer,
            summary,
            explicit_download=True,
            max_package_bytes=self.limit,
        )
        self.assertEqual(download.filename, "review.zip")
        self.assertEqual(download.media_type, "application/zip")
        self.assertEqual(download.content, expected)
        self.assertEqual(download.sha256, hashlib.sha256(expected).hexdigest())
        self.assertNotIn("PK", repr(download))

    def test_download_requires_exact_true_before_reading_workspace(self) -> None:
        package, _ = self._package()
        summary = inspect_review_package(
            self.writer,
            package,
            max_package_bytes=self.limit,
        )
        for value in (False, None, 1, "yes"):
            with self.subTest(value=value):
                with mock.patch.object(
                    WorkspaceWriter,
                    "read_bytes",
                    autospec=True,
                ) as read:
                    with self.assertRaisesRegex(ReviewHandoffError, "explicit"):
                        prepare_manual_download(
                            self.writer,
                            summary,
                            explicit_download=value,  # type: ignore[arg-type]
                            max_package_bytes=self.limit,
                        )
                    read.assert_not_called()

    def test_changed_package_is_rejected_before_download(self) -> None:
        package, _ = self._package()
        summary = inspect_review_package(
            self.writer,
            package,
            max_package_bytes=self.limit,
        )
        (self.workspace / "review.zip").write_bytes(b"changed")
        with self.assertRaisesRegex(ReviewHandoffError, "changed"):
            prepare_manual_download(
                self.writer,
                summary,
                explicit_download=True,
                max_package_bytes=self.limit,
            )

    def test_result_size_hash_and_manifest_must_match_published_zip(self) -> None:
        package, payload = self._package()
        variants = (
            ConfirmedReviewPackageResult(
                package.relative_path,
                package.size_bytes + 1,
                package.sha256,
                package.manifest,
                package.members,
                package.contact_sheet_relative_path,
            ),
            ConfirmedReviewPackageResult(
                package.relative_path,
                package.size_bytes,
                "0" * 64,
                package.manifest,
                package.members,
                package.contact_sheet_relative_path,
            ),
        )
        for variant in variants:
            with self.subTest(variant=variant.sha256):
                with self.assertRaises(ReviewHandoffError):
                    inspect_review_package(
                        self.writer,
                        variant,
                        max_package_bytes=len(payload) + 10,
                    )
        different = self._manifest()
        object.__setattr__(different, "selected_count", 1)
        variant = ConfirmedReviewPackageResult(
            package.relative_path,
            package.size_bytes,
            package.sha256,
            different,
            package.members,
            package.contact_sheet_relative_path,
        )
        with self.assertRaisesRegex(ReviewHandoffError, "manifest"):
            inspect_review_package(
                self.writer,
                variant,
                max_package_bytes=self.limit,
            )

    def test_unknown_extra_missing_or_unsafe_members_are_rejected(self) -> None:
        cases = (
            ("extra.zip", ("manifest.json", "contact-sheet.jpg", "images/proxy-one.jpg", "images/proxy-two.jpg", "extra.txt")),
            ("missing.zip", ("manifest.json", "contact-sheet.jpg", "images/proxy-one.jpg")),
            ("unsafe.zip", ("manifest.json", "contact-sheet.jpg", "images/proxy-one.jpg", "../proxy-two.jpg")),
        )
        for path, members in cases:
            with self.subTest(path=path):
                package, _ = self._package(relative_path=path, members=members)
                with self.assertRaises(ReviewHandoffError):
                    inspect_review_package(
                        self.writer,
                        package,
                        max_package_bytes=self.limit,
                    )

    def test_duplicate_zip_members_are_rejected_case_insensitively(self) -> None:
        package, _ = self._package(duplicate="IMAGES/PROXY-ONE.JPG")
        with self.assertRaisesRegex(ReviewHandoffError, "duplicate"):
            inspect_review_package(
                self.writer,
                package,
                max_package_bytes=self.limit,
            )

    def test_identifiers_and_warnings_must_be_sanitized(self) -> None:
        base = self._manifest()
        unsafe_asset = ConfirmedManifestAsset(
            base.assets[0].asset_id,
            "C:\\private\\name",
            base.assets[0].rating,
            base.assets[0].preview_source,
            base.assets[0].proxy_member,
            base.assets[0].width_px,
            base.assets[0].height_px,
            ("safe_warning",),
        )
        variants = (
            ConfirmedReviewManifest(
                "0.3",
                2,
                "contact-sheet.jpg",
                (unsafe_asset, base.assets[1]),
                base.warnings,
            ),
            ConfirmedReviewManifest(
                "0.3",
                2,
                "contact-sheet.jpg",
                base.assets,
                ("C:\\private\\warning",),
            ),
        )
        for index, manifest in enumerate(variants):
            with self.subTest(index=index):
                package, _ = self._package(
                    relative_path=f"unsafe-metadata-{index}.zip",
                    manifest=manifest,
                )
                with self.assertRaises(ReviewHandoffError):
                    inspect_review_package(
                        self.writer,
                        package,
                        max_package_bytes=self.limit,
                    )

    def test_size_limit_is_applied_to_inspection_and_download(self) -> None:
        package, payload = self._package()
        with self.assertRaisesRegex(ReviewHandoffError, "limit"):
            inspect_review_package(
                self.writer,
                package,
                max_package_bytes=len(payload) - 1,
            )
        summary = inspect_review_package(
            self.writer,
            package,
            max_package_bytes=len(payload),
        )
        with self.assertRaisesRegex(ReviewHandoffError, "limit"):
            prepare_manual_download(
                self.writer,
                summary,
                explicit_download=True,
                max_package_bytes=len(payload) - 1,
            )

    def test_review_models_are_immutable_and_no_file_is_created(self) -> None:
        package, _ = self._package()
        before = tuple(sorted(path.name for path in self.workspace.iterdir()))
        summary = inspect_review_package(
            self.writer,
            package,
            max_package_bytes=self.limit,
        )
        prepare_manual_download(
            self.writer,
            summary,
            explicit_download=True,
            max_package_bytes=self.limit,
        )
        after = tuple(sorted(path.name for path in self.workspace.iterdir()))
        self.assertEqual(before, after)
        with self.assertRaises(FrozenInstanceError):
            summary.selected_count = 1  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
