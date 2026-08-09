from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photo_session_workflow.paths import (
    PathBoundaryError,
    RootBoundaries,
    SessionReader,
    WorkspaceWriter,
)


class BoundaryTests(unittest.TestCase):
    def _create_siblings(self, parent: Path) -> tuple[Path, Path, Path]:
        session = parent / "session"
        workspace = parent / "workspace"
        repository = parent / "repository"
        for path in (session, workspace, repository):
            path.mkdir()
        return session, workspace, repository

    def test_workspace_inside_session_is_rejected_after_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, _, repository = self._create_siblings(parent)
            workspace = session / "nested-workspace"
            workspace.mkdir()
            normalized_expression = session / "unused" / ".." / "nested-workspace"
            with self.assertRaisesRegex(PathBoundaryError, "workspace_root must not be inside"):
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=normalized_expression,
                    repository_root=repository,
                )

    def test_boundaries_cannot_be_constructed_without_validation(self) -> None:
        with self.assertRaises(TypeError):
            RootBoundaries(Path("session"), Path("workspace"), Path("repository"))

    def test_workspace_inside_repository_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, _, repository = self._create_siblings(parent)
            workspace = repository / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(PathBoundaryError, "workspace_root must not be inside"):
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )

    def test_session_and_workspace_equal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, _, repository = self._create_siblings(parent)
            with self.assertRaisesRegex(PathBoundaryError, "must not be equal"):
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=session,
                    repository_root=repository,
                )

    def test_session_inside_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            workspace = parent / "workspace"
            session = workspace / "session"
            repository = parent / "repository"
            session.mkdir(parents=True)
            repository.mkdir()
            with self.assertRaisesRegex(PathBoundaryError, "session_root must not be inside"):
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )

    def test_repository_inside_workspace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session = parent / "session"
            workspace = parent / "workspace"
            repository = workspace / "repository"
            session.mkdir()
            repository.mkdir(parents=True)
            with self.assertRaisesRegex(PathBoundaryError, "repository_root must not be inside"):
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )

    def test_detectable_symlink_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            link = parent / "workspace-link"
            try:
                link.symlink_to(workspace, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")
            with self.assertRaisesRegex(PathBoundaryError, "symbolic link"):
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=link,
                    repository_root=repository,
                )

    def test_detected_reparse_point_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            with patch(
                "photo_session_workflow.paths._is_reparse_point",
                side_effect=lambda path: path == workspace,
            ):
                with self.assertRaisesRegex(PathBoundaryError, "reparse point"):
                    RootBoundaries.create(
                        session_root=session,
                        workspace_root=workspace,
                        repository_root=repository,
                    )

    def test_session_reader_has_no_write_capability_and_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            source = session / "synthetic.txt"
            source.write_bytes(b"read-only synthetic source")
            before = hashlib.sha256(source.read_bytes()).digest()
            boundaries = RootBoundaries.create(
                session_root=session,
                workspace_root=workspace,
                repository_root=repository,
            )
            reader = SessionReader(boundaries)
            for forbidden_capability in (
                "write_bytes",
                "unlink",
                "delete",
                "move",
                "rename",
                "replace",
                "root",
            ):
                self.assertFalse(hasattr(reader, forbidden_capability))
            self.assertEqual(reader.read_bytes("synthetic.txt"), b"read-only synthetic source")
            after = hashlib.sha256(source.read_bytes()).digest()
            self.assertEqual(before, after)

    def test_session_reader_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            (workspace / "outside.txt").write_text("outside", encoding="utf-8")
            reader = SessionReader(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            with self.assertRaisesRegex(PathBoundaryError, "escapes session_root"):
                reader.read_bytes("../workspace/outside.txt")

    def test_workspace_writer_is_restricted_to_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            boundaries = RootBoundaries.create(
                session_root=session,
                workspace_root=workspace,
                repository_root=repository,
            )
            writer = WorkspaceWriter(boundaries)
            destination = writer.write_bytes("generated.txt", b"workspace only")
            self.assertEqual(destination.parent, workspace.resolve())
            with self.assertRaisesRegex(PathBoundaryError, "escapes workspace_root"):
                writer.write_bytes("../session/forbidden.txt", b"forbidden")
            self.assertFalse((session / "forbidden.txt").exists())

    def test_workspace_writer_rejects_absolute_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            with self.assertRaisesRegex(PathBoundaryError, "relative path"):
                writer.write_bytes(session / "forbidden.txt", b"forbidden")
            self.assertFalse((session / "forbidden.txt").exists())

    def test_workspace_writer_rechecks_detected_reparse_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            generated = workspace / "generated"
            generated.mkdir()
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            with patch(
                "photo_session_workflow.paths._is_reparse_point",
                side_effect=lambda path: path == generated,
            ):
                with self.assertRaisesRegex(PathBoundaryError, "reparse point"):
                    writer.write_bytes("generated/blocked.txt", b"blocked")
            self.assertFalse((generated / "blocked.txt").exists())

    def test_workspace_writer_rejects_symlink_parent_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            outside = parent / "outside"
            outside.mkdir()
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            link = workspace / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")
            with self.assertRaisesRegex(PathBoundaryError, "symbolic link"):
                writer.write_bytes("linked/blocked.txt", b"blocked")
            self.assertFalse((outside / "blocked.txt").exists())

    def test_workspace_writer_rejects_final_symlink_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            outside = parent / "outside.txt"
            outside.write_bytes(b"outside-original")
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            link = workspace / "linked.txt"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")
            with self.assertRaisesRegex(PathBoundaryError, "symbolic link"):
                writer.write_bytes("linked.txt", b"forbidden", overwrite=True)
            self.assertEqual(outside.read_bytes(), b"outside-original")

    def test_workspace_writer_rejects_final_reparse_point(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            destination = workspace / "existing.txt"
            destination.write_bytes(b"original")
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            with patch(
                "photo_session_workflow.paths._is_reparse_point",
                side_effect=lambda path: path == destination,
            ):
                with self.assertRaisesRegex(PathBoundaryError, "reparse point"):
                    writer.write_bytes("existing.txt", b"replacement", overwrite=True)
            self.assertEqual(destination.read_bytes(), b"original")

    def test_workspace_writer_atomically_replaces_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            destination = workspace / "existing.txt"
            destination.write_bytes(b"original")
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            result = writer.write_bytes(
                "existing.txt", memoryview(b"replacement"), overwrite=True
            )
            self.assertEqual(result, destination.resolve())
            self.assertEqual(destination.read_bytes(), b"replacement")
            self.assertEqual(list(workspace.glob(".existing.txt.*.tmp")), [])

    def test_workspace_writer_never_overwrites_without_permission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            destination = workspace / "existing.txt"
            destination.write_bytes(b"original")
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            with self.assertRaises(FileExistsError):
                writer.write_bytes("existing.txt", b"replacement")
            self.assertEqual(destination.read_bytes(), b"original")

    def test_workspace_writer_rejects_existing_directory_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            (workspace / "directory.txt").mkdir()
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            with self.assertRaisesRegex(PathBoundaryError, "regular file"):
                writer.write_bytes("directory.txt", b"replacement", overwrite=True)

    def test_invalid_content_does_not_create_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            with self.assertRaisesRegex(TypeError, "content must be bytes"):
                writer.write_bytes("invalid.txt", object())  # type: ignore[arg-type]
            self.assertFalse((workspace / "invalid.txt").exists())

    def test_overwrite_requires_existing_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            with self.assertRaisesRegex(PathBoundaryError, "requires an existing"):
                writer.write_bytes("missing.txt", b"replacement", overwrite=True)
            self.assertFalse((workspace / "missing.txt").exists())

    def test_failed_atomic_write_preserves_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            destination = workspace / "existing.txt"
            destination.write_bytes(b"original")
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )

            def fail_after_partial_write(stream: object, content: bytes) -> None:
                stream.write(content[:3])  # type: ignore[attr-defined]
                raise OSError("simulated write failure")

            with patch(
                "photo_session_workflow.paths._write_stream",
                side_effect=fail_after_partial_write,
            ):
                with self.assertRaisesRegex(OSError, "simulated write failure"):
                    writer.write_bytes("existing.txt", b"replacement", overwrite=True)
            self.assertEqual(destination.read_bytes(), b"original")

    def test_failed_atomic_write_removes_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._create_siblings(parent)
            destination = workspace / "existing.txt"
            destination.write_bytes(b"original")
            writer = WorkspaceWriter(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            with patch(
                "photo_session_workflow.paths._write_stream",
                side_effect=OSError("simulated write failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated write failure"):
                    writer.write_bytes("existing.txt", b"replacement", overwrite=True)
            self.assertEqual(list(workspace.glob(".existing.txt.*.tmp")), [])
            self.assertEqual(destination.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
