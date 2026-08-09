from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from photo_session_workflow.inventory import InventoryEntry, InventoryResult
from photo_session_workflow.paths import RootBoundaries, SessionReader
from photo_session_workflow.rated_selection import build_rated_selection
from photo_session_workflow.rating_filter import RatingFilter, filter_assets_by_rating
from photo_session_workflow.relations import RelationResult, relate_inventory
from photo_session_workflow.selection_manifest import build_preliminary_manifest
from photo_session_workflow.xmp_rating import (
    RatingReadResult,
    XmpRatingReader,
    read_relation_ratings,
)
from tests.synthetic_fixtures import create_synthetic_session


XMP_PREFIX = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/" '
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    'xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
    '<rdf:RDF>'
)
XMP_SUFFIX = "</rdf:RDF></x:xmpmeta>"


class RatedSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        parent = Path(self.temporary.name)
        self.session = parent / "session"
        self.workspace = parent / "workspace"
        self.repository = parent / "repository"
        for root in (self.session, self.workspace, self.repository):
            root.mkdir()
        self.reader = SessionReader(
            RootBoundaries.create(
                session_root=self.session,
                workspace_root=self.workspace,
                repository_root=self.repository,
            )
        )

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
            1,
            "2026-01-01T00:00:00.000000000Z",
            "admitted",
            (),
        )

    def _relations(self, *paths: str) -> RelationResult:
        entries = tuple(self._entry(path) for path in paths)
        inventory = InventoryResult(
            entries,
            (),
            (),
            sum(entry.category in {"raw", "image"} for entry in entries),
            sum(entry.category == "sidecar" for entry in entries),
            sum(entry.category == "auxiliary" for entry in entries),
            (),
        )
        return relate_inventory(inventory)

    def _write(self, relative_path: str, content: str | bytes) -> Path:
        destination = self.session / Path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = content.encode("utf-8") if isinstance(content, str) else content
        destination.write_bytes(payload)
        return destination

    def _attribute_xmp(self, value: str) -> str:
        return f'{XMP_PREFIX}<rdf:Description xmp:Rating="{value}"/>{XMP_SUFFIX}'

    def _element_xmp(self, *values: str) -> str:
        elements = "".join(f"<xmp:Rating>{value}</xmp:Rating>" for value in values)
        return f"{XMP_PREFIX}<rdf:Description>{elements}</rdf:Description>{XMP_SUFFIX}"

    def _read_single(self, xmp_content: str | bytes, *, max_bytes: int = 262_144) -> RatingReadResult:
        self._write("photo.xmp", xmp_content)
        relations = self._relations("photo.NEF", "photo.xmp")
        return XmpRatingReader(max_bytes=max_bytes).read_asset(
            self.reader, relations.assets[0]
        )

    def test_ratings_one_through_five(self) -> None:
        for rating in range(1, 6):
            with self.subTest(rating=rating):
                result = self._read_single(self._attribute_xmp(str(rating)))
                self.assertEqual((result.status, result.rating), ("rated", rating))

    def test_zero_is_unrated_and_minus_one_is_rejected(self) -> None:
        unrated = self._read_single(self._attribute_xmp("0"))
        rejected = self._read_single(self._attribute_xmp("-1"))
        self.assertEqual((unrated.status, unrated.rating), ("unrated", 0))
        self.assertEqual((rejected.status, rejected.rating), ("rejected", -1))

    def test_absent_rating_is_missing(self) -> None:
        result = self._read_single(
            f"{XMP_PREFIX}<rdf:Description/>{XMP_SUFFIX}"
        )
        self.assertEqual(result.status, "missing")
        self.assertIn("rating_missing", result.warnings)

    def test_invalid_rating_value(self) -> None:
        result = self._read_single(self._attribute_xmp("six"))
        self.assertEqual(result.status, "invalid")
        self.assertIn("rating_value_invalid", result.warnings)

    def test_malformed_xmp_is_sanitized(self) -> None:
        result = self._read_single(b"<x:xmpmeta><broken>")
        self.assertEqual((result.status, result.error_code), ("error", "xmp_xml_invalid"))
        self.assertNotIn("broken", repr(result))

    def test_attribute_and_element_forms(self) -> None:
        attribute = self._read_single(self._attribute_xmp("3"))
        element = self._read_single(self._element_xmp("4"))
        self.assertEqual(attribute.rating, 3)
        self.assertEqual(element.rating, 4)

    def test_equal_duplicate_values_are_accepted(self) -> None:
        result = self._read_single(self._element_xmp("4", "4"))
        self.assertEqual((result.status, result.rating), ("rated", 4))
        self.assertIn("duplicate_rating_values", result.warnings)

    def test_conflicting_values_are_invalid(self) -> None:
        result = self._read_single(self._element_xmp("3", "5"))
        self.assertEqual(result.status, "invalid")
        self.assertIn("rating_values_conflict", result.warnings)

    def test_doctype_and_entity_are_forbidden(self) -> None:
        doctype = self._read_single(
            f'<!DOCTYPE x [<!ELEMENT x ANY>]>{self._attribute_xmp("3")}'
        )
        entity = self._read_single(
            f'<!ENTITY secret "value">{self._attribute_xmp("3")}'
        )
        self.assertEqual(doctype.error_code, "xmp_doctype_forbidden")
        self.assertEqual(entity.error_code, "xmp_entity_forbidden")

    def test_utf16_doctype_is_also_forbidden(self) -> None:
        payload = (
            '<!DOCTYPE x [<!ENTITY secret "value">]>'
            f'{XMP_PREFIX}<rdf:Description xmp:Rating="3"/>{XMP_SUFFIX}'
        ).encode("utf-16")
        result = self._read_single(payload)
        self.assertEqual(result.error_code, "xmp_doctype_forbidden")

    def test_xmp_over_limit_is_rejected(self) -> None:
        result = self._read_single(b"x" * 65, max_bytes=64)
        self.assertEqual(result.error_code, "xmp_too_large")

    def test_missing_sidecar_and_missing_file_are_isolated(self) -> None:
        no_sidecar = self._relations("photo.NEF").assets[0]
        missing_file = self._relations("other.NEF", "other.xmp").assets[0]
        xmp_reader = XmpRatingReader()
        absent = xmp_reader.read_asset(self.reader, no_sidecar)
        unavailable = xmp_reader.read_asset(self.reader, missing_file)
        self.assertEqual((absent.status, absent.warnings), ("missing", ("xmp_missing",)))
        self.assertEqual((unavailable.status, unavailable.error_code), ("error", "xmp_unavailable"))
        self.assertNotIn(str(self.session), repr(unavailable))

    def test_ambiguous_sidecar_and_asset_are_skipped(self) -> None:
        sidecar_ambiguous = self._relations("photo.NEF", "photo.xmp", "photo.XMP").assets[0]
        asset_ambiguous = self._relations("other.jpg", "other.jpeg", "other.xmp").assets[0]
        xmp_reader = XmpRatingReader()
        self.assertEqual(
            xmp_reader.read_asset(self.reader, sidecar_ambiguous).status,
            "skipped_ambiguous_sidecar",
        )
        self.assertEqual(
            xmp_reader.read_asset(self.reader, asset_ambiguous).status,
            "skipped_ambiguous_asset",
        )

    def test_minimum_three_filter_selects_three_four_five(self) -> None:
        relations = self._relations("one.NEF", "two.NEF", "three.NEF", "four.NEF", "five.NEF")
        ratings = tuple(
            RatingReadResult(asset.asset_id, index, "rated", f"{index}.xmp", (), None)
            for index, asset in enumerate(relations.assets, start=1)
        )
        result = filter_assets_by_rating(
            relations, ratings, RatingFilter.create(minimum_rating=3)
        )
        self.assertEqual([item.rating_result.rating for item in result.selected], [3, 4, 5])
        self.assertEqual([item.reason for item in result.excluded], ["rating_below_minimum", "rating_below_minimum"])

    def test_exact_rating_set_filter(self) -> None:
        relations = self._relations("one.NEF", "two.NEF", "three.NEF", "four.NEF", "five.NEF")
        ratings = tuple(
            RatingReadResult(asset.asset_id, index, "rated", None, (), None)
            for index, asset in enumerate(relations.assets, start=1)
        )
        result = filter_assets_by_rating(
            relations, ratings, RatingFilter.create(exact_ratings={2, 4})
        )
        self.assertEqual([item.rating_result.rating for item in result.selected], [2, 4])

    def test_invalid_filter_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            RatingFilter.create(minimum_rating=3, exact_ratings={4})
        with self.assertRaisesRegex(ValueError, "1 to 5"):
            RatingFilter.create(exact_ratings={0, 5})
        with self.assertRaisesRegex(ValueError, "between 1 and 5"):
            RatingFilter.create(minimum_rating=6)

    def test_non_rated_states_are_excluded_with_reasons(self) -> None:
        states = (
            "unrated", "rejected", "missing", "invalid", "error",
            "skipped_ambiguous_asset", "skipped_ambiguous_sidecar",
        )
        relations = self._relations(*(f"asset-{index}.NEF" for index in range(len(states))))
        ratings = tuple(
            RatingReadResult(asset.asset_id, None, state, None, (), None)
            for asset, state in zip(relations.assets, states)
        )
        result = filter_assets_by_rating(
            relations, ratings, RatingFilter.create(minimum_rating=1)
        )
        self.assertEqual(result.selected, ())
        self.assertEqual(
            {item.reason for item in result.excluded},
            {f"status_{state}" for state in states},
        )

    def test_matching_jpg_is_candidate_but_not_confirmed(self) -> None:
        relations = self._relations("photo.NEF", "photo.xmp", "photo.JPG")
        asset = relations.assets[0]
        ratings = (RatingReadResult(asset.asset_id, 4, "rated", "photo.xmp", (), None),)
        selection = filter_assets_by_rating(relations, ratings, RatingFilter.create(minimum_rating=3))
        item = build_preliminary_manifest(selection).assets[0]
        self.assertEqual(item.jpg_candidate_relative_path, "photo.JPG")
        self.assertIn("jpg_candidate_unverified", item.warnings)

    def test_missing_jpg_and_edit_suffix_are_not_guessed(self) -> None:
        relations = self._relations("photo.NEF", "photo.xmp", "photo-Edit.jpg")
        photo = next(asset for asset in relations.assets if asset.normalized_base_name == "photo")
        ratings = tuple(
            RatingReadResult(
                asset.asset_id,
                4 if asset == photo else None,
                "rated" if asset == photo else "missing",
                "photo.xmp" if asset == photo else None,
                (),
                None,
            )
            for asset in relations.assets
        )
        selection = filter_assets_by_rating(relations, ratings, RatingFilter.create(minimum_rating=3))
        item = build_preliminary_manifest(selection).assets[0]
        self.assertIsNone(item.jpg_candidate_relative_path)
        self.assertIn("jpg_candidate_missing", item.warnings)

    def test_ambiguous_jpg_candidates_are_not_chosen(self) -> None:
        relations = self._relations("photo.NEF", "photo.xmp", "photo.jpg", "photo.jpeg")
        asset = relations.assets[0]
        ratings = (RatingReadResult(asset.asset_id, 4, "rated", "photo.xmp", (), None),)
        selection = filter_assets_by_rating(
            relations, ratings, RatingFilter.create(minimum_rating=3)
        )
        item = build_preliminary_manifest(selection).assets[0]
        self.assertIsNone(item.jpg_candidate_relative_path)
        self.assertIn("jpg_candidate_ambiguous", item.warnings)

    def test_manifest_is_deterministic_valid_and_minimized(self) -> None:
        relations = self._relations("Selección Ñ/photo.NEF", "Selección Ñ/photo.xmp", "Selección Ñ/photo.jpg")
        asset = relations.assets[0]
        ratings = (RatingReadResult(asset.asset_id, 5, "rated", "Selección Ñ/photo.xmp", ("xmp_last_saved_state_only",), None),)
        selection = filter_assets_by_rating(relations, ratings, RatingFilter.create(minimum_rating=3))
        first = build_preliminary_manifest(selection)
        second = build_preliminary_manifest(selection)
        self.assertEqual(first, second)
        self.assertEqual(first.to_json(), second.to_json())
        decoded = json.loads(first.to_json())
        self.assertEqual(decoded["schema_version"], "0.1")
        self.assertEqual(decoded["selected_count"], 1)
        serialized = first.to_json()
        for forbidden in (str(self.session), "GPS", "EXIF", "<x:xmpmeta", "timestamp", "NEF"):
            self.assertNotIn(forbidden, serialized)

    def test_workflow_is_in_memory_and_does_not_modify_sources(self) -> None:
        self._write("photo.NEF", b"synthetic non-decodable raw")
        self._write("photo.jpg", b"synthetic non-decodable jpg")
        self._write("photo.xmp", self._attribute_xmp("4"))
        before = {
            path.name: (path.stat().st_mtime_ns, path.read_bytes())
            for path in self.session.iterdir()
        }
        inventory = self.reader.inventory()
        relations = relate_inventory(inventory)
        workflow = build_rated_selection(
            self.reader,
            relations,
            xmp_reader=XmpRatingReader(),
            rating_filter=RatingFilter.create(minimum_rating=3),
        )
        after = {
            path.name: (path.stat().st_mtime_ns, path.read_bytes())
            for path in self.session.iterdir()
        }
        self.assertEqual(before, after)
        self.assertEqual(list(self.workspace.iterdir()), [])
        self.assertEqual(workflow.manifest.selected_count, 1)
        self.assertEqual(json.loads(workflow.manifest_json)["assets"][0]["rating"], 4)

    def test_error_in_one_asset_does_not_block_others(self) -> None:
        self._write("bad.xmp", b"<broken>")
        self._write("good.xmp", self._attribute_xmp("5"))
        relations = self._relations("bad.NEF", "bad.xmp", "good.NEF", "good.xmp")
        results = read_relation_ratings(self.reader, relations, XmpRatingReader())
        self.assertEqual([result.status for result in results], ["error", "rated"])

    def test_existing_synthetic_fixtures_are_compatible(self) -> None:
        create_synthetic_session(self.session)
        relations = relate_inventory(self.reader.inventory())
        results = read_relation_ratings(self.reader, relations, XmpRatingReader())
        rated = next(result for result in results if result.asset_id.endswith(":rated"))
        self.assertEqual((rated.status, rated.rating), ("rated", 4))

    def test_models_are_immutable(self) -> None:
        result = RatingReadResult("asset:.:photo", 4, "rated", "photo.xmp", (), None)
        with self.assertRaises(FrozenInstanceError):
            result.rating = 5  # type: ignore[misc]
        rating_filter = RatingFilter.create(minimum_rating=3)
        with self.assertRaises(FrozenInstanceError):
            rating_filter.minimum_rating = 1  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
