from __future__ import annotations

import hashlib
import io
import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

from photo_session_workflow.inventory import InventoryResult
from photo_session_workflow.lightroom_exports import (
    LightroomExportEntry,
    LightroomExportInventory,
    LightroomExportResolution,
    LightroomExportResolutionResult,
    resolve_lightroom_exports,
)
from photo_session_workflow.paths import (
    PathBoundaryError,
    RootBoundaries,
    SessionReader,
    WorkspaceWriter,
)
from photo_session_workflow.proxies import ProxyBatchResult, ProxyEntry
from photo_session_workflow.rating_filter import RatingFilter, filter_assets_by_rating
from photo_session_workflow.relations import relate_inventory
from photo_session_workflow.review_package import (
    ReviewPackageError,
    ReviewPackageIncompleteError,
    ReviewPackageLimitError,
    ReviewPackageLimits,
    build_review_manifest,
    generate_review_package,
)
from photo_session_workflow.selection_confirmation import (
    confirm_selection,
    create_selection_draft,
)
from photo_session_workflow.xmp_rating import RatingReadResult


class LightroomExportPackageTests(unittest.TestCase):
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

    def _write_main(self, base: str, *, rating: int = 5) -> None:
        (self.session / f"{base}.NEF").write_bytes(b"synthetic raw marker")
        (self.session / f"{base}.JPG").write_bytes(b"synthetic camera jpg marker")
        (self.session / f"{base}.xmp").write_text(
            f"synthetic xmp rating marker {rating}", encoding="utf-8"
        )

    def _write_export(self, filename: str, payload: bytes | None = None) -> Path:
        destination = self.export / filename
        destination.write_bytes(payload or f"export:{filename}".encode())
        return destination

    def _selection(self, bases: tuple[str, ...]):
        for base in bases:
            self._write_main(base)
        inventory = self.reader.inventory(recursive=False)
        relations = relate_inventory(inventory)
        ratings = tuple(
            RatingReadResult(asset.asset_id, 5, "rated", f"{asset.original_base_names[0]}.xmp", (), None)
            for asset in relations.assets
        )
        return filter_assets_by_rating(
            relations, ratings, RatingFilter.create(minimum_rating=1)
        )

    def _resolved(self, bases: tuple[str, ...]):
        selection = self._selection(bases)
        for base in bases:
            self._write_export(f"{base}.jpg")
        inventory = self.reader.inventory_lightroom_exports("export-app")
        return resolve_lightroom_exports(selection, inventory)

    def _limits(self, *, jpg: int = 100_000, package: int = 1_000_000):
        return ReviewPackageLimits.create(
            max_jpg_bytes=jpg, max_package_bytes=package
        )

    def _confirmation(self, resolutions, *, selected_asset_ids=None):
        entries = tuple(
            ProxyEntry(
                item.asset_id,
                item.identifier_name,
                item.rating,
                "lightroom_export",
                item.export.relative_path,
                hashlib.sha256(
                    (self.session / item.export.relative_path).read_bytes()
                ).hexdigest(),
                "generated",
                f"proxies/proxy-{index}.jpg",
                80,
                60,
                100,
                hashlib.sha256(item.asset_id.encode()).hexdigest(),
                (),
                None,
            )
            for index, item in enumerate(resolutions.resolutions)
            if item.status == "resolved" and item.export is not None
        )
        batch = ProxyBatchResult(entries, len(entries), 0, 0)
        draft = create_selection_draft(
            batch,
            initially_selected_asset_ids=selected_asset_ids,
        )
        return confirm_selection(draft, explicit_confirmation=True)

    def test_four_selected_assets_resolve_to_four_declared_exports(self) -> None:
        bases = ("DSC_9448", "DSC_9450", "DSC_9462", "DSC_9519")
        result = self._resolved(bases)
        self.assertTrue(result.ready)
        self.assertEqual(result.resolved_count, 4)
        self.assertTrue(
            all(item.export.relative_path.startswith("export-app/") for item in result.resolutions)  # type: ignore[union-attr]
        )

    def test_export_inventory_is_non_recursive_and_jpg_only(self) -> None:
        self._write_export("selected.jpg")
        self._write_export("ignored.xmp")
        nested = self.export / "nested"
        nested.mkdir()
        (nested / "hidden.jpg").write_bytes(b"hidden")
        inventory = self.reader.inventory_lightroom_exports("export-app")
        self.assertEqual([entry.filename for entry in inventory.entries], ["selected.jpg"])
        self.assertEqual(
            {notice.reason for notice in inventory.ignored},
            {"not_jpg_export", "recursion_disabled"},
        )

    def test_camera_jpg_and_unselected_export_are_never_packaged(self) -> None:
        resolved = self._resolved(("selected",))
        self._write_export("unselected.jpg", b"unselected export")
        result = generate_review_package(
            self.reader,
            self.writer,
            export_relative_directory="export-app",
            resolutions=resolved,
            destination_relative_path="review.zip",
            limits=self._limits(),
            confirmation=self._confirmation(resolved),
        )
        with ZipFile(self.workspace / "review.zip") as archive:
            self.assertEqual(archive.namelist(), ["manifest.json", "images/selected.jpg"])
            self.assertEqual(archive.read("images/selected.jpg"), b"export:selected.jpg")
            self.assertNotIn(b"camera", archive.read("images/selected.jpg"))
            self.assertNotIn("images/unselected.jpg", archive.namelist())
        self.assertEqual(result.members, ("manifest.json", "images/selected.jpg"))

    def test_missing_and_duplicate_exports_block_manifest_and_package(self) -> None:
        selection = self._selection(("missing", "duplicate"))
        self._write_export("duplicate.jpg")
        self._write_export("duplicate.JPEG")
        resolved = resolve_lightroom_exports(
            selection, self.reader.inventory_lightroom_exports("export-app")
        )
        self.assertEqual([item.status for item in resolved.resolutions], ["ambiguous", "missing"])
        with self.assertRaises(ReviewPackageIncompleteError) as context:
            build_review_manifest(resolved)
        self.assertEqual(
            set(context.exception.failures),
            {("duplicate", "ambiguous"), ("missing", "missing")},
        )
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_unicode_spaces_casefold_and_no_suffix_guessing(self) -> None:
        selection = self._selection(("Selección Ñ", "MixedCase", "plain"))
        self._write_export("Selección Ñ.JPG")
        self._write_export("mixedcase.jpeg")
        self._write_export("plain-Edit.jpg")
        resolved = resolve_lightroom_exports(
            selection, self.reader.inventory_lightroom_exports("export-app")
        )
        self.assertEqual(
            [item.status for item in resolved.resolutions],
            ["resolved", "missing", "resolved"],
        )

    def test_invalid_export_directory_paths_are_rejected(self) -> None:
        for invalid in ("", ".", "../export-app", os.fspath(self.export)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(PathBoundaryError):
                    self.reader.inventory_lightroom_exports(invalid)
        with self.assertRaisesRegex(PathBoundaryError, "existing directory"):
            self.reader.inventory_lightroom_exports("missing")

    def test_export_directory_symlink_is_rejected_when_available(self) -> None:
        link = self.session / "export-link"
        try:
            link.symlink_to(self.export, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")
        with self.assertRaisesRegex(PathBoundaryError, "symbolic link"):
            self.reader.inventory_lightroom_exports("export-link")

    def test_export_directory_reparse_point_is_rejected_deterministically(self) -> None:
        with mock.patch(
            "photo_session_workflow.paths._is_reparse_point",
            side_effect=lambda path: path == self.export,
        ):
            with self.assertRaisesRegex(PathBoundaryError, "reparse point"):
                self.reader.inventory_lightroom_exports("export-app")

    def test_export_file_is_revalidated_before_each_read(self) -> None:
        resolved = self._resolved(("photo",))
        source = self.export / "photo.jpg"
        with mock.patch(
            "photo_session_workflow.paths._is_reparse_point",
            side_effect=lambda path: path == source,
        ):
            with self.assertRaisesRegex(PathBoundaryError, "reparse point"):
                generate_review_package(
                    self.reader,
                    self.writer,
                    export_relative_directory="export-app",
                    resolutions=resolved,
                    destination_relative_path="review.zip",
                    limits=self._limits(),
                    confirmation=self._confirmation(resolved),
                )
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_rejected_matching_jpg_produces_invalid_resolution(self) -> None:
        selection = self._selection(("photo",))
        rejected = self._write_export("photo.jpg")
        with mock.patch(
            "photo_session_workflow.lightroom_exports.stat.FILE_ATTRIBUTE_REPARSE_POINT",
            1024,
        ), mock.patch(
            "photo_session_workflow.lightroom_exports.os.DirEntry.stat",
            autospec=True,
        ) as mocked_stat:
            real_stat = rejected.stat()
            mocked_stat.return_value = mock.Mock(
                st_mode=real_stat.st_mode,
                st_file_attributes=1024,
            )
            inventory = self.reader.inventory_lightroom_exports("export-app")
        resolution = resolve_lightroom_exports(selection, inventory)
        self.assertEqual(resolution.resolutions[0].status, "invalid")

    def test_manifest_02_is_deterministic_and_minimized(self) -> None:
        resolved = self._resolved(("photo",))
        first = build_review_manifest(resolved)
        second = build_review_manifest(resolved)
        self.assertEqual(first.to_json(), second.to_json())
        self.assertEqual(first.schema_version, "0.2")
        serialized = first.to_json()
        self.assertIn('"preview_source":"lightroom_export"', serialized)
        for forbidden in (str(self.session), "GPS", "<xmp", "EXIF", "binary"):
            self.assertNotIn(forbidden, serialized)

    def test_zip_order_metadata_and_bytes_are_deterministic(self) -> None:
        resolved = self._resolved(("b", "a"))
        first = generate_review_package(
            self.reader, self.writer,
            export_relative_directory="export-app", resolutions=resolved,
            destination_relative_path="first.zip", limits=self._limits(),
            confirmation=self._confirmation(resolved),
        )
        second = generate_review_package(
            self.reader, self.writer,
            export_relative_directory="export-app", resolutions=resolved,
            destination_relative_path="second.zip", limits=self._limits(),
            confirmation=self._confirmation(resolved),
        )
        first_bytes = (self.workspace / "first.zip").read_bytes()
        second_bytes = (self.workspace / "second.zip").read_bytes()
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first.sha256, hashlib.sha256(first_bytes).hexdigest())
        self.assertEqual(first.sha256, second.sha256)
        with ZipFile(io.BytesIO(first_bytes)) as archive:
            self.assertEqual(
                archive.namelist(), ["manifest.json", "images/a.jpg", "images/b.jpg"]
            )
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))

    def test_zip_slip_and_absolute_internal_names_are_rejected(self) -> None:
        (self.export / "escape.jpg").write_bytes(b"synthetic malicious-name fixture")
        malicious = LightroomExportEntry(
            "export-app/escape.jpg", "../escape.jpg", ".jpg", ".jpg", 1,
            "2026-01-01T00:00:00.000000000Z",
        )
        resolution = LightroomExportResolution(
            "asset:.:escape", "escape", 5, "escape.xmp", "resolved", malicious, ()
        )
        result = LightroomExportResolutionResult((resolution,), 1, 0, 0, 0)
        with self.assertRaisesRegex(ReviewPackageError, "unsafe"):
            generate_review_package(
                self.reader, self.writer,
                export_relative_directory="export-app", resolutions=result,
                destination_relative_path="review.zip", limits=self._limits(),
                confirmation=self._confirmation(result),
            )
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_absolute_package_destination_is_rejected_before_writing(self) -> None:
        resolved = self._resolved(("photo",))
        with self.assertRaisesRegex(ReviewPackageError, "relative"):
            generate_review_package(
                self.reader, self.writer,
                export_relative_directory="export-app", resolutions=resolved,
                destination_relative_path=os.fspath(self.workspace / "review.zip"),
                limits=self._limits(),
                confirmation=self._confirmation(resolved),
            )
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_individual_and_total_size_limits(self) -> None:
        resolved = self._resolved(("photo",))
        (self.export / "photo.jpg").write_bytes(b"x" * 20)
        with self.assertRaisesRegex(ReviewPackageLimitError, "individual"):
            generate_review_package(
                self.reader, self.writer,
                export_relative_directory="export-app", resolutions=resolved,
                destination_relative_path="individual.zip",
                limits=self._limits(jpg=10, package=1000),
                confirmation=self._confirmation(resolved),
            )
        with self.assertRaisesRegex(ReviewPackageLimitError, "package size"):
            generate_review_package(
                self.reader, self.writer,
                export_relative_directory="export-app", resolutions=resolved,
                destination_relative_path="total.zip",
                limits=self._limits(jpg=100, package=100),
                confirmation=self._confirmation(resolved),
            )
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_existing_package_is_never_overwritten(self) -> None:
        resolved = self._resolved(("photo",))
        previous = self.workspace / "review.zip"
        previous.write_bytes(b"previous")
        with self.assertRaises(FileExistsError):
            generate_review_package(
                self.reader, self.writer,
                export_relative_directory="export-app", resolutions=resolved,
                destination_relative_path="review.zip", limits=self._limits(),
                confirmation=self._confirmation(resolved),
            )
        self.assertEqual(previous.read_bytes(), b"previous")

    def test_write_failure_leaves_no_partial_or_temporary_package(self) -> None:
        resolved = self._resolved(("photo",))
        with mock.patch(
            "photo_session_workflow.paths._write_stream",
            side_effect=OSError("simulated failure"),
        ):
            with self.assertRaisesRegex(OSError, "simulated failure"):
                generate_review_package(
                    self.reader, self.writer,
                    export_relative_directory="export-app", resolutions=resolved,
                    destination_relative_path="review.zip", limits=self._limits(),
                    confirmation=self._confirmation(resolved),
                )
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_publication_failure_cleans_temporary_package(self) -> None:
        resolved = self._resolved(("photo",))
        with mock.patch(
            "photo_session_workflow.paths.os.link",
            side_effect=OSError("simulated publication failure"),
        ):
            with self.assertRaisesRegex(OSError, "simulated publication failure"):
                generate_review_package(
                    self.reader, self.writer,
                    export_relative_directory="export-app", resolutions=resolved,
                    destination_relative_path="review.zip", limits=self._limits(),
                    confirmation=self._confirmation(resolved),
                )
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_sources_unchanged_and_workspace_contains_only_final_package(self) -> None:
        resolved = self._resolved(("photo",))
        before = {
            path.relative_to(self.session).as_posix(): hashlib.sha256(path.read_bytes()).digest()
            for path in self.session.rglob("*") if path.is_file()
        }
        generate_review_package(
            self.reader, self.writer,
            export_relative_directory="export-app", resolutions=resolved,
            destination_relative_path="review.zip", limits=self._limits(),
            confirmation=self._confirmation(resolved),
        )
        after = {
            path.relative_to(self.session).as_posix(): hashlib.sha256(path.read_bytes()).digest()
            for path in self.session.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertEqual([path.name for path in self.workspace.iterdir()], ["review.zip"])
        with ZipFile(self.workspace / "review.zip") as archive:
            names = archive.namelist()
            self.assertFalse(any(name.casefold().endswith((".nef", ".xmp", ".acr")) for name in names))

    def test_models_are_immutable(self) -> None:
        entry = LightroomExportEntry(
            "export-app/photo.jpg", "photo.jpg", ".jpg", ".jpg", 1,
            "2026-01-01T00:00:00.000000000Z",
        )
        with self.assertRaises(FrozenInstanceError):
            entry.size_bytes = 2  # type: ignore[misc]
        limits = self._limits()
        with self.assertRaises(FrozenInstanceError):
            limits.max_jpg_bytes = 2  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
