from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

from PIL import Image, ImageCms

from photo_session_workflow.contact_sheet import (
    ContactSheetError,
    ContactSheetSettings,
    generate_contact_sheet,
)
from photo_session_workflow.lightroom_exports import (
    LightroomExportEntry,
    LightroomExportResolution,
    LightroomExportResolutionResult,
)
from photo_session_workflow.paths import (
    PathBoundaryError,
    RootBoundaries,
    SessionReader,
    WorkspaceWriter,
)
from photo_session_workflow.proxies import (
    ProxyConfigurationError,
    ProxySettings,
    generate_proxies,
)


class ProxyAndContactSheetTests(unittest.TestCase):
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
        self.settings = ProxySettings.create(
            long_edge_px=80,
            jpeg_quality=85,
            max_source_bytes=500_000,
            max_source_pixels=1_000_000,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _jpeg(
        self,
        name: str,
        *,
        size: tuple[int, int] = (100, 200),
        color: tuple[int, int, int] = (120, 80, 40),
        orientation: int | None = None,
        profile: bool = True,
    ) -> Path:
        image = Image.new("RGB", size, color)
        exif = Image.Exif()
        exif[315] = "synthetic private artist"
        if orientation is not None:
            exif[274] = orientation
        kwargs: dict[str, object] = {
            "format": "JPEG",
            "quality": 92,
            "exif": exif,
            "comment": b"synthetic private comment",
        }
        if profile:
            kwargs["icc_profile"] = ImageCms.ImageCmsProfile(
                ImageCms.createProfile("sRGB")
            ).tobytes()
        destination = self.export / name
        image.save(destination, **kwargs)
        return destination

    def _resolutions(
        self,
        names: tuple[str, ...],
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> LightroomExportResolutionResult:
        statuses = statuses or tuple("resolved" for _ in names)
        items = []
        for name, status in zip(names, statuses):
            source = self.export / name
            entry = None
            if status == "resolved":
                metadata = source.stat()
                entry = LightroomExportEntry(
                    f"export-app/{name}",
                    name,
                    source.suffix,
                    source.suffix.casefold(),
                    metadata.st_size,
                    "2026-01-01T00:00:00.000000000Z",
                )
            base = source.stem
            items.append(
                LightroomExportResolution(
                    f"asset:.:{base.casefold()}",
                    base,
                    5,
                    f"{base}.xmp",
                    status,
                    entry,
                    ("lightroom_export_user_declared",),
                )
            )
        values = tuple(items)
        return LightroomExportResolutionResult(
            values,
            sum(item.status == "resolved" for item in values),
            sum(item.status == "missing" for item in values),
            sum(item.status == "ambiguous" for item in values),
            sum(item.status == "invalid" for item in values),
        )

    def _generate(self, names: tuple[str, ...]):
        return generate_proxies(
            self.reader,
            self.writer,
            export_relative_directory="export-app",
            resolutions=self._resolutions(names),
            settings=self.settings,
        )

    def _sheet_settings(self, **overrides: int) -> ContactSheetSettings:
        values = {
            "columns": 2,
            "cell_width_px": 160,
            "thumbnail_height_px": 100,
            "label_height_px": 40,
            "padding_px": 5,
            "jpeg_quality": 85,
            "max_output_pixels": 1_000_000,
            "max_proxy_bytes": 500_000,
        }
        values.update(overrides)
        return ContactSheetSettings.create(**values)

    def test_proxy_is_oriented_resized_srgb_and_has_no_exif(self) -> None:
        source = self._jpeg("portrait.jpg", orientation=6)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        result = self._generate(("portrait.jpg",))
        self.assertTrue(result.ready)
        self.assertEqual(result.generated_count, 1)
        entry = result.entries[0]
        self.assertEqual((entry.width_px, entry.height_px), (80, 40))
        self.assertEqual(entry.preview_source, "lightroom_export")
        self.assertIn("exif_orientation_applied", entry.warnings)
        self.assertIn("embedded_profile_converted_to_srgb", entry.warnings)
        payload = self.writer.read_bytes(entry.proxy_relative_path, max_bytes=500_000)  # type: ignore[arg-type]
        with Image.open(io.BytesIO(payload)) as proxy:
            self.assertEqual(proxy.format, "JPEG")
            self.assertEqual(proxy.mode, "RGB")
            self.assertEqual(proxy.size, (80, 40))
            self.assertFalse(proxy.getexif())
            self.assertTrue(proxy.info.get("icc_profile"))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)

    def test_missing_profile_is_declared_as_srgb_assumption(self) -> None:
        self._jpeg("no-profile.jpg", profile=False)
        entry = self._generate(("no-profile.jpg",)).entries[0]
        self.assertEqual(entry.status, "generated")
        self.assertIn("source_profile_missing_assumed_srgb", entry.warnings)

    def test_embedded_srgb_profile_bytes_are_stable_across_processes(self) -> None:
        command = (
            "import hashlib; "
            "from photo_session_workflow.proxies import _srgb_profile; "
            "print(hashlib.sha256(_srgb_profile()[1]).hexdigest())"
        )
        first = subprocess.check_output(
            [sys.executable, "-c", command],
            text=True,
        ).strip()
        time.sleep(1.1)
        second = subprocess.check_output(
            [sys.executable, "-c", command],
            text=True,
        ).strip()
        self.assertEqual(first, second)

    def test_invalid_embedded_profile_is_rejected_without_raw_error(self) -> None:
        image = Image.new("RGB", (20, 20), (1, 2, 3))
        image.save(
            self.export / "invalid-profile.jpg",
            format="JPEG",
            icc_profile=b"not an ICC profile",
        )
        entry = self._generate(("invalid-profile.jpg",)).entries[0]
        self.assertEqual(entry.status, "error")
        self.assertEqual(entry.error_code, "invalid_embedded_color_profile")

    def test_invalid_jpeg_is_isolated_with_sanitized_error(self) -> None:
        (self.export / "broken.jpg").write_bytes(b"not a jpeg")
        result = self._generate(("broken.jpg",))
        self.assertFalse(result.ready)
        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.entries[0].error_code, "invalid_jpeg")
        self.assertFalse(any(self.workspace.rglob("*.jpg")))

    def test_source_size_and_pixel_limits_are_enforced(self) -> None:
        source = self._jpeg("large.jpg", size=(100, 100))
        tiny_bytes = ProxySettings.create(
            long_edge_px=80,
            jpeg_quality=85,
            max_source_bytes=source.stat().st_size - 1,
            max_source_pixels=1_000_000,
        )
        result = generate_proxies(
            self.reader,
            self.writer,
            export_relative_directory="export-app",
            resolutions=self._resolutions(("large.jpg",)),
            settings=tiny_bytes,
        )
        self.assertEqual(result.entries[0].error_code, "source_too_large")
        tiny_pixels = ProxySettings.create(
            long_edge_px=80,
            jpeg_quality=85,
            max_source_bytes=500_000,
            max_source_pixels=9_999,
        )
        result = generate_proxies(
            self.reader,
            self.writer,
            export_relative_directory="export-app",
            resolutions=self._resolutions(("large.jpg",)),
            settings=tiny_pixels,
        )
        self.assertEqual(result.entries[0].error_code, "source_pixel_limit_exceeded")

    def test_unresolved_selection_is_never_read(self) -> None:
        resolutions = self._resolutions(("missing.jpg",), statuses=("missing",))
        with mock.patch(
            "photo_session_workflow.paths.SessionReader.read_lightroom_export",
            autospec=True,
            side_effect=AssertionError("must not read"),
        ):
            result = generate_proxies(
                self.reader,
                self.writer,
                export_relative_directory="export-app",
                resolutions=resolutions,
                settings=self.settings,
            )
        self.assertEqual(result.entries[0].error_code, "lightroom_export_missing")

    def test_same_proxy_is_reused_without_duplication(self) -> None:
        self._jpeg("repeat.jpg")
        first = self._generate(("repeat.jpg",))
        second = self._generate(("repeat.jpg",))
        self.assertEqual(first.entries[0].proxy_relative_path, second.entries[0].proxy_relative_path)
        self.assertEqual(second.entries[0].status, "reused")
        self.assertEqual(len(list((self.workspace / "proxies").iterdir())), 1)

    def test_existing_proxy_conflict_is_not_overwritten(self) -> None:
        self._jpeg("conflict.jpg")
        first = self._generate(("conflict.jpg",))
        path = self.workspace / first.entries[0].proxy_relative_path  # type: ignore[arg-type]
        path.write_bytes(b"conflict")
        second = self._generate(("conflict.jpg",))
        self.assertEqual(second.entries[0].error_code, "existing_proxy_conflict")
        self.assertEqual(path.read_bytes(), b"conflict")

    def test_proxy_publication_failure_is_sanitized_and_cleans_temporary(self) -> None:
        self._jpeg("publication.jpg")
        with mock.patch(
            "photo_session_workflow.paths.os.link",
            side_effect=OSError("private absolute path must not escape"),
        ):
            result = self._generate(("publication.jpg",))
        self.assertEqual(result.entries[0].error_code, "proxy_publication_error")
        self.assertEqual(list((self.workspace / "proxies").iterdir()), [])

    def test_results_are_relative_immutable_and_contain_no_personal_paths(self) -> None:
        self._jpeg("Selección Ñ.jpg")
        entry = self._generate(("Selección Ñ.jpg",)).entries[0]
        self.assertFalse(Path(entry.proxy_relative_path).is_absolute())  # type: ignore[arg-type]
        self.assertNotIn(str(self.session), repr(entry))
        self.assertNotIn(str(self.workspace), repr(entry))
        with self.assertRaises(FrozenInstanceError):
            entry.status = "changed"  # type: ignore[misc]

    def test_contact_sheet_uses_only_complete_proxy_batch(self) -> None:
        self._jpeg("one.jpg", color=(200, 20, 20))
        self._jpeg("two.jpg", color=(20, 200, 20))
        proxies = self._generate(("one.jpg", "two.jpg"))
        result = generate_contact_sheet(
            self.writer,
            proxies=proxies,
            settings=self._sheet_settings(),
        )
        self.assertEqual(result.asset_count, 2)
        self.assertEqual((result.width_px, result.height_px), (320, 150))
        self.assertEqual(result.status, "generated")
        payload = self.writer.read_bytes(result.relative_path, max_bytes=500_000)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), result.sha256)
        with Image.open(io.BytesIO(payload)) as sheet:
            self.assertEqual(sheet.size, (320, 150))
            self.assertFalse(sheet.getexif())
            self.assertTrue(sheet.info.get("icc_profile"))

    def test_contact_sheet_is_deterministic_and_reused(self) -> None:
        self._jpeg("one.jpg")
        proxies = self._generate(("one.jpg",))
        first = generate_contact_sheet(
            self.writer, proxies=proxies, settings=self._sheet_settings()
        )
        second = generate_contact_sheet(
            self.writer, proxies=proxies, settings=self._sheet_settings()
        )
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.relative_path, second.relative_path)
        self.assertEqual(second.status, "reused")
        self.assertEqual(len(list((self.workspace / "contact-sheets").iterdir())), 1)

    def test_complete_flow_does_not_modify_or_copy_session_sources(self) -> None:
        self._jpeg("one.jpg", color=(200, 20, 20))
        self._jpeg("two.jpg", color=(20, 200, 20))
        (self.session / "one.NEF").write_bytes(b"synthetic non-decodable raw marker")
        (self.session / "one.JPG").write_bytes(b"synthetic camera jpg marker")
        (self.session / "one.xmp").write_text(
            "synthetic rating marker", encoding="utf-8"
        )
        before = {
            path.relative_to(self.session).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in self.session.rglob("*")
            if path.is_file()
        }
        proxies = self._generate(("one.jpg", "two.jpg"))
        generate_contact_sheet(
            self.writer,
            proxies=proxies,
            settings=self._sheet_settings(),
        )
        after = {
            path.relative_to(self.session).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in self.session.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        outputs = tuple(
            path.relative_to(self.workspace).as_posix()
            for path in self.workspace.rglob("*")
            if path.is_file()
        )
        self.assertTrue(outputs)
        self.assertTrue(
            all(
                path.startswith(("proxies/", "contact-sheets/"))
                and path.casefold().endswith(".jpg")
                for path in outputs
            )
        )

    def test_contact_sheet_rejects_incomplete_or_tampered_proxies(self) -> None:
        (self.export / "broken.jpg").write_bytes(b"broken")
        incomplete = self._generate(("broken.jpg",))
        with self.assertRaisesRegex(ContactSheetError, "complete proxy batch"):
            generate_contact_sheet(
                self.writer,
                proxies=incomplete,
                settings=self._sheet_settings(),
            )
        self._jpeg("valid.jpg")
        valid = self._generate(("valid.jpg",))
        path = self.workspace / valid.entries[0].proxy_relative_path  # type: ignore[arg-type]
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ContactSheetError, "hash"):
            generate_contact_sheet(
                self.writer,
                proxies=valid,
                settings=self._sheet_settings(),
            )

    def test_contact_sheet_publication_failure_is_sanitized_and_cleans_temporary(self) -> None:
        self._jpeg("one.jpg")
        proxies = self._generate(("one.jpg",))
        with mock.patch(
            "photo_session_workflow.paths.os.link",
            side_effect=OSError("private absolute path must not escape"),
        ):
            with self.assertRaisesRegex(ContactSheetError, "could not be published"):
                generate_contact_sheet(
                    self.writer,
                    proxies=proxies,
                    settings=self._sheet_settings(),
                )
        self.assertEqual(list((self.workspace / "contact-sheets").iterdir()), [])

    def test_contact_sheet_pixel_limit_and_unsafe_destinations_are_rejected(self) -> None:
        self._jpeg("one.jpg")
        proxies = self._generate(("one.jpg",))
        with self.assertRaisesRegex(ContactSheetError, "pixel limit"):
            generate_contact_sheet(
                self.writer,
                proxies=proxies,
                settings=self._sheet_settings(max_output_pixels=19_199),
            )
        for invalid in ("", ".", "../outside", os.fspath(self.workspace)):
            with self.subTest(invalid=invalid):
                with self.assertRaises((ContactSheetError, PathBoundaryError)):
                    generate_contact_sheet(
                        self.writer,
                        proxies=proxies,
                        settings=self._sheet_settings(),
                        destination_relative_directory=invalid,
                    )

    def test_workspace_read_rejects_escape_and_final_symlink_when_available(self) -> None:
        self.writer.ensure_directory("proxies")
        outside = self.temporary.name + "-outside.jpg"
        Path(outside).write_bytes(b"outside")
        self.addCleanup(lambda: Path(outside).unlink(missing_ok=True))
        with self.assertRaises(PathBoundaryError):
            self.writer.read_bytes("../outside.jpg", max_bytes=10)
        link = self.workspace / "proxies" / "link.jpg"
        try:
            link.symlink_to(Path(outside))
        except OSError as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")
        with self.assertRaisesRegex(PathBoundaryError, "symbolic link"):
            self.writer.read_bytes("proxies/link.jpg", max_bytes=10)

    def test_settings_validation_and_models_are_immutable(self) -> None:
        with self.assertRaises(ProxyConfigurationError):
            ProxySettings.create(long_edge_px=1)
        with self.assertRaises(ContactSheetError):
            ContactSheetSettings.create(columns=0)
        with self.assertRaises(FrozenInstanceError):
            self.settings.jpeg_quality = 10  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
