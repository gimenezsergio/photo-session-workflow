from __future__ import annotations

import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from photo_session_workflow.paths import RootBoundaries, SessionReader
from tests.synthetic_fixtures import create_synthetic_session


class SyntheticFixtureTests(unittest.TestCase):
    def test_fixture_set_covers_required_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = create_synthetic_session(root)
            names = {path.name for path in fixture.files}
            self.assertTrue(
                {
                    "rated.NEF",
                    "rated.jpg",
                    "rated.xmp",
                    "rated.acr",
                    "unrated.xmp",
                    "invalid-rating.xmp",
                    "malformed.xmp",
                    "ambiguous.NEF",
                    "ambiguous.jpg",
                    "ambiguous.jpeg",
                    "CASE_VARIANT.NEF",
                    "case_variant.xmp",
                    "orphan.xmp",
                }.issubset(names)
            )
            self.assertTrue(all(not path.exists() for path in fixture.expected_missing))

    def test_nef_and_jpg_are_explicitly_non_decodable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            create_synthetic_session(root)
            self.assertIn(b"NOT_A_DECODABLE_RAW_FILE", (root / "rated.NEF").read_bytes())
            self.assertIn(
                b"NOT_A_DECODABLE_JPEG_IMAGE", (root / "rated.jpg").read_bytes()
            )

    def test_xmp_variants_are_structurally_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            create_synthetic_session(root)
            rating_key = "{http://ns.adobe.com/xap/1.0/}Rating"
            rated = ET.parse(root / "rated.xmp").getroot()
            unrated = ET.parse(root / "unrated.xmp").getroot()
            invalid = ET.parse(root / "invalid-rating.xmp").getroot()
            rated_description = next(rated.iter("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description"))
            unrated_description = next(
                unrated.iter("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description")
            )
            invalid_description = next(
                invalid.iter("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description")
            )
            self.assertEqual(rated_description.attrib[rating_key], "4")
            self.assertNotIn(rating_key, unrated_description.attrib)
            self.assertEqual(invalid_description.attrib[rating_key], "invalid-rating")
            with self.assertRaises(ET.ParseError):
                ET.parse(root / "malformed.xmp")

    def test_fixture_generation_is_isolated_and_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_root = Path(first)
            second_root = Path(second)
            first_fixture = create_synthetic_session(first_root)
            second_fixture = create_synthetic_session(second_root)
            self.assertNotEqual(first_fixture.root, second_fixture.root)
            self.assertTrue(all(path.is_relative_to(first_root) for path in first_fixture.files))
            self.assertTrue(all(path.is_relative_to(second_root) for path in second_fixture.files))
        self.assertFalse(first_root.exists())
        self.assertFalse(second_root.exists())

    def test_fixture_contents_have_no_personal_gps_or_local_path_data(self) -> None:
        forbidden = re.compile(
            rb"C:\\Users|/Users/|GPS|latitude|longitude|@|token|password|credential",
            re.IGNORECASE,
        )
        with tempfile.TemporaryDirectory() as temporary:
            fixture = create_synthetic_session(Path(temporary))
            for path in fixture.files:
                self.assertIsNone(forbidden.search(path.read_bytes()), path.name)

    def test_reading_fixture_session_causes_no_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            session = parent / "session"
            workspace = parent / "workspace"
            repository = parent / "repository"
            for path in (session, workspace, repository):
                path.mkdir()
            fixture = create_synthetic_session(session)
            snapshot = {path.name: path.read_bytes() for path in fixture.files}
            reader = SessionReader(
                RootBoundaries.create(
                    session_root=session,
                    workspace_root=workspace,
                    repository_root=repository,
                )
            )
            for relative_name, expected in snapshot.items():
                self.assertEqual(reader.read_bytes(relative_name), expected)
            self.assertEqual(
                snapshot, {path.name: path.read_bytes() for path in fixture.files}
            )
            self.assertEqual(list(workspace.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
