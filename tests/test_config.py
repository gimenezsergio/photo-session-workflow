from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from photo_session_workflow.config import ConfigurationError, load_config
from photo_session_workflow.exif import ExifToolSettings


class ConfigTests(unittest.TestCase):
    def _roots(self, parent: Path) -> tuple[Path, Path, Path]:
        session = parent / "session with spaces"
        workspace = parent / "private workspace"
        repository = parent / "repository"
        for path in (session, workspace, repository):
            path.mkdir()
        return session, workspace, repository

    def _write_config(
        self, parent: Path, session: object, workspace: object, repository: object
    ) -> Path:
        path = parent / "config.local.json"
        path.write_text(
            json.dumps(
                {
                    "paths": {
                        "session_root": os.fspath(session) if isinstance(session, os.PathLike) else session,
                        "workspace_root": os.fspath(workspace)
                        if isinstance(workspace, os.PathLike)
                        else workspace,
                        "repository_root": os.fspath(repository)
                        if isinstance(repository, os.PathLike)
                        else repository,
                    }
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_valid_configuration_and_paths_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._roots(parent)
            config = load_config(self._write_config(parent, session, workspace, repository))
            self.assertEqual(config.session_root, session.resolve())
            self.assertEqual(config.workspace_root, workspace.resolve())
            self.assertEqual(config.repository_root, repository.resolve())

    def test_empty_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._roots(parent)
            with self.assertRaisesRegex(ConfigurationError, "must not be empty"):
                load_config(self._write_config(parent, "", workspace, repository))

    def test_relative_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            _, workspace, repository = self._roots(parent)
            with self.assertRaisesRegex(ConfigurationError, "must be absolute"):
                load_config(self._write_config(parent, "relative/session", workspace, repository))

    def test_missing_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            _, workspace, repository = self._roots(parent)
            missing = parent / "does not exist"
            with self.assertRaisesRegex(ConfigurationError, "existing directory"):
                load_config(self._write_config(parent, missing, workspace, repository))

    def test_regular_file_cannot_be_a_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            _, workspace, repository = self._roots(parent)
            file_path = parent / "not-a-directory"
            file_path.write_text("synthetic", encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "must reference a directory"):
                load_config(self._write_config(parent, file_path, workspace, repository))

    def test_invalid_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.local.json"
            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "valid UTF-8 JSON"):
                load_config(path)

    def test_exiftool_configuration_is_loaded_without_free_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._roots(parent)
            executable = parent / "tools" / "exiftool.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"synthetic executable marker")
            config_path = self._write_config(parent, session, workspace, repository)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["exiftool"] = {
                "executable": os.fspath(executable),
                "timeout_seconds": 7,
                "max_output_bytes": 2048,
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_config(config_path)
            self.assertIsInstance(config.exiftool, ExifToolSettings)
            self.assertEqual(config.exiftool.timeout_seconds, 7)  # type: ignore[union-attr]
            self.assertEqual(config.exiftool.max_output_bytes, 2048)  # type: ignore[union-attr]

    def test_exiftool_free_arguments_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._roots(parent)
            executable = parent / "exiftool.exe"
            executable.write_bytes(b"synthetic executable marker")
            config_path = self._write_config(parent, session, workspace, repository)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["exiftool"] = {
                "executable": os.fspath(executable),
                "timeout_seconds": 5,
                "arguments": ["-overwrite_original"],
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "unsupported keys"):
                load_config(config_path)

    def test_xmp_size_limit_is_loaded_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._roots(parent)
            config_path = self._write_config(parent, session, workspace, repository)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["xmp"] = {"max_bytes": 4096}
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(load_config(config_path).xmp_max_bytes, 4096)
            payload["xmp"] = {"max_bytes": 1}
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "between 64"):
                load_config(config_path)

    def test_lightroom_export_directory_and_package_limits_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._roots(parent)
            (session / "export-app").mkdir()
            config_path = self._write_config(parent, session, workspace, repository)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["lightroom_export_relative_directory"] = "export-app"
            payload["review_package"] = {
                "max_jpg_bytes": 1234,
                "max_package_bytes": 5678,
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_config(config_path)
            self.assertEqual(config.lightroom_export_relative_directory, "export-app")
            self.assertEqual(config.review_package_limits.max_jpg_bytes, 1234)
            self.assertEqual(config.review_package_limits.max_package_bytes, 5678)

    def test_invalid_lightroom_export_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._roots(parent)
            (session / "export-app").mkdir()
            for invalid in ("", ".", "../export-app", os.fspath(session / "export-app"), "missing"):
                with self.subTest(invalid=invalid):
                    config_path = self._write_config(parent, session, workspace, repository)
                    payload = json.loads(config_path.read_text(encoding="utf-8"))
                    payload["lightroom_export_relative_directory"] = invalid
                    config_path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(ConfigurationError):
                        load_config(config_path)

    def test_invalid_review_package_limits_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._roots(parent)
            config_path = self._write_config(parent, session, workspace, repository)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["review_package"] = {
                "max_jpg_bytes": 200,
                "max_package_bytes": 100,
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "must not be smaller"):
                load_config(config_path)

    @unittest.skipUnless(os.name == "nt", "Windows-specific path behavior")
    def test_windows_backslash_paths_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session, workspace, repository = self._roots(parent)
            config = load_config(
                self._write_config(
                    parent, str(session), str(workspace), str(repository)
                )
            )
            self.assertEqual(config.session_root, session.resolve())


if __name__ == "__main__":
    unittest.main()
