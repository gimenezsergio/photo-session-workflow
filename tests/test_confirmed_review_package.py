from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

from PIL import Image

from photo_session_workflow.confirmed_review_package import (
    ConfirmedReviewPackageError,
    ConfirmedReviewPackageLimitError,
    ConfirmedReviewPackageLimits,
    generate_confirmed_review_package,
)
from photo_session_workflow.contact_sheet import ContactSheetSettings
from photo_session_workflow.lightroom_exports import (
    LightroomExportEntry,
    LightroomExportResolution,
    LightroomExportResolutionResult,
)
from photo_session_workflow.paths import RootBoundaries, SessionReader, WorkspaceWriter
from photo_session_workflow.proxies import (
    ProxyBatchResult,
    ProxySettings,
    generate_proxies,
)
from photo_session_workflow.selection_confirmation import (
    confirm_selection,
    create_selection_draft,
    update_selection,
)


class ConfirmedReviewPackageTests(unittest.TestCase):
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
        self.proxy_settings = ProxySettings.create(
            long_edge_px=96,
            jpeg_quality=82,
            max_source_bytes=500_000,
            max_source_pixels=1_000_000,
        )
        self.sheet_settings = ContactSheetSettings.create(
            columns=2,
            cell_width_px=160,
            thumbnail_height_px=100,
            label_height_px=40,
            padding_px=5,
            jpeg_quality=82,
            max_output_pixels=1_000_000,
            max_proxy_bytes=500_000,
        )
        self.limits = ConfirmedReviewPackageLimits.create(
            max_proxy_bytes=500_000,
            max_contact_sheet_bytes=500_000,
            max_package_bytes=2_000_000,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _inputs(self, names: tuple[str, ...]):
        resolutions = []
        for index, name in enumerate(names):
            image = Image.new(
                "RGB",
                (120 + index * 10, 80 + index * 5),
                (30 + index * 40, 60, 120),
            )
            source = self.export / f"{name}.jpg"
            image.save(source, format="JPEG", quality=90)
            payload_size = source.stat().st_size
            export = LightroomExportEntry(
                f"export-app/{name}.jpg",
                f"{name}.jpg",
                ".jpg",
                ".jpg",
                payload_size,
                "2026-01-01T00:00:00.000000000Z",
            )
            resolutions.append(
                LightroomExportResolution(
                    f"asset:.:{name.casefold()}",
                    name,
                    5,
                    f"{name}.xmp",
                    "resolved",
                    export,
                    (),
                )
            )
        values = tuple(resolutions)
        resolution_result = LightroomExportResolutionResult(
            values, len(values), 0, 0, 0
        )
        proxies = generate_proxies(
            self.reader,
            self.writer,
            export_relative_directory="export-app",
            resolutions=resolution_result,
            settings=self.proxy_settings,
        )
        self.assertTrue(proxies.ready)
        return resolution_result, proxies

    def _confirmation(self, proxies: ProxyBatchResult, *, remove: tuple[str, ...] = ()):
        draft = create_selection_draft(proxies)
        if remove:
            draft = update_selection(draft, remove_asset_ids=remove)
        return confirm_selection(draft, explicit_confirmation=True)

    def _package(
        self,
        proxies: ProxyBatchResult,
        confirmation,
        *,
        destination: str = "review.zip",
        limits: ConfirmedReviewPackageLimits | None = None,
    ):
        return generate_confirmed_review_package(
            self.writer,
            proxies=proxies,
            confirmation=confirmation,
            contact_sheet_settings=self.sheet_settings,
            destination_relative_path=destination,
            limits=limits or self.limits,
        )

    def test_package_contains_manifest_sheet_and_exact_confirmed_proxies(self) -> None:
        _, proxies = self._inputs(("one", "two", "three"))
        confirmation = self._confirmation(
            proxies,
            remove=("asset:.:two",),
        )
        result = self._package(proxies, confirmation)
        self.assertEqual(result.manifest.schema_version, "0.3")
        self.assertEqual(result.manifest.selected_count, 2)
        self.assertEqual(
            tuple(item.identifier_name for item in result.manifest.assets),
            ("one", "three"),
        )
        with ZipFile(self.workspace / "review.zip") as archive:
            self.assertEqual(archive.namelist(), list(result.members))
            self.assertEqual(archive.namelist()[:2], ["manifest.json", "contact-sheet.jpg"])
            self.assertEqual(len(archive.namelist()), 4)
            self.assertFalse(any("two" in name for name in archive.namelist()))
            self.assertEqual(
                json.loads(archive.read("manifest.json"))["selected_count"], 2
            )

    def test_manifest_is_minimized_sanitized_and_identifies_lightroom_assets(self) -> None:
        _, proxies = self._inputs(("selection-a",))
        result = self._package(proxies, self._confirmation(proxies))
        serialized = result.manifest.to_json()
        payload = json.loads(serialized)
        asset = payload["assets"][0]
        self.assertEqual(asset["identifier_name"], "selection-a")
        self.assertEqual(asset["rating"], 5)
        self.assertEqual(asset["preview_source"], "lightroom_export")
        self.assertGreater(asset["width_px"], 0)
        self.assertGreater(asset["height_px"], 0)
        for forbidden in (
            str(self.session),
            str(self.workspace),
            "GPS",
            "<xmp",
            "source_relative_path",
            "source_sha256",
            "proxy_sha256",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_proxy_members_equal_verified_workspace_proxy_bytes(self) -> None:
        _, proxies = self._inputs(("one", "two"))
        result = self._package(proxies, self._confirmation(proxies))
        by_asset = {entry.asset_id: entry for entry in proxies.entries}
        with ZipFile(self.workspace / "review.zip") as archive:
            for asset in result.manifest.assets:
                entry = by_asset[asset.asset_id]
                expected = self.writer.read_bytes(
                    entry.proxy_relative_path,  # type: ignore[arg-type]
                    max_bytes=self.limits.max_proxy_bytes,
                )
                self.assertEqual(archive.read(asset.proxy_member), expected)

    def test_contact_sheet_is_regenerated_for_confirmed_subset(self) -> None:
        _, proxies = self._inputs(("one", "two", "three"))
        confirmation = self._confirmation(
            proxies,
            remove=("asset:.:two", "asset:.:three"),
        )
        result = self._package(proxies, confirmation)
        sheet = self.writer.read_bytes(
            result.contact_sheet_relative_path,
            max_bytes=self.limits.max_contact_sheet_bytes,
        )
        with Image.open(io.BytesIO(sheet)) as image:
            self.assertEqual(image.size, (320, 150))
        self.assertEqual(result.manifest.selected_count, 1)

    def test_package_bytes_are_deterministic_and_second_sheet_is_reused(self) -> None:
        _, proxies = self._inputs(("one", "two"))
        confirmation = self._confirmation(proxies)
        first = self._package(proxies, confirmation, destination="first.zip")
        second = self._package(proxies, confirmation, destination="second.zip")
        first_bytes = (self.workspace / "first.zip").read_bytes()
        second_bytes = (self.workspace / "second.zip").read_bytes()
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.contact_sheet_relative_path, second.contact_sheet_relative_path)

    def test_tampered_proxy_blocks_sheet_and_package(self) -> None:
        _, proxies = self._inputs(("one",))
        confirmation = self._confirmation(proxies)
        proxy_path = self.workspace / proxies.entries[0].proxy_relative_path  # type: ignore[arg-type]
        proxy_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ConfirmedReviewPackageError, "contact sheet"):
            self._package(proxies, confirmation)
        self.assertFalse((self.workspace / "review.zip").exists())

    def test_missing_or_changed_proxy_result_blocks_package(self) -> None:
        _, proxies = self._inputs(("one", "two"))
        confirmation = self._confirmation(proxies)
        missing = ProxyBatchResult((proxies.entries[0],), 1, 0, 0)
        with self.assertRaisesRegex(ConfirmedReviewPackageError, "absent"):
            self._package(missing, confirmation)
        changed_entry = proxies.entries[0]
        changed = ProxyBatchResult(
            (
                changed_entry,
                type(proxies.entries[1])(
                    proxies.entries[1].asset_id,
                    proxies.entries[1].identifier_name,
                    4,
                    proxies.entries[1].preview_source,
                    proxies.entries[1].source_relative_path,
                    proxies.entries[1].source_sha256,
                    proxies.entries[1].status,
                    proxies.entries[1].proxy_relative_path,
                    proxies.entries[1].width_px,
                    proxies.entries[1].height_px,
                    proxies.entries[1].size_bytes,
                    proxies.entries[1].sha256,
                    proxies.entries[1].warnings,
                    proxies.entries[1].error_code,
                ),
            ),
            2,
            0,
            0,
        )
        with self.assertRaisesRegex(ConfirmedReviewPackageError, "matches"):
            self._package(changed, confirmation)

    def test_individual_contact_and_total_limits_block_publication(self) -> None:
        _, proxies = self._inputs(("one", "two"))
        confirmation = self._confirmation(proxies)
        proxy_limit = ConfirmedReviewPackageLimits.create(
            max_proxy_bytes=1,
            max_contact_sheet_bytes=500_000,
            max_package_bytes=1_000_000,
        )
        with self.assertRaises(ConfirmedReviewPackageLimitError):
            self._package(proxies, confirmation, limits=proxy_limit)
        contact_limit = ConfirmedReviewPackageLimits.create(
            max_proxy_bytes=500_000,
            max_contact_sheet_bytes=1,
            max_package_bytes=1_000_000,
        )
        with self.assertRaisesRegex(ConfirmedReviewPackageLimitError, "contact sheet"):
            self._package(proxies, confirmation, limits=contact_limit)
        sheet_files = tuple((self.workspace / "contact-sheets" / "confirmed").iterdir())
        self.assertEqual(len(sheet_files), 1)
        sheet_size = sheet_files[0].stat().st_size
        largest_proxy = max(entry.size_bytes for entry in proxies.entries)  # type: ignore[type-var]
        total_limit = ConfirmedReviewPackageLimits.create(
            max_proxy_bytes=largest_proxy,
            max_contact_sheet_bytes=sheet_size,
            max_package_bytes=max(largest_proxy, sheet_size),
        )
        with self.assertRaises(ConfirmedReviewPackageLimitError):
            self._package(proxies, confirmation, limits=total_limit)
        self.assertFalse((self.workspace / "review.zip").exists())

    def test_existing_package_is_never_overwritten(self) -> None:
        _, proxies = self._inputs(("one",))
        existing = self.workspace / "review.zip"
        existing.write_bytes(b"previous")
        with self.assertRaises(FileExistsError):
            self._package(proxies, self._confirmation(proxies))
        self.assertEqual(existing.read_bytes(), b"previous")

    def test_publication_failure_leaves_no_zip_or_temporary(self) -> None:
        _, proxies = self._inputs(("one",))
        confirmation = self._confirmation(proxies)
        # Materialize the confirmed sheet before making package publication fail.
        self._package(proxies, confirmation, destination="first.zip")
        with mock.patch(
            "photo_session_workflow.paths.os.link",
            side_effect=OSError("simulated private path failure"),
        ):
            with self.assertRaisesRegex(ConfirmedReviewPackageError, "published"):
                self._package(proxies, confirmation, destination="failed.zip")
        self.assertFalse((self.workspace / "failed.zip").exists())
        self.assertFalse(any(path.suffix == ".tmp" for path in self.workspace.rglob("*")))

    def test_session_sources_are_unchanged_and_package_uses_only_workspace(self) -> None:
        _, proxies = self._inputs(("one", "two"))
        (self.session / "one.NEF").write_bytes(b"synthetic raw marker")
        (self.session / "one.xmp").write_text("synthetic xmp", encoding="utf-8")
        before = {
            path.relative_to(self.session).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in self.session.rglob("*")
            if path.is_file()
        }
        self._package(proxies, self._confirmation(proxies))
        after = {
            path.relative_to(self.session).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in self.session.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        with ZipFile(self.workspace / "review.zip") as archive:
            self.assertFalse(
                any(
                    name.casefold().endswith((".nef", ".xmp", ".acr", ".lrcat"))
                    for name in archive.namelist()
                )
            )

    def test_invalid_destination_limits_and_models(self) -> None:
        _, proxies = self._inputs(("one",))
        confirmation = self._confirmation(proxies)
        for invalid in ("", "review.jpg", "../review.zip", str(self.workspace / "x.zip")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ConfirmedReviewPackageError):
                    self._package(proxies, confirmation, destination=invalid)
        with self.assertRaises(ValueError):
            ConfirmedReviewPackageLimits.create(
                max_proxy_bytes=100,
                max_contact_sheet_bytes=200,
                max_package_bytes=50,
            )
        with self.assertRaises(FrozenInstanceError):
            self.limits.max_package_bytes = 1  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
