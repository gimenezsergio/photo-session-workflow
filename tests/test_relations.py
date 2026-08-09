from __future__ import annotations

import io
import tempfile
import unittest
from collections import Counter
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from unittest.mock import patch

from photo_session_workflow.inventory import (
    InventoryEntry,
    InventoryNotice,
    InventoryResult,
)
from photo_session_workflow.paths import RootBoundaries, SessionReader
from photo_session_workflow.relations import (
    AssetComponent,
    LogicalAsset,
    RelationInputError,
    relate_inventory,
)


class RelationTests(unittest.TestCase):
    def _entry(
        self,
        relative_path: str,
        *,
        modified_at: str = "2026-01-01T00:00:00.000000000Z",
    ) -> InventoryEntry:
        filename = relative_path.rsplit("/", 1)[-1]
        extension = Path(filename).suffix
        normalized = extension.casefold()
        categories = {
            ".nef": "raw",
            ".jpg": "image",
            ".jpeg": "image",
            ".xmp": "sidecar",
            ".acr": "auxiliary",
        }
        return InventoryEntry(
            relative_path=relative_path,
            filename=filename,
            original_extension=extension,
            normalized_extension=normalized,
            category=categories[normalized],
            size_bytes=10,
            modified_at=modified_at,
            status="admitted",
            warnings=(),
        )

    def _inventory(
        self,
        *paths: str,
        ignored: tuple[InventoryNotice, ...] = (),
        rejected: tuple[InventoryNotice, ...] = (),
    ) -> InventoryResult:
        entries = tuple(self._entry(path) for path in paths)
        return InventoryResult(
            entries=entries,
            ignored=ignored,
            rejected=rejected,
            photo_count=sum(item.category in {"raw", "image"} for item in entries),
            sidecar_count=sum(item.category == "sidecar" for item in entries),
            auxiliary_count=sum(item.category == "auxiliary" for item in entries),
            warnings=(),
        )

    def test_complete_four_component_asset(self) -> None:
        result = relate_inventory(
            self._inventory("DSC_9497.NEF", "DSC_9497.xmp", "DSC_9497.acr", "DSC_9497.jpg")
        )
        self.assertEqual(result.total_assets, 1)
        asset = result.assets[0]
        self.assertEqual(asset.status, "complete")
        self.assertEqual([component.role for component in asset.components], ["raw", "image", "sidecar", "auxiliary"])
        self.assertEqual(asset.warnings, ())

    def test_nef_without_xmp_is_complete_with_warning(self) -> None:
        asset = relate_inventory(self._inventory("foto.NEF")).assets[0]
        self.assertEqual(asset.status, "complete")
        self.assertIn("xmp_missing", asset.warnings)
        self.assertIn("image_missing", asset.warnings)

    def test_jpg_without_raw_is_complete_with_warning(self) -> None:
        asset = relate_inventory(self._inventory("foto.JPG")).assets[0]
        self.assertEqual(asset.status, "complete")
        self.assertIn("raw_missing", asset.warnings)

    def test_orphan_xmp_is_incomplete(self) -> None:
        result = relate_inventory(self._inventory("foto.xmp"))
        self.assertEqual(result.assets[0].status, "incomplete")
        self.assertIn("photographic_file_missing", result.assets[0].warnings)

    def test_orphan_acr_is_incomplete(self) -> None:
        result = relate_inventory(self._inventory("foto.acr"))
        self.assertEqual(result.assets[0].status, "incomplete")
        self.assertIn("photographic_file_missing", result.assets[0].warnings)
        self.assertIn("xmp_missing", result.assets[0].warnings)

    def test_same_base_in_different_directories_stays_separate(self) -> None:
        result = relate_inventory(self._inventory("one/foto.NEF", "two/foto.xmp"))
        self.assertEqual(result.total_assets, 2)
        self.assertEqual([asset.relative_directory for asset in result.assets], ["one", "two"])

    def test_extension_case_does_not_prevent_association(self) -> None:
        asset = relate_inventory(self._inventory("foto.NEF", "foto.XMP", "foto.JpEg")).assets[0]
        self.assertEqual(asset.status, "complete")
        self.assertEqual(asset.original_base_names, ("foto",))

    def test_base_name_case_collision_is_ambiguous(self) -> None:
        asset = relate_inventory(self._inventory("Foto.NEF", "foto.xmp")).assets[0]
        self.assertEqual(asset.status, "ambiguous")
        self.assertEqual(asset.original_base_names, ("Foto", "foto"))
        self.assertIn("base_name_case_collision", asset.warnings)

    def test_multiple_jpg_and_jpeg_candidates_are_ambiguous(self) -> None:
        asset = relate_inventory(self._inventory("foto.NEF", "foto.jpg", "foto.jpeg")).assets[0]
        self.assertEqual(asset.status, "ambiguous")
        self.assertIn("multiple_image_candidates", asset.warnings)
        self.assertEqual(len(asset.components_for("image")), 2)

    def test_multiple_xmp_candidates_are_ambiguous(self) -> None:
        asset = relate_inventory(self._inventory("foto.NEF", "foto.xmp", "foto.XMP")).assets[0]
        self.assertEqual(asset.status, "ambiguous")
        self.assertIn("multiple_sidecar_candidates", asset.warnings)

    def test_multiple_acr_candidates_are_ambiguous(self) -> None:
        asset = relate_inventory(self._inventory("foto.NEF", "foto.acr", "foto.ACR")).assets[0]
        self.assertEqual(asset.status, "ambiguous")
        self.assertIn("multiple_auxiliary_candidates", asset.warnings)

    def test_multiple_raw_candidates_are_ambiguous(self) -> None:
        asset = relate_inventory(self._inventory("foto.NEF", "foto.nef")).assets[0]
        self.assertEqual(asset.status, "ambiguous")
        self.assertIn("multiple_raw_candidates", asset.warnings)

    def test_spaces_unicode_and_original_provenance_are_preserved(self) -> None:
        result = relate_inventory(self._inventory("Selección Ñ/Cámara Única.NEF", "Selección Ñ/Cámara Única.xmp"))
        asset = result.assets[0]
        self.assertEqual(asset.relative_directory, "Selección Ñ")
        self.assertEqual(asset.original_base_names, ("Cámara Única",))
        self.assertEqual(asset.components[0].source_entry.relative_path, "Selección Ñ/Cámara Única.NEF")

    def test_only_last_extension_is_removed(self) -> None:
        asset = relate_inventory(self._inventory("session.v1/foto.final.NEF", "session.v1/foto.final.xmp")).assets[0]
        self.assertEqual(asset.normalized_base_name, "foto.final")
        self.assertEqual(asset.relative_directory, "session.v1")

    def test_export_suffixes_are_not_guessed_as_equivalent(self) -> None:
        result = relate_inventory(self._inventory("DSC_9497.NEF", "DSC_9497-Edit.jpg", "DSC_9497_v2.jpg"))
        self.assertEqual(result.total_assets, 3)
        self.assertEqual(
            [asset.normalized_base_name for asset in result.assets],
            ["dsc_9497", "dsc_9497-edit", "dsc_9497_v2"],
        )

    def test_order_and_identifier_are_deterministic_and_ignore_timestamps(self) -> None:
        source = self._inventory("z.NEF", "A.jpg", "b.XMP")
        first = relate_inventory(source)
        reordered = InventoryResult(
            entries=tuple(reversed(source.entries)),
            ignored=(),
            rejected=(),
            photo_count=2,
            sidecar_count=1,
            auxiliary_count=0,
            warnings=(),
        )
        self.assertEqual(first, relate_inventory(reordered))
        second_inventory = InventoryResult(
            entries=tuple(
                reversed(
                    tuple(
                        self._entry(path, modified_at="2030-12-31T23:59:59.000000000Z")
                        for path in ("z.NEF", "A.jpg", "b.XMP")
                    )
                )
            ),
            ignored=(),
            rejected=(),
            photo_count=2,
            sidecar_count=1,
            auxiliary_count=0,
            warnings=(),
        )
        second = relate_inventory(second_inventory)
        self.assertEqual([asset.normalized_base_name for asset in first.assets], ["a", "b", "z"])
        self.assertEqual(
            [asset.asset_id for asset in first.assets],
            [asset.asset_id for asset in second.assets],
        )
        self.assertTrue(all(not asset.asset_id.startswith(("/", "C:")) for asset in first.assets))

    def test_result_reports_each_status_count(self) -> None:
        result = relate_inventory(
            self._inventory(
                "complete.NEF",
                "orphan.xmp",
                "duplicate.jpg",
                "duplicate.jpeg",
            )
        )
        self.assertEqual(result.total_assets, 3)
        self.assertEqual(result.complete_count, 1)
        self.assertEqual(result.incomplete_count, 1)
        self.assertEqual(result.ambiguous_count, 1)

    def test_models_are_immutable_and_contain_no_path_values(self) -> None:
        result = relate_inventory(self._inventory("folder/foto.NEF"))
        asset = result.assets[0]
        with self.assertRaises(FrozenInstanceError):
            asset.status = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            result.total_assets = 99  # type: ignore[misc]
        self.assertFalse(any(field.type is Path for field in fields(LogicalAsset)))
        self.assertFalse(any(field.type is Path for field in fields(AssetComponent)))
        self.assertFalse(any(isinstance(value, Path) for value in (
            asset.asset_id,
            asset.relative_directory,
            asset.normalized_base_name,
        )))

    def test_every_admitted_entry_is_represented_exactly_once(self) -> None:
        inventory = self._inventory("a.NEF", "a.xmp", "b.jpg", "c.acr")
        result = relate_inventory(inventory)
        represented = [component.source_entry.relative_path for asset in result.assets for component in asset.components]
        self.assertEqual(Counter(represented), Counter(entry.relative_path for entry in inventory.entries))
        self.assertEqual(result.represented_entry_count, 4)
        self.assertTrue(result.coverage_complete)

    def test_absolute_paths_are_rejected_without_echoing_input(self) -> None:
        entry = self._entry("C:/private/foto.NEF")
        inventory = InventoryResult((entry,), (), (), 1, 0, 0, ())
        with self.assertRaises(RelationInputError) as captured:
            relate_inventory(inventory)
        self.assertNotIn("C:/private", str(captured.exception))

    def test_ignored_and_rejected_inventory_elements_do_not_participate(self) -> None:
        ignored = InventoryNotice("ignored.txt", "ignored.txt", "ignored", "unsupported_extension")
        rejected = InventoryNotice("catalog.lrcat", "catalog.lrcat", "rejected", "lightroom_data_prohibited")
        result = relate_inventory(self._inventory("foto.NEF", ignored=(ignored,), rejected=(rejected,)))
        self.assertEqual(result.total_assets, 1)
        self.assertEqual(result.admitted_entry_count, 1)

    def test_relations_do_not_open_content_or_mutate_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session = parent / "session"
            workspace = parent / "workspace"
            repository = parent / "repository"
            for root in (session, workspace, repository):
                root.mkdir()
            (session / "foto.NEF").write_bytes(b"synthetic raw marker")
            (session / "foto.XMP").write_bytes(b"synthetic xmp marker")
            reader = SessionReader(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            inventory = reader.inventory()
            before = tuple((path.name, path.stat().st_mtime_ns, path.read_bytes()) for path in sorted(session.iterdir()))
            with patch("builtins.open", side_effect=AssertionError("content opened")), patch.object(
                io, "open", side_effect=AssertionError("content opened")
            ):
                result = relate_inventory(inventory)
            after = tuple((path.name, path.stat().st_mtime_ns, path.read_bytes()) for path in sorted(session.iterdir()))
            self.assertEqual(before, after)
            self.assertEqual(list(workspace.iterdir()), [])
            self.assertEqual(result.total_assets, 1)


if __name__ == "__main__":
    unittest.main()
