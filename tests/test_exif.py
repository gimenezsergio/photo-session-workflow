from __future__ import annotations

import json
import io
import os
import subprocess
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from photo_session_workflow.exif import (
    FIXED_READ_ARGUMENTS,
    REQUESTED_TAGS,
    ExifConfigurationError,
    ExifMetadata,
    ExifReadResult,
    ExifToolAdapter,
    ExifToolInfo,
    ExifToolSettings,
    ProcessResult,
    _default_runner,
    select_exif_source,
)
from photo_session_workflow.inventory import InventoryEntry, InventoryResult
from photo_session_workflow.paths import RootBoundaries, SessionReader
from photo_session_workflow.paths import PathBoundaryError
from photo_session_workflow.relations import LogicalAsset, relate_inventory


class RecordingRunner:
    def __init__(self, result: ProcessResult | BaseException) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], float, int]] = []

    def __call__(
        self, arguments: tuple[str, ...], timeout: float, max_capture_bytes: int
    ) -> ProcessResult:
        self.calls.append((arguments, timeout, max_capture_bytes))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class ExifTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        parent = Path(self.temporary.name)
        self.session = parent / "session"
        self.workspace = parent / "workspace"
        self.repository = parent / "repository"
        self.tools = parent / "tools"
        for root in (self.session, self.workspace, self.repository, self.tools):
            root.mkdir()
        self.executable = self.tools / "exiftool.exe"
        self.executable.write_bytes(b"synthetic executable marker")
        self.boundaries = RootBoundaries.create(
            session_root=self.session,
            workspace_root=self.workspace,
            repository_root=self.repository,
        )
        self.settings = ExifToolSettings.create(
            executable=self.executable,
            timeout_seconds=5,
            max_output_bytes=1024,
            boundaries=self.boundaries,
        )
        self.reader = SessionReader(self.boundaries)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _entry(self, relative_path: str) -> InventoryEntry:
        filename = relative_path.rsplit("/", 1)[-1]
        extension = Path(filename).suffix
        normalized = extension.casefold()
        category = {
            ".nef": "raw",
            ".jpg": "image",
            ".jpeg": "image",
            ".xmp": "sidecar",
            ".acr": "auxiliary",
        }[normalized]
        return InventoryEntry(
            relative_path,
            filename,
            extension,
            normalized,
            category,
            10,
            "2026-01-01T00:00:00.000000000Z",
            "admitted",
            (),
        )

    def _asset(self, *paths: str, create_sources: bool = True) -> LogicalAsset:
        entries = tuple(self._entry(path) for path in paths)
        if create_sources:
            for entry in entries:
                destination = self.session / Path(entry.relative_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    destination.write_bytes(b"synthetic source marker")
        inventory = InventoryResult(
            entries,
            (),
            (),
            sum(entry.category in {"raw", "image"} for entry in entries),
            sum(entry.category == "sidecar" for entry in entries),
            sum(entry.category == "auxiliary" for entry in entries),
            (),
        )
        return relate_inventory(inventory).assets[0]

    def _json_result(self, payload: object, *, returncode: int = 0, stderr: bytes = b"") -> ProcessResult:
        return ProcessResult(returncode, json.dumps(payload).encode("utf-8"), stderr)

    def _read(self, asset: LogicalAsset, result: ProcessResult | BaseException) -> tuple[ExifReadResult, RecordingRunner]:
        runner = RecordingRunner(result)
        read_result = ExifToolAdapter(self.settings, runner=runner).read_asset(self.reader, asset)
        return read_result, runner

    def test_selection_prefers_unique_nef_over_jpg(self) -> None:
        selection = select_exif_source(self._asset("foto.NEF", "foto.jpg"))
        self.assertEqual((selection.status, selection.role, selection.relative_path), ("selected", "raw", "foto.NEF"))

    def test_selection_falls_back_to_unique_jpg(self) -> None:
        selection = select_exif_source(self._asset("foto.jpeg"))
        self.assertEqual((selection.status, selection.role), ("selected", "image"))

    def test_ambiguous_asset_is_skipped_without_runner(self) -> None:
        asset = self._asset("foto.jpg", "foto.jpeg")
        result, runner = self._read(asset, AssertionError("runner must not execute"))
        self.assertEqual(result.status, "skipped_ambiguous")
        self.assertEqual(runner.calls, [])

    def test_asset_without_photo_is_skipped_without_runner(self) -> None:
        asset = self._asset("foto.xmp", "foto.acr")
        result, runner = self._read(asset, AssertionError("runner must not execute"))
        self.assertEqual(result.status, "skipped_no_photographic_file")
        self.assertEqual(runner.calls, [])

    def test_complete_fields_are_normalized_with_documented_fallbacks(self) -> None:
        payload = [{
            "SourceFile": str(self.session / "foto.NEF"),
            "DateTimeOriginal": "2025:12:31 23:59:58",
            "Make": "NIKON CORPORATION",
            "Model": "NIKON D7000",
            "LensID": "Synthetic 35mm",
            "ExposureTime": 0.008,
            "FNumber": 2.8,
            "ISO": 400,
            "FocalLength": 35.0,
            "ExifImageWidth": 4928,
            "ExifImageHeight": 3264,
            "Orientation": 1,
        }]
        result, _ = self._read(self._asset("foto.NEF"), self._json_result(payload))
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.metadata.captured_at, "2025-12-31T23:59:58")  # type: ignore[union-attr]
        self.assertEqual(result.metadata.lens, "Synthetic 35mm")  # type: ignore[union-attr]
        self.assertEqual((result.metadata.width_px, result.metadata.height_px), (4928, 3264))  # type: ignore[union-attr]

    def test_partial_fields_do_not_invalidate_available_values(self) -> None:
        result, _ = self._read(
            self._asset("foto.jpg"), self._json_result([{"Make": "NIKON"}])
        )
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.metadata.manufacturer, "NIKON")  # type: ignore[union-attr]
        self.assertIn("iso_unavailable", result.warnings)

    def test_invalid_json_is_sanitized(self) -> None:
        result, _ = self._read(self._asset("foto.NEF"), ProcessResult(0, b"{invalid", b"private"))
        self.assertEqual((result.status, result.error_code), ("error", "exiftool_json_invalid"))

    def test_empty_result_is_rejected(self) -> None:
        result, _ = self._read(self._asset("foto.NEF"), self._json_result([]))
        self.assertEqual(result.error_code, "exiftool_result_empty")

    def test_multiple_results_are_rejected(self) -> None:
        result, _ = self._read(self._asset("foto.NEF"), self._json_result([{}, {}]))
        self.assertEqual(result.error_code, "exiftool_result_count_invalid")

    def test_timeout_is_sanitized(self) -> None:
        error = subprocess.TimeoutExpired([str(self.executable)], 5)
        result, _ = self._read(self._asset("foto.NEF"), error)
        self.assertEqual(result.error_code, "exiftool_timeout")

    def test_missing_executable_becomes_unavailable_without_path(self) -> None:
        self.executable.unlink()
        adapter = ExifToolAdapter(self.settings, runner=RecordingRunner(ProcessResult(0, b"12.00", b"")))
        info = adapter.info()
        result = adapter.read_asset(self.reader, self._asset("foto.NEF"))
        self.assertEqual(info, ExifToolInfo(False, None, "unavailable"))
        self.assertEqual(result.error_code, "exiftool_unavailable")
        self.assertNotIn(str(self.executable), repr((info, result)))

    def test_valid_and_invalid_versions(self) -> None:
        valid = ExifToolAdapter(self.settings, runner=RecordingRunner(ProcessResult(0, b"13.42\n", b""))).info()
        invalid = ExifToolAdapter(self.settings, runner=RecordingRunner(ProcessResult(0, b"version unknown", b""))).info()
        self.assertEqual(valid, ExifToolInfo(True, "13.42", "available"))
        self.assertEqual(invalid, ExifToolInfo(False, None, "error"))

    def test_nonzero_exit_does_not_expose_stderr(self) -> None:
        private_path = b"C:\\Users\\private-person\\secret.NEF"
        result, _ = self._read(
            self._asset("foto.NEF"), ProcessResult(1, b"", private_path)
        )
        self.assertEqual(result.error_code, "exiftool_exit_error")
        self.assertNotIn("private-person", repr(result))

    def test_stdout_limit_is_enforced(self) -> None:
        result, _ = self._read(
            self._asset("foto.NEF"), ProcessResult(0, b"x" * 1025, b"")
        )
        self.assertEqual(result.error_code, "exiftool_output_too_large")

    def test_stderr_limit_is_enforced_without_retaining_content(self) -> None:
        result, _ = self._read(
            self._asset("foto.NEF"), ProcessResult(0, b"[{}]", b"s" * 1025)
        )
        self.assertEqual(result.error_code, "exiftool_output_too_large")
        self.assertNotIn("s" * 100, repr(result))

    def test_sensitive_and_unknown_keys_are_discarded(self) -> None:
        payload = [{
            "Make": "NIKON",
            "SourceFile": "C:/Users/private/secret.NEF",
            "GPSLatitude": -34.0,
            "GPSLongitude": -58.0,
            "SerialNumber": "PRIVATE-SERIAL",
            "LensSerialNumber": "PRIVATE-LENS",
            "OwnerName": "PRIVATE OWNER",
            "Copyright": "PRIVATE COPYRIGHT",
            "Comment": "PRIVATE COMMENT",
            "MakerNotes": "PRIVATE MAKER NOTES",
            "UnknownPrivateTag": "PRIVATE VALUE",
        }]
        result, _ = self._read(self._asset("foto.NEF"), self._json_result(payload))
        self.assertEqual(result.metadata.manufacturer, "NIKON")  # type: ignore[union-attr]
        representation = repr(result)
        for secret in ("Users/private", "GPS", "SERIAL", "OWNER", "COPYRIGHT", "COMMENT", "MAKER", "PRIVATE VALUE"):
            self.assertNotIn(secret, representation)

    def test_invalid_types_and_ranges_are_discarded(self) -> None:
        payload = [{
            "ExposureTime": "1/125",
            "FNumber": -2.8,
            "ISO": True,
            "FocalLength": 10001,
            "ImageWidth": 0,
            "ImageHeight": 2_000_000,
            "Orientation": 9,
        }]
        result, _ = self._read(self._asset("foto.NEF"), self._json_result(payload))
        self.assertEqual(result.status, "unavailable")
        self.assertTrue(all(value is None for value in (
            result.metadata.exposure_time_seconds,
            result.metadata.aperture_f_number,
            result.metadata.iso,
            result.metadata.focal_length_mm,
            result.metadata.width_px,
            result.metadata.height_px,
            result.metadata.orientation,
        )))  # type: ignore[union-attr]

    def test_command_uses_fixed_allowlist_and_has_no_write_argument(self) -> None:
        result, runner = self._read(self._asset("foto.NEF"), self._json_result([{"Make": "NIKON"}]))
        self.assertEqual(result.status, "partial")
        arguments = runner.calls[0][0]
        self.assertEqual(arguments[1:-1], FIXED_READ_ARGUMENTS)
        self.assertEqual(set(argument[1:] for argument in arguments[1:-1] if argument.startswith("-") and argument not in {"-json", "-n"}), set(REQUESTED_TAGS))
        self.assertFalse(any("=" in argument for argument in arguments))
        self.assertFalse(any(argument.casefold() in {"-overwrite_original", "-delete_original"} for argument in arguments))

    def test_default_runner_uses_argument_list_without_shell(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.BytesIO(b"13.42")
                self.stderr = io.BytesIO(b"")
                self.killed = False

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.killed = True

        process = FakeProcess()
        with patch("photo_session_workflow.exif.subprocess.Popen", return_value=process) as mocked:
            result = _default_runner(("tool", "-ver"), 5, 128)
        self.assertEqual(result.stdout, b"13.42")
        positional, keywords = mocked.call_args
        self.assertEqual(positional[0], ["tool", "-ver"])
        self.assertIs(keywords["shell"], False)

    def test_default_runner_bounds_captured_streams(self) -> None:
        class FakeProcess:
            stdout = io.BytesIO(b"x" * 5000)
            stderr = io.BytesIO(b"y" * 5000)

            @staticmethod
            def wait(timeout=None):
                return 0

            @staticmethod
            def kill():
                return None

        with patch("photo_session_workflow.exif.subprocess.Popen", return_value=FakeProcess()):
            result = _default_runner(("tool",), 5, 1024)
        self.assertEqual(len(result.stdout), 1025)
        self.assertEqual(len(result.stderr), 1025)

    def test_executable_path_validation_rejects_missing_and_protected_roots(self) -> None:
        with self.assertRaisesRegex(ExifConfigurationError, "available"):
            ExifToolSettings.create(
                executable=self.tools / "missing.exe",
                timeout_seconds=5,
                max_output_bytes=1024,
                boundaries=self.boundaries,
            )
        inside_session = self.session / "exiftool.exe"
        inside_session.write_bytes(b"marker")
        with self.assertRaisesRegex(ExifConfigurationError, "outside session_root"):
            ExifToolSettings.create(
                executable=inside_session,
                timeout_seconds=5,
                max_output_bytes=1024,
                boundaries=self.boundaries,
            )
        inside_workspace = self.workspace / "exiftool.exe"
        inside_workspace.write_bytes(b"marker")
        with self.assertRaisesRegex(ExifConfigurationError, "outside workspace_root"):
            ExifToolSettings.create(
                executable=inside_workspace,
                timeout_seconds=5,
                max_output_bytes=1024,
                boundaries=self.boundaries,
            )
        inside_repository = self.repository / "exiftool.exe"
        inside_repository.write_bytes(b"marker")
        with self.assertRaisesRegex(ExifConfigurationError, "outside repository_root"):
            ExifToolSettings.create(
                executable=inside_repository,
                timeout_seconds=5,
                max_output_bytes=1024,
                boundaries=self.boundaries,
            )

    def test_executable_reparse_point_is_rejected_deterministically(self) -> None:
        with patch(
            "photo_session_workflow.exif.reject_links_or_reparse_points",
            side_effect=PathBoundaryError("simulated reparse point"),
        ):
            with self.assertRaisesRegex(ExifConfigurationError, "available"):
                ExifToolSettings.create(
                    executable=self.executable,
                    timeout_seconds=5,
                    max_output_bytes=1024,
                    boundaries=self.boundaries,
                )

    def test_executable_symlink_is_rejected_when_available(self) -> None:
        link = self.tools / "linked-exiftool.exe"
        try:
            link.symlink_to(self.executable)
        except OSError as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")
        with self.assertRaisesRegex(ExifConfigurationError, "available"):
            ExifToolSettings.create(
                executable=link,
                timeout_seconds=5,
                max_output_bytes=1024,
                boundaries=self.boundaries,
            )

    def test_source_with_equals_is_rejected_before_runner(self) -> None:
        asset = self._asset("foto=name.NEF")
        result, runner = self._read(asset, AssertionError("runner must not execute"))
        self.assertEqual(result.error_code, "source_name_not_supported")
        self.assertEqual(runner.calls, [])

    def test_session_workspace_and_source_remain_unchanged(self) -> None:
        asset = self._asset("folder/foto.NEF")
        source = self.session / "folder" / "foto.NEF"
        before = (source.stat().st_mtime_ns, source.read_bytes())
        result, _ = self._read(asset, self._json_result([{"ISO": 100}]))
        after = (source.stat().st_mtime_ns, source.read_bytes())
        self.assertEqual(result.status, "partial")
        self.assertEqual(before, after)
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_models_are_immutable_and_results_are_deterministic(self) -> None:
        asset = self._asset("foto.NEF")
        payload = self._json_result([{"ISO": 100, "Make": "NIKON"}])
        first, _ = self._read(asset, payload)
        second, _ = self._read(asset, payload)
        self.assertEqual(first, second)
        with self.assertRaises(FrozenInstanceError):
            first.status = "changed"  # type: ignore[misc]
        metadata = ExifMetadata(iso=100)
        with self.assertRaises(FrozenInstanceError):
            metadata.iso = 200  # type: ignore[misc]


class RealExifToolIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("PHOTO_SESSION_EXIFTOOL_INTEGRATION") == "1",
        "real ExifTool integration requires explicit opt-in",
    )
    def test_real_exiftool_version_without_photo(self) -> None:
        executable = os.environ.get("PHOTO_SESSION_EXIFTOOL_PATH")
        if not executable:
            self.skipTest("PHOTO_SESSION_EXIFTOOL_PATH is not configured")
        completed = subprocess.run(
            [executable, "-ver"],
            shell=False,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
