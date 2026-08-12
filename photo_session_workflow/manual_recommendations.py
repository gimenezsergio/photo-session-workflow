"""Private SQLite registry for manually entered Phase 0 recommendations."""

from __future__ import annotations

import os
import re
import sqlite3
import stat
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterator

from .paths import (
    PathBoundaryError,
    WorkspaceWriter,
    reject_links_or_reparse_points,
)
from .review_handoff import ReviewPackageSummary


class ManualRecommendationError(ValueError):
    """Raised for invalid manual records or sanitized storage failures."""


RECOMMENDATION_CATEGORIES = frozenset(
    {
        "exposure",
        "color",
        "series_coherence",
        "similarity",
        "selection",
        "global_adjustment",
        "mask",
    }
)
RECOMMENDATION_STATUSES = frozenset({"pending", "confirmed", "rejected"})


@dataclass(frozen=True, slots=True)
class ManualRecommendationSettings:
    database_relative_path: str = "state/recommendations.sqlite3"

    @classmethod
    def create(
        cls,
        *,
        database_relative_path: str = "state/recommendations.sqlite3",
    ) -> "ManualRecommendationSettings":
        return cls(_relative_database_path(database_relative_path))


@dataclass(frozen=True, slots=True)
class ManualRecommendation:
    recommendation_id: str
    package_sha256: str
    asset_id: str
    identifier_name: str
    category: str
    recommendation: str
    status: str
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True, slots=True)
class RecommendationStatusEvent:
    event_id: int
    recommendation_id: str
    previous_status: str | None
    status: str
    note: str | None
    recorded_at_utc: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _relative_database_path(value: str | os.PathLike[str]) -> str:
    text = os.fspath(value)
    posix = PurePosixPath(text.replace("\\", "/"))
    windows = PureWindowsPath(text)
    if (
        not text
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or posix == PurePosixPath(".")
        or ".." in posix.parts
        or posix.suffix.casefold() not in {".sqlite", ".sqlite3", ".db"}
    ):
        raise ManualRecommendationError(
            "recommendation database must be a relative SQLite path"
        )
    return posix.as_posix()


def _text(value: object, *, label: str, maximum: int, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise ManualRecommendationError(f"{label} must be text")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(ord(character) < 32 and character not in "\n\t" for character in normalized)
    ):
        raise ManualRecommendationError(f"{label} is invalid")
    return normalized


def _status(value: object) -> str:
    if not isinstance(value, str) or value not in RECOMMENDATION_STATUSES:
        raise ManualRecommendationError("recommendation status is invalid")
    return value


def _category(value: object) -> str:
    if not isinstance(value, str) or value not in RECOMMENDATION_CATEGORIES:
        raise ManualRecommendationError("recommendation category is invalid")
    return value


def _review_assets(review: ReviewPackageSummary) -> dict[str, str]:
    if not isinstance(review, ReviewPackageSummary):
        raise ManualRecommendationError("review package summary is required")
    if not re.fullmatch(r"[0-9a-f]{64}", review.sha256):
        raise ManualRecommendationError("review package identity is invalid")
    assets = {item.asset_id: item.identifier_name for item in review.assets}
    if (
        not assets
        or len(assets) != len(review.assets)
        or len(assets) != review.selected_count
    ):
        raise ManualRecommendationError("review package assets are invalid")
    return assets


class ManualRecommendationStore:
    """Closed SQLite capability restricted to one file inside the workspace."""

    __slots__ = ("_clock", "_relative_path", "_writer")

    def __init__(
        self,
        writer: WorkspaceWriter,
        *,
        database_relative_path: str = "state/recommendations.sqlite3",
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        if not isinstance(writer, WorkspaceWriter):
            raise ManualRecommendationError("workspace writer capability is required")
        if not callable(clock):
            raise ManualRecommendationError("recommendation clock is invalid")
        self._writer = writer
        self._relative_path = _relative_database_path(database_relative_path)
        self._clock = clock
        parent = PurePosixPath(self._relative_path).parent.as_posix()
        if parent != ".":
            writer.ensure_directory(parent)
        try:
            writer.write_bytes(self._relative_path, b"", overwrite=False)
        except FileExistsError:
            pass
        except (OSError, PathBoundaryError) as exc:
            raise ManualRecommendationError(
                "recommendation database could not be initialized"
            ) from exc
        self._initialize_schema()

    @property
    def database_relative_path(self) -> str:
        return self._relative_path

    def _validated_database(self) -> Path:
        candidate = self._writer.root / Path(self._relative_path)
        try:
            reject_links_or_reparse_points(
                candidate,
                label="recommendation database",
            )
            root = self._writer.root.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
            mode = candidate.stat(follow_symlinks=False).st_mode
        except (OSError, RuntimeError, PathBoundaryError) as exc:
            raise ManualRecommendationError(
                "recommendation database is unavailable"
            ) from exc
        if not resolved.is_relative_to(root) or not stat.S_ISREG(mode):
            raise ManualRecommendationError("recommendation database is invalid")
        return resolved

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        database = self._validated_database()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                database,
                timeout=5.0,
                isolation_level="DEFERRED",
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA temp_store = MEMORY")
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise ManualRecommendationError(
                "recommendation database could not be opened"
            ) from exc
        try:
            yield connection
        except sqlite3.Error as exc:
            connection.rollback()
            raise ManualRecommendationError(
                "recommendation database operation failed"
            ) from exc
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS manual_recommendations (
                    recommendation_id TEXT PRIMARY KEY,
                    package_sha256 TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    identifier_name TEXT NOT NULL,
                    category TEXT NOT NULL CHECK (category IN (
                        'exposure', 'color', 'series_coherence', 'similarity',
                        'selection', 'global_adjustment', 'mask'
                    )),
                    recommendation_text TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN (
                        'pending', 'confirmed', 'rejected'
                    )),
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS recommendations_by_package
                    ON manual_recommendations(package_sha256, created_at_utc, recommendation_id);
                CREATE TABLE IF NOT EXISTS recommendation_status_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id TEXT NOT NULL,
                    previous_status TEXT CHECK (
                        previous_status IS NULL OR previous_status IN (
                            'pending', 'confirmed', 'rejected'
                        )
                    ),
                    status TEXT NOT NULL CHECK (status IN (
                        'pending', 'confirmed', 'rejected'
                    )),
                    note TEXT,
                    recorded_at_utc TEXT NOT NULL,
                    FOREIGN KEY (recommendation_id)
                        REFERENCES manual_recommendations(recommendation_id)
                        ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS events_by_recommendation
                    ON recommendation_status_events(recommendation_id, event_id);
                """
            )
            connection.commit()

    @staticmethod
    def _recommendation(row: sqlite3.Row) -> ManualRecommendation:
        return ManualRecommendation(
            row["recommendation_id"],
            row["package_sha256"],
            row["asset_id"],
            row["identifier_name"],
            row["category"],
            row["recommendation_text"],
            row["status"],
            row["created_at_utc"],
            row["updated_at_utc"],
        )

    def add(
        self,
        review: ReviewPackageSummary,
        *,
        asset_id: str,
        category: str,
        recommendation: str,
        status: str = "pending",
    ) -> ManualRecommendation:
        assets = _review_assets(review)
        if not isinstance(asset_id, str) or asset_id not in assets:
            raise ManualRecommendationError(
                "recommendation asset is not part of the reviewed package"
            )
        validated_category = _category(category)
        validated_text = _text(
            recommendation,
            label="recommendation",
            maximum=4_000,
        )
        validated_status = _status(status)
        recommendation_id = uuid.uuid4().hex
        timestamp = self._clock()
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise ManualRecommendationError("recommendation clock returned an invalid value")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO manual_recommendations (
                    recommendation_id, package_sha256, asset_id, identifier_name,
                    category, recommendation_text, status, created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recommendation_id,
                    review.sha256,
                    asset_id,
                    assets[asset_id],
                    validated_category,
                    validated_text,
                    validated_status,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO recommendation_status_events (
                    recommendation_id, previous_status, status, note, recorded_at_utc
                ) VALUES (?, NULL, ?, NULL, ?)
                """,
                (recommendation_id, validated_status, timestamp),
            )
            connection.commit()
        return ManualRecommendation(
            recommendation_id,
            review.sha256,
            asset_id,
            assets[asset_id],
            validated_category,
            validated_text,  # type: ignore[arg-type]
            validated_status,
            timestamp,
            timestamp,
        )

    def list_for_review(
        self,
        review: ReviewPackageSummary,
    ) -> tuple[ManualRecommendation, ...]:
        _review_assets(review)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM manual_recommendations
                WHERE package_sha256 = ?
                ORDER BY created_at_utc, recommendation_id
                """,
                (review.sha256,),
            ).fetchall()
        return tuple(self._recommendation(row) for row in rows)

    def set_status(
        self,
        review: ReviewPackageSummary,
        recommendation_id: str,
        *,
        status: str,
        expected_status: str | None = None,
        note: str | None = None,
    ) -> ManualRecommendation:
        assets = _review_assets(review)
        if not isinstance(recommendation_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", recommendation_id
        ):
            raise ManualRecommendationError("recommendation id is invalid")
        target_status = _status(status)
        expected = None if expected_status is None else _status(expected_status)
        validated_note = _text(note, label="status note", maximum=2_000, optional=True)
        timestamp = self._clock()
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise ManualRecommendationError("recommendation clock returned an invalid value")

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM manual_recommendations
                WHERE recommendation_id = ? AND package_sha256 = ?
                """,
                (recommendation_id, review.sha256),
            ).fetchone()
            if row is None:
                raise ManualRecommendationError(
                    "recommendation does not belong to the reviewed package"
                )
            if row["asset_id"] not in assets:
                raise ManualRecommendationError(
                    "recommendation asset is not part of the reviewed package"
                )
            current = row["status"]
            if expected is not None and current != expected:
                raise ManualRecommendationError("recommendation status changed concurrently")
            if current == target_status:
                raise ManualRecommendationError("recommendation already has that status")
            cursor = connection.execute(
                """
                UPDATE manual_recommendations
                SET status = ?, updated_at_utc = ?
                WHERE recommendation_id = ? AND package_sha256 = ? AND status = ?
                """,
                (
                    target_status,
                    timestamp,
                    recommendation_id,
                    review.sha256,
                    current,
                ),
            )
            if cursor.rowcount != 1:
                raise ManualRecommendationError("recommendation status changed concurrently")
            connection.execute(
                """
                INSERT INTO recommendation_status_events (
                    recommendation_id, previous_status, status, note, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    recommendation_id,
                    current,
                    target_status,
                    validated_note,
                    timestamp,
                ),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM manual_recommendations WHERE recommendation_id = ?",
                (recommendation_id,),
            ).fetchone()
        return self._recommendation(updated)

    def history(
        self,
        review: ReviewPackageSummary,
        recommendation_id: str,
    ) -> tuple[RecommendationStatusEvent, ...]:
        records = {
            item.recommendation_id
            for item in self.list_for_review(review)
        }
        if recommendation_id not in records:
            raise ManualRecommendationError(
                "recommendation does not belong to the reviewed package"
            )
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_id, recommendation_id, previous_status, status,
                       note, recorded_at_utc
                FROM recommendation_status_events
                WHERE recommendation_id = ?
                ORDER BY event_id
                """,
                (recommendation_id,),
            ).fetchall()
        return tuple(
            RecommendationStatusEvent(
                row["event_id"],
                row["recommendation_id"],
                row["previous_status"],
                row["status"],
                row["note"],
                row["recorded_at_utc"],
            )
            for row in rows
        )
