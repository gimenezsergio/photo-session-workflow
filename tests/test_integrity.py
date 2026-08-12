from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest import mock

from photo_session_workflow.integrity import (
    SourceIntegrityError,
    capture_source_integrity,
    check_repository_hygiene,
    compare_source_integrity,
    require_unchanged_sources,
)
from photo_session_workflow.paths import (
    PathBoundaryError,
    RootBoundaries,
    SessionReader,
    WorkspaceWriter,
)


class SourceIntegrityTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _sources(self) -> None:
        (self.session / "DSC_0001.NEF").write_bytes(b"synthetic raw marker")
        (self.session / "DSC_0001.xmp").write_text(
            "<x:xmpmeta xmlns:x='adobe:ns:meta/'>synthetic</x:xmpmeta>",
            encoding="utf-8",
        )
        (self.session / "DSC_0001.acr").write_text("synthetic acr", encoding="utf-8")
        (self.session / "DSC_0001.JPG").write_bytes(b"synthetic camera jpeg")
        (self.exports / "DSC_0001.jpg").write_bytes(b"synthetic export jpeg")

    def _capture(self):
        inventory = self.reader.inventory(recursive=False)
        exports = self.reader.inventory_lightroom_exports("export-app")
        return capture_source_integrity(
            self.reader,
            inventory,
            lightroom_exports=exports,
            chunk_size=4_096,
        )

    @staticmethod
    def _tree(path: Path) -> tuple[tuple[str, int, str], ...]:
        return tuple(
            sorted(
                (
                    item.relative_to(path).as_posix(),
                    item.stat().st_size,
                    hashlib.sha256(item.read_bytes()).hexdigest(),
                )
                for item in path.rglob("*")
                if item.is_file()
            )
        )

    def test_snapshot_covers_all_admitted_session_and_export_sources(self) -> None:
        self._sources()
        snapshot = self._capture()
        self.assertEqual(snapshot.source_count, 5)
        self.assertEqual(
            tuple(entry.relative_path for entry in snapshot.entries),
            (
                "DSC_0001.acr",
                "DSC_0001.JPG",
                "DSC_0001.NEF",
                "DSC_0001.xmp",
                "export-app/DSC_0001.jpg",
            ),
        )
        self.assertEqual(snapshot.entries[-1].source_kind, "lightroom_export")
        self.assertTrue(all(not Path(item.relative_path).is_absolute() for item in snapshot.entries))

    def test_repeated_snapshot_is_deterministic_and_unchanged(self) -> None:
        self._sources()
        before = self._capture()
        after = self._capture()
        self.assertEqual(before, after)
        report = compare_source_integrity(before, after)
        self.assertTrue(report.unchanged)
        self.assertEqual(report.added, ())
        self.assertEqual(report.missing, ())
        self.assertEqual(report.changed, ())
        require_unchanged_sources(report)

    def test_content_change_is_detected_even_if_size_and_mtime_are_restored(self) -> None:
        self._sources()
        source = self.session / "DSC_0001.NEF"
        before = self._capture()
        metadata = source.stat()
        source.write_bytes(b"synthetic RAW marker")
        self.assertEqual(source.stat().st_size, metadata.st_size)
        os.utime(source, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        after = self._capture()
        report = compare_source_integrity(before, after)
        self.assertFalse(report.unchanged)
        self.assertEqual(
            tuple(item.relative_path for item in report.changed),
            ("DSC_0001.NEF",),
        )
        with self.assertRaisesRegex(SourceIntegrityError, "failed"):
            require_unchanged_sources(report)

    def test_added_and_missing_sources_are_reported_without_absolute_paths(self) -> None:
        self._sources()
        before = self._capture()
        (self.session / "DSC_0001.acr").unlink()
        (self.session / "DSC_0002.NEF").write_bytes(b"new synthetic marker")
        after = self._capture()
        report = compare_source_integrity(before, after)
        self.assertEqual(
            tuple(item.relative_path for item in report.added),
            ("DSC_0002.NEF",),
        )
        self.assertEqual(
            tuple(item.relative_path for item in report.missing),
            ("DSC_0001.acr",),
        )
        self.assertNotIn(str(self.session), repr(report))

    def test_lightroom_catalogs_and_ignored_files_are_never_opened(self) -> None:
        self._sources()
        (self.session / "catalog.lrcat").write_bytes(b"forbidden catalog")
        catalog_data = self.session / "catalog.lrdata"
        catalog_data.mkdir()
        (catalog_data / "preview.jpg").write_bytes(b"forbidden preview")
        (self.session / "notes.txt").write_text("ignored", encoding="utf-8")
        inventory = self.reader.inventory(recursive=False)
        self.assertTrue(
            any(item.relative_path == "catalog.lrcat" for item in inventory.rejected)
        )
        opened: list[str] = []
        original = SessionReader.fingerprint_file

        def record(reader, relative_path, *, chunk_size=1_048_576):
            opened.append(relative_path)
            return original(reader, relative_path, chunk_size=chunk_size)

        with mock.patch.object(
            SessionReader,
            "fingerprint_file",
            autospec=True,
            side_effect=record,
        ):
            capture_source_integrity(self.reader, inventory)
        self.assertNotIn("catalog.lrcat", opened)
        self.assertNotIn("notes.txt", opened)
        with self.assertRaisesRegex(PathBoundaryError, "prohibited"):
            self.reader.open_binary("catalog.lrcat")
        with self.assertRaisesRegex(PathBoundaryError, "prohibited"):
            self.reader.open_binary("catalog.lrdata/preview.jpg")

    def test_source_disappearing_after_inventory_is_sanitized(self) -> None:
        self._sources()
        inventory = self.reader.inventory(recursive=False)
        (self.session / "DSC_0001.xmp").unlink()
        with self.assertRaisesRegex(SourceIntegrityError, "fingerprinted") as caught:
            capture_source_integrity(self.reader, inventory)
        self.assertNotIn(str(self.session), str(caught.exception))

    def test_recursive_inventory_plus_export_inventory_rejects_duplicates(self) -> None:
        self._sources()
        inventory = self.reader.inventory(recursive=True)
        exports = self.reader.inventory_lightroom_exports("export-app")
        with self.assertRaisesRegex(SourceIntegrityError, "duplicate"):
            capture_source_integrity(
                self.reader,
                inventory,
                lightroom_exports=exports,
            )

    def test_capture_does_not_write_and_workspace_writes_do_not_change_sources(self) -> None:
        self._sources()
        source_before = self._tree(self.session)
        repository_before = self._tree(self.repository)
        snapshot_before = self._capture()
        self.writer.ensure_directory("audit")
        self.writer.write_bytes("audit/synthetic.txt", b"workspace-only")
        snapshot_after = self._capture()
        self.assertTrue(compare_source_integrity(snapshot_before, snapshot_after).unchanged)
        self.assertEqual(self._tree(self.session), source_before)
        self.assertEqual(self._tree(self.repository), repository_before)
        self.assertEqual((self.workspace / "audit/synthetic.txt").read_bytes(), b"workspace-only")

    def test_invalid_snapshot_and_input_are_rejected(self) -> None:
        self._sources()
        snapshot = self._capture()
        with self.assertRaisesRegex(SourceIntegrityError, "snapshot"):
            compare_source_integrity(
                replace(snapshot, snapshot_sha256="0" * 64),
                snapshot,
            )
        with self.assertRaises(SourceIntegrityError):
            capture_source_integrity(self.reader, object())  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.reader.fingerprint_file("DSC_0001.NEF", chunk_size=1)

    def test_models_are_immutable(self) -> None:
        self._sources()
        snapshot = self._capture()
        with self.assertRaises(FrozenInstanceError):
            snapshot.source_count = 0  # type: ignore[misc]

    def test_repository_hygiene_detects_private_tracked_material(self) -> None:
        clean = check_repository_hygiene(
            ("README.md", "photo_session_workflow/integrity.py", "config.example.json")
        )
        self.assertTrue(clean.clean)
        prohibited = check_repository_hygiene(
            (
                "session/image.NEF",
                "exports/review.JPG",
                "private/config.local.json",
                "state/workflow.sqlite3",
                "catalog/catalog.lrcat-data",
                "package/review.zip",
            )
        )
        self.assertFalse(prohibited.clean)
        self.assertEqual(prohibited.tracked_count, 6)
        self.assertEqual(len(prohibited.prohibited_paths), 6)
        self.assertTrue(
            all(not Path(path).is_absolute() for path in prohibited.prohibited_paths)
        )


if __name__ == "__main__":
    unittest.main()
