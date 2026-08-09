from __future__ import annotations

import hashlib
import io
import re
import tempfile
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from unittest.mock import patch

from photo_session_workflow.inventory import InventoryEntry
from photo_session_workflow.paths import RootBoundaries, SessionReader


class InventoryTests(unittest.TestCase):
    def _roots(self, parent: Path) -> tuple[Path, Path, Path]:
        session = parent / "session"
        workspace = parent / "workspace"
        repository = parent / "repository"
        for root in (session, workspace, repository):
            root.mkdir()
        return session, workspace, repository

    def _reader(self, parent: Path) -> tuple[SessionReader, Path, Path]:
        session, workspace, repository = self._roots(parent)
        boundaries = RootBoundaries.create(
            session_root=session,
            workspace_root=workspace,
            repository_root=repository,
        )
        return SessionReader(boundaries), session, workspace

    def _snapshot(self, root: Path) -> tuple[tuple[str, int, int, str], ...]:
        snapshot = []
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            metadata = path.stat(follow_symlinks=False)
            digest = "directory"
            if path.is_file() and not path.is_symlink():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot.append(
                (
                    path.relative_to(root).as_posix(),
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    digest,
                )
            )
        return tuple(snapshot)

    def test_empty_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, _, _ = self._reader(Path(temporary))
            result = reader.inventory()
            self.assertEqual(result.entries, ())
            self.assertEqual(result.ignored, ())
            self.assertEqual(result.rejected, ())
            self.assertEqual(result.photo_count, 0)

    def test_recognized_extensions_are_case_insensitive_and_classified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            names = ("one.NEF", "two.jpg", "three.JpEg", "four.XMP", "five.aCr")
            for name in names:
                (session / name).write_bytes(b"synthetic marker")
            result = reader.inventory()
            by_name = {entry.filename: entry for entry in result.entries}
            self.assertEqual(set(by_name), set(names))
            self.assertEqual(by_name["one.NEF"].original_extension, ".NEF")
            self.assertEqual(by_name["one.NEF"].normalized_extension, ".nef")
            self.assertEqual(by_name["one.NEF"].category, "raw")
            self.assertEqual(by_name["one.NEF"].size_bytes, len(b"synthetic marker"))
            self.assertEqual(by_name["one.NEF"].status, "admitted")
            self.assertEqual(by_name["one.NEF"].warnings, ())
            self.assertEqual(
                [field.name for field in fields(by_name["one.NEF"])],
                [
                    "relative_path",
                    "filename",
                    "original_extension",
                    "normalized_extension",
                    "category",
                    "size_bytes",
                    "modified_at",
                    "status",
                    "warnings",
                ],
            )
            self.assertTrue(
                re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z",
                    by_name["one.NEF"].modified_at,
                )
            )
            self.assertEqual(by_name["two.jpg"].category, "image")
            self.assertEqual(by_name["four.XMP"].category, "sidecar")
            self.assertEqual(by_name["five.aCr"].category, "auxiliary")
            self.assertEqual((result.photo_count, result.sidecar_count, result.auxiliary_count), (3, 1, 1))

    def test_unsupported_regular_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            (session / "notes.txt").write_text("synthetic", encoding="utf-8")
            result = reader.inventory()
            self.assertEqual(result.entries, ())
            self.assertEqual(result.ignored[0].reason, "unsupported_extension")
            self.assertEqual(result.ignored[0].status, "ignored")

    def test_lightroom_data_is_rejected_without_stat_or_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            (session / "catalog.LRCAT").write_bytes(b"must not open")
            for directory_name in ("catalog.lrcat-data", "previews.LRDATA"):
                directory = session / directory_name
                directory.mkdir()
                (directory / "hidden.NEF").write_bytes(b"must not discover")

            from photo_session_workflow.inventory import _stat_entry as real_stat_entry

            def guarded_stat(entry):
                self.assertFalse(entry.name.casefold().endswith((".lrcat", ".lrcat-data", ".lrdata")))
                return real_stat_entry(entry)

            with patch("photo_session_workflow.inventory._stat_entry", side_effect=guarded_stat):
                result = reader.inventory()
            self.assertEqual(result.entries, ())
            self.assertEqual(len(result.rejected), 3)
            self.assertTrue(all(item.reason == "lightroom_data_prohibited" for item in result.rejected))

    def test_recursive_and_non_recursive_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            (session / "root.NEF").write_bytes(b"root")
            nested = session / "subfolder"
            nested.mkdir()
            (nested / "nested.JPG").write_bytes(b"nested")
            recursive = reader.inventory()
            shallow = reader.inventory(recursive=False)
            self.assertEqual([item.relative_path for item in recursive.entries], ["root.NEF", "subfolder/nested.JPG"])
            self.assertEqual([item.relative_path for item in shallow.entries], ["root.NEF"])
            self.assertEqual(shallow.ignored[0].reason, "recursion_disabled")

    def test_unicode_spaces_and_original_case_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            folder = session / "Selección Ñ"
            folder.mkdir()
            (folder / "Cámara Única.JpG").write_bytes(b"synthetic")
            entry = reader.inventory().entries[0]
            self.assertEqual(entry.relative_path, "Selección Ñ/Cámara Única.JpG")
            self.assertEqual(entry.filename, "Cámara Única.JpG")

    def test_order_is_deterministic_casefold_then_original_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            for name in ("z.NEF", "B.jpg", "a.XMP", "c.ACR"):
                (session / name).write_bytes(b"synthetic")
            first = reader.inventory()
            second = reader.inventory()
            expected = ["a.XMP", "B.jpg", "c.ACR", "z.NEF"]
            self.assertEqual([item.relative_path for item in first.entries], expected)
            self.assertEqual(first, second)

    def test_results_and_errors_do_not_expose_absolute_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            (session / "visible.NEF").write_bytes(b"synthetic")
            (session / "failure.JPG").write_bytes(b"synthetic")

            from photo_session_workflow.inventory import _stat_entry as real_stat_entry

            def failing_stat(entry):
                if entry.name == "failure.JPG":
                    raise PermissionError(str(session / entry.name))
                return real_stat_entry(entry)

            with patch("photo_session_workflow.inventory._stat_entry", side_effect=failing_stat):
                result = reader.inventory()
            self.assertNotIn(str(session), repr(result))
            self.assertEqual(result.rejected[0].relative_path, "failure.JPG")
            self.assertEqual(result.rejected[0].reason, "metadata_unavailable")

    def test_file_metadata_error_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            (session / "good.NEF").write_bytes(b"good")
            (session / "vanished.JPG").write_bytes(b"gone")

            from photo_session_workflow.inventory import _stat_entry as real_stat_entry

            def disappearing_stat(entry):
                if entry.name == "vanished.JPG":
                    raise FileNotFoundError("simulated disappearance")
                return real_stat_entry(entry)

            with patch("photo_session_workflow.inventory._stat_entry", side_effect=disappearing_stat):
                result = reader.inventory()
            self.assertEqual([item.filename for item in result.entries], ["good.NEF"])
            self.assertEqual(result.rejected[0].reason, "metadata_unavailable")

    def test_file_symlink_is_rejected_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            outside = Path(temporary) / "outside.NEF"
            outside.write_bytes(b"outside")
            link = session / "linked.NEF"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")
            result = reader.inventory()
            self.assertEqual(result.entries, ())
            self.assertEqual(result.rejected[0].reason, "link_or_reparse_point")

    def test_directory_symlink_is_not_traversed_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            outside = Path(temporary) / "outside"
            outside.mkdir()
            (outside / "hidden.NEF").write_bytes(b"outside")
            link = session / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")
            result = reader.inventory()
            self.assertEqual(result.entries, ())
            self.assertEqual(result.rejected[0].relative_path, "linked")

    def test_reparse_point_is_rejected_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            (session / "blocked.NEF").write_bytes(b"unique-size-17!!!")
            with patch("photo_session_workflow.inventory._is_reparse_stat", return_value=True):
                result = reader.inventory()
            self.assertEqual(result.entries, ())
            self.assertEqual(result.rejected[0].reason, "link_or_reparse_point")

    def test_two_hundred_photos_complete_without_volume_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            for index in range(200):
                (session / f"synthetic-{index:03d}.NEF").write_bytes(b"not a decodable raw")
            result = reader.inventory()
            self.assertEqual(result.photo_count, 200)
            self.assertEqual(len(result.entries), 200)
            self.assertEqual(result.warnings, ())

    def test_more_than_target_warns_and_keeps_complete_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            for index in range(201):
                extension = ".JPG" if index % 2 else ".NEF"
                (session / f"synthetic-{index:03d}{extension}").write_bytes(b"simulated")
            (session / "rating.XMP").write_bytes(b"not interpreted")
            result = reader.inventory()
            self.assertEqual(result.photo_count, 201)
            self.assertEqual(result.sidecar_count, 1)
            self.assertEqual(len(result.entries), 202)
            self.assertEqual(result.warnings, ("photo_volume_exceeds_target",))

    def test_inventory_does_not_mutate_session_or_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, workspace = self._reader(Path(temporary))
            folder = session / "source"
            folder.mkdir()
            (folder / "one.NEF").write_bytes(b"synthetic raw marker")
            (folder / "one.XMP").write_bytes(b"synthetic xmp marker")
            before = self._snapshot(session)
            reader.inventory()
            after = self._snapshot(session)
            self.assertEqual(before, after)
            self.assertEqual(list(workspace.iterdir()), [])

    def test_inventory_never_opens_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, _ = self._reader(Path(temporary))
            for name in ("one.NEF", "two.JPG", "three.XMP", "four.ACR"):
                (session / name).write_bytes(b"must remain unopened")
            with patch("builtins.open", side_effect=AssertionError("content opened")), patch.object(
                io, "open", side_effect=AssertionError("content opened")
            ):
                result = reader.inventory()
            self.assertEqual(len(result.entries), 4)

    def test_models_are_immutable(self) -> None:
        entry = InventoryEntry(
            relative_path="one.NEF",
            filename="one.NEF",
            original_extension=".NEF",
            normalized_extension=".nef",
            category="raw",
            size_bytes=1,
            modified_at="2026-01-01T00:00:00.000000000Z",
            status="admitted",
            warnings=(),
        )
        with self.assertRaises(FrozenInstanceError):
            entry.status = "changed"  # type: ignore[misc]

    def test_invalid_inventory_options_are_rejected_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reader, session, workspace = self._reader(Path(temporary))
            with self.assertRaisesRegex(TypeError, "recursive"):
                reader.inventory(recursive=1)  # type: ignore[arg-type]
            with self.assertRaisesRegex(ValueError, "positive"):
                reader.inventory(target_photo_count=0)
            self.assertEqual(list(session.iterdir()), [])
            self.assertEqual(list(workspace.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
