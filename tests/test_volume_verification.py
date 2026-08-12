from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from photo_session_workflow.confirmed_review_package import (
    ConfirmedReviewPackageLimits,
)
from photo_session_workflow.contact_sheet import ContactSheetSettings
from photo_session_workflow.paths import RootBoundaries, SessionReader, WorkspaceWriter
from photo_session_workflow.proxies import ProxySettings
from photo_session_workflow.selection_confirmation import SelectionConfirmationError
from photo_session_workflow.volume_verification import (
    VolumeVerificationError,
    run_volume_verification,
)


def _xmp(rating: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"
 xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:xmp="http://ns.adobe.com/xap/1.0/">
 <rdf:RDF><rdf:Description xmp:Rating="{rating}" /></rdf:RDF>
</x:xmpmeta>
"""


class VolumeVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        parent = Path(self.temporary.name)
        self.session = parent / "session"
        self.workspace = parent / "workspace"
        self.repository = parent / "repository"
        self.exports = self.session / "export-app"
        for path in (self.session, self.workspace, self.repository, self.exports):
            path.mkdir()
        boundaries = RootBoundaries.create(
            session_root=self.session,
            workspace_root=self.workspace,
            repository_root=self.repository,
        )
        self.reader = SessionReader(boundaries)
        self.writer = WorkspaceWriter(boundaries)
        self.proxy_settings = ProxySettings.create(
            long_edge_px=64,
            jpeg_quality=80,
            max_source_bytes=100_000,
            max_source_pixels=1_000_000,
        )
        self.contact_settings = ContactSheetSettings.create(
            columns=4,
            cell_width_px=128,
            thumbnail_height_px=96,
            label_height_px=32,
            padding_px=4,
            jpeg_quality=80,
            max_output_pixels=2_000_000,
            max_proxy_bytes=100_000,
        )
        self.package_limits = ConfirmedReviewPackageLimits.create(
            max_proxy_bytes=100_000,
            max_contact_sheet_bytes=500_000,
            max_package_bytes=5_000_000,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build_200_photo_session(self) -> tuple[str, ...]:
        selected_ids: list[str] = []
        for index in range(200):
            name = f"DSC_{index:04d}"
            (self.session / f"{name}.NEF").write_bytes(
                f"synthetic non-decodable Nikon D7000 NEF fixture {index}".encode()
            )
            rating = 5 if index % 10 == 0 else 0
            (self.session / f"{name}.xmp").write_text(
                _xmp(rating),
                encoding="utf-8",
            )
            if rating == 5:
                image = Image.new(
                    "RGB",
                    (80, 60),
                    ((index * 3) % 255, 80, 140),
                )
                image.save(
                    self.exports / f"{name}.jpg",
                    format="JPEG",
                    quality=88,
                )
                selected_ids.append(f"asset:.:{name.casefold()}")
        return tuple(selected_ids)

    def test_complete_200_photo_flow_is_reduced_measured_and_non_destructive(self) -> None:
        selected = self._build_200_photo_session()
        self.assertEqual(len(selected), 20)
        report = run_volume_verification(
            self.reader,
            self.writer,
            export_relative_directory="export-app",
            confirmed_asset_ids=selected[:12],
            proxy_settings=self.proxy_settings,
            contact_sheet_settings=self.contact_settings,
            package_limits=self.package_limits,
            target_photo_count=200,
            minimum_rating=1,
            explicit_confirmation=True,
        )
        self.assertTrue(report.completed)
        self.assertEqual(report.inventoried_photo_count, 200)
        self.assertEqual(report.sidecar_count, 200)
        self.assertEqual(report.logical_asset_count, 200)
        self.assertEqual(report.rated_selection_count, 20)
        self.assertEqual(report.proxy_count, 20)
        self.assertEqual(report.overview_contact_sheet_count, 20)
        self.assertEqual(report.confirmed_selection_count, 12)
        self.assertEqual(report.package_selected_count, 12)
        self.assertLess(report.proxy_count, report.inventoried_photo_count)
        self.assertLess(report.package_selected_count, report.inventoried_photo_count)
        self.assertEqual(report.source_count, 420)
        self.assertTrue(report.source_integrity.unchanged)
        self.assertGreater(report.source_bytes, 0)
        self.assertEqual(report.workspace_artifact_count_before, 0)
        self.assertGreater(report.workspace_artifact_count_after, 0)
        self.assertEqual(report.workspace_bytes_before, 0)
        self.assertGreater(report.workspace_bytes_after, 0)
        self.assertEqual(report.workspace_added_bytes, report.workspace_bytes_after)
        self.assertGreater(report.package_size_bytes, 0)
        self.assertEqual(len(report.package_sha256), 64)
        self.assertEqual(
            tuple(stage.stage for stage in report.stages),
            (
                "workspace_usage_before",
                "inventory",
                "relations",
                "rating_selection",
                "lightroom_exports",
                "source_integrity_before",
                "proxies",
                "overview_contact_sheet",
                "selection_confirmation",
                "confirmed_review_package",
                "source_integrity_after",
                "workspace_usage_after",
            ),
        )
        self.assertTrue(all(stage.elapsed_seconds >= 0 for stage in report.stages))
        self.assertGreaterEqual(report.total_elapsed_seconds, 0)
        self.assertIn(
            "performance_results_depend_on_local_hardware",
            report.warnings,
        )
        self.assertIn(
            "synthetic_results_do_not_validate_real_nef_decoding",
            report.warnings,
        )

        package_path = self.workspace / report.package_relative_path
        with ZipFile(package_path) as archive:
            self.assertEqual(len(archive.namelist()), 14)
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["selected_count"], 12)
        self.assertEqual(
            tuple(item["asset_id"] for item in manifest["assets"]),
            selected[:12],
        )
        self.assertTrue(
            all(item["preview_source"] == "lightroom_export" for item in manifest["assets"])
        )
        with self.assertRaises(FrozenInstanceError):
            report.completed = False  # type: ignore[misc]

    def test_confirmation_is_never_inferred(self) -> None:
        selected = self._build_200_photo_session()
        with self.assertRaises(SelectionConfirmationError):
            run_volume_verification(
                self.reader,
                self.writer,
                export_relative_directory="export-app",
                confirmed_asset_ids=selected[:12],
                proxy_settings=self.proxy_settings,
                contact_sheet_settings=self.contact_settings,
                package_limits=self.package_limits,
                package_relative_path="not-created.zip",
                explicit_confirmation=False,
            )
        self.assertFalse((self.workspace / "not-created.zip").exists())

    def test_invalid_target_and_confirmation_ids_are_rejected(self) -> None:
        for target in (0, 201, True):
            with self.subTest(target=target):
                with self.assertRaises(VolumeVerificationError):
                    run_volume_verification(
                        self.reader,
                        self.writer,
                        export_relative_directory="export-app",
                        confirmed_asset_ids=("asset:.:one",),
                        proxy_settings=self.proxy_settings,
                        contact_sheet_settings=self.contact_settings,
                        package_limits=self.package_limits,
                        target_photo_count=target,  # type: ignore[arg-type]
                        explicit_confirmation=True,
                    )
        with self.assertRaisesRegex(VolumeVerificationError, "unique"):
            run_volume_verification(
                self.reader,
                self.writer,
                export_relative_directory="export-app",
                confirmed_asset_ids=("asset:.:one", "asset:.:one"),
                proxy_settings=self.proxy_settings,
                contact_sheet_settings=self.contact_settings,
                package_limits=self.package_limits,
                explicit_confirmation=True,
            )
        for invalid_clock in (None, lambda: float("nan")):
            with self.subTest(clock=invalid_clock):
                with self.assertRaisesRegex(VolumeVerificationError, "clock"):
                    run_volume_verification(
                        self.reader,
                        self.writer,
                        export_relative_directory="export-app",
                        confirmed_asset_ids=("asset:.:one",),
                        proxy_settings=self.proxy_settings,
                        contact_sheet_settings=self.contact_settings,
                        package_limits=self.package_limits,
                        explicit_confirmation=True,
                        clock=invalid_clock,  # type: ignore[arg-type]
                    )

if __name__ == "__main__":
    unittest.main()
