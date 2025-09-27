"""Utilities for cleaning up Home Assistant recorder databases."""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from types import TracebackType


@dataclass(frozen=True)
class DeletionSummary:
    """Summary of rows removed from the recorder database."""

    states: int = 0
    statistics: int = 0
    statistics_short_term: int = 0

    @property
    def total(self) -> int:
        """Return the total number of deleted rows across all tables."""

        return self.states + self.statistics + self.statistics_short_term


@dataclass(frozen=True)
class StateDeletionPreview:
    """Summary of rows that would be removed by deleting a state value."""

    states_count: int = 0
    statistics_count: int = 0
    statistics_short_term_count: int = 0
    first_seen_ts: float | None = None
    last_seen_ts: float | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    examples: tuple[sqlite3.Row, ...] = ()

    @property
    def total(self) -> int:
        """Return the total number of rows that would be removed."""

        return (
            self.states_count
            + self.statistics_count
            + self.statistics_short_term_count
        )


@dataclass(frozen=True)
class ValueStatistics:
    """Aggregated information for a sensor state value."""

    state: str
    count: int
    first_seen_ts: float | None
    last_seen_ts: float | None
    first_seen: str | None
    last_seen: str | None


class RecorderFixer:
    """Convenience wrapper around the Home Assistant recorder database."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def __enter__(self) -> RecorderFixer:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def get_metadata_id(self, entity_id: str) -> int | None:
        """Return the ``states_meta.metadata_id`` for the given entity."""

        cur = self.conn.execute(
            "SELECT metadata_id FROM states_meta WHERE entity_id = ?",
            (entity_id,),
        )
        row = cur.fetchone()
        return row["metadata_id"] if row else None

    def get_statistic_id(self, entity_id: str) -> int | None:
        """Return the ``statistics_meta.id`` for the given entity."""

        cur = self.conn.execute(
            "SELECT id FROM statistics_meta WHERE statistic_id = ?",
            (entity_id,),
        )
        row = cur.fetchone()
        return row["id"] if row else None

    def _execute_delete(self, query: str, params: Iterable[object]) -> int:
        """Execute a ``DELETE`` statement and return affected rows."""

        cursor = self.conn.execute(query, tuple(params))
        return cursor.rowcount

    @staticmethod
    def _coerce_state_to_float(state_value: str) -> float | None:
        """Convert a state value to ``float`` if possible."""

        try:
            value = float(state_value)
        except (TypeError, ValueError):
            return None

        return value if math.isfinite(value) else None

    def delete_state_everywhere(self, entity_id: str, state_value: str) -> DeletionSummary:
        """Remove matching state rows from recorder tables.

        The method deletes rows from ``states``, ``statistics`` and
        ``statistics_short_term`` that belong to ``entity_id`` and match the
        provided ``state_value``. The statistics tables only store numeric
        values, therefore they are only touched if ``state_value`` can be
        converted to a finite floating point number.
        """

        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return DeletionSummary()

        statistics_metadata_id = self.get_statistic_id(entity_id)

        try:
            deleted_states = self._execute_delete(
                "DELETE FROM states WHERE metadata_id = ? AND state = ?",
                (metadata_id, state_value),
            )

            deleted_stats = 0
            deleted_short = 0

            numeric_value = self._coerce_state_to_float(state_value)

            if statistics_metadata_id is not None and numeric_value is not None:
                deleted_stats = self._execute_delete(
                    """
                    DELETE FROM statistics
                    WHERE metadata_id = ? AND (
                        state = ? OR min = ? OR max = ? OR mean = ?
                    )
                    """,
                    (
                        statistics_metadata_id,
                        numeric_value,
                        numeric_value,
                        numeric_value,
                        numeric_value,
                    ),
                )

                deleted_short = self._execute_delete(
                    """
                    DELETE FROM statistics_short_term
                    WHERE metadata_id = ? AND (
                        state = ? OR min = ? OR max = ? OR mean = ?
                    )
                    """,
                    (
                        statistics_metadata_id,
                        numeric_value,
                        numeric_value,
                        numeric_value,
                        numeric_value,
                    ),
                )

            self.conn.commit()

            return DeletionSummary(
                states=deleted_states,
                statistics=deleted_stats,
                statistics_short_term=deleted_short,
            )

        except sqlite3.DatabaseError:
            self.conn.rollback()
            raise

    def get_state_deletion_preview(
        self, entity_id: str, state_value: str, *, sample_limit: int = 5
    ) -> StateDeletionPreview | None:
        """Return a summary of rows that would be deleted for ``state_value``."""

        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return None

        summary_cursor = self.conn.execute(
            """
            SELECT
                COUNT(*) AS count,
                MIN(last_updated_ts) AS first_seen_ts,
                MAX(last_updated_ts) AS last_seen_ts,
                MIN(last_updated) AS first_seen,
                MAX(last_updated) AS last_seen
            FROM states
            WHERE metadata_id = ? AND state = ?
            """,
            (metadata_id, state_value),
        )
        summary_row = summary_cursor.fetchone()

        states_count = int(summary_row["count"]) if summary_row and summary_row["count"] else 0
        first_seen_ts = (
            float(summary_row["first_seen_ts"])
            if summary_row and summary_row["first_seen_ts"] is not None
            else None
        )
        last_seen_ts = (
            float(summary_row["last_seen_ts"])
            if summary_row and summary_row["last_seen_ts"] is not None
            else None
        )
        first_seen = summary_row["first_seen"] if summary_row else None
        last_seen = summary_row["last_seen"] if summary_row else None

        sample_cursor = self.conn.execute(
            """
            SELECT state_id, state, last_updated, last_updated_ts
            FROM states
            WHERE metadata_id = ? AND state = ?
            ORDER BY COALESCE(last_updated_ts, 0) DESC
            LIMIT ?
            """,
            (metadata_id, state_value, sample_limit),
        )
        examples = tuple(sample_cursor.fetchall())

        statistics_metadata_id = self.get_statistic_id(entity_id)
        numeric_value = self._coerce_state_to_float(state_value)

        statistics_count = 0
        statistics_short_term_count = 0

        if statistics_metadata_id is not None and numeric_value is not None:
            for table_name in ("statistics", "statistics_short_term"):
                cursor = self.conn.execute(
                    f"""
                    SELECT COUNT(*) AS count
                    FROM {table_name}
                    WHERE metadata_id = ? AND (
                        state = ? OR min = ? OR max = ? OR mean = ?
                    )
                    """,
                    (
                        statistics_metadata_id,
                        numeric_value,
                        numeric_value,
                        numeric_value,
                        numeric_value,
                    ),
                )
                count = cursor.fetchone()["count"]

                if table_name == "statistics":
                    statistics_count = int(count)
                else:
                    statistics_short_term_count = int(count)

        return StateDeletionPreview(
            states_count=states_count,
            statistics_count=statistics_count,
            statistics_short_term_count=statistics_short_term_count,
            first_seen_ts=first_seen_ts,
            last_seen_ts=last_seen_ts,
            first_seen=first_seen,
            last_seen=last_seen,
            examples=examples,
        )

    def delete_state_by_id(self, entity_id: str, state_id: int) -> bool:
        """Delete a single ``states`` row identified by ``state_id``."""

        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return False

        try:
            deleted_rows = self._execute_delete(
                "DELETE FROM states WHERE metadata_id = ? AND state_id = ?",
                (metadata_id, state_id),
            )
            self.conn.commit()
        except sqlite3.DatabaseError:
            self.conn.rollback()
            raise

        return deleted_rows > 0

    def list_all_sensors(self):
        cur = self.conn.execute(
            "SELECT entity_id, metadata_id FROM states_meta ORDER BY entity_id"
        )
        return cur.fetchall()

    def get_unique_values(self, entity_id: str) -> list[str]:
        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return []
        cur = self.conn.execute(
            "SELECT DISTINCT state FROM states WHERE metadata_id = ? ORDER BY state",
            (metadata_id,),
        )
        return [row["state"] for row in cur.fetchall()]

    def get_value_statistics(self, entity_id: str) -> list[ValueStatistics]:
        """Return grouped statistics for all values of ``entity_id``."""

        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return []

        cursor = self.conn.execute(
            """
            SELECT
                state,
                COUNT(*) AS count,
                MIN(last_updated_ts) AS first_seen_ts,
                MAX(last_updated_ts) AS last_seen_ts,
                MIN(last_updated) AS first_seen,
                MAX(last_updated) AS last_seen
            FROM states
            WHERE metadata_id = ?
            GROUP BY state
            ORDER BY count DESC, state ASC
            """,
            (metadata_id,),
        )

        stats: list[ValueStatistics] = []
        for row in cursor.fetchall():
            stats.append(
                ValueStatistics(
                    state=row["state"],
                    count=int(row["count"]),
                    first_seen_ts=float(row["first_seen_ts"]) if row["first_seen_ts"] is not None else None,
                    last_seen_ts=float(row["last_seen_ts"]) if row["last_seen_ts"] is not None else None,
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                )
            )

        return stats

    def get_raw_states(self, entity_id: str, limit: int = 200):
        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return []
        cur = self.conn.execute(
            """
            SELECT state_id, state, last_updated, last_updated_ts
            FROM states
            WHERE metadata_id = ?
            ORDER BY COALESCE(last_updated_ts, 0) DESC
            LIMIT ?
            """,
            (metadata_id, limit),
        )
        return cur.fetchall()

    def list_states_by_id(self, metadata_id: int, limit: int = 200):
        cur = self.conn.execute(
            """
            SELECT state_id, state, last_updated, last_updated_ts
            FROM states
            WHERE metadata_id = ?
            ORDER BY COALESCE(last_updated_ts, 0) DESC
            LIMIT ?
            """,
            (metadata_id, limit),
        )
        return cur.fetchall()

    def find_states_for_value(
        self,
        entity_id: str,
        state_value: str,
        *,
        tolerance: float = 0.01,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        """Return rows whose state matches ``state_value`` (with tolerance)."""

        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return []

        rows: list[sqlite3.Row] = []
        seen_state_ids: set[int] = set()

        cursor = self.conn.execute(
            """
            SELECT state_id, state, last_updated, last_updated_ts
            FROM states
            WHERE metadata_id = ? AND state = ?
            ORDER BY COALESCE(last_updated_ts, 0) DESC
            LIMIT ?
            """,
            (metadata_id, state_value, limit),
        )
        exact_matches = cursor.fetchall()
        for row in exact_matches:
            rows.append(row)
            seen_state_ids.add(row["state_id"])

        numeric_value = self._coerce_state_to_float(state_value)
        tolerance = abs(tolerance)

        if numeric_value is None or tolerance == 0:
            return rows

        candidate_cursor = self.conn.execute(
            """
            SELECT state_id, state, last_updated, last_updated_ts
            FROM states
            WHERE metadata_id = ?
            ORDER BY ABS(CAST(state AS REAL) - ?), COALESCE(last_updated_ts, 0) DESC
            LIMIT ?
            """,
            (metadata_id, numeric_value, limit * 3),
        )

        for row in candidate_cursor.fetchall():
            state_id = row["state_id"]
            if state_id in seen_state_ids:
                continue

            row_value = self._coerce_state_to_float(row["state"])
            if row_value is None:
                continue

            if math.isfinite(row_value) and abs(row_value - numeric_value) <= tolerance:
                rows.append(row)
                seen_state_ids.add(state_id)

            if len(rows) >= limit:
                break

        rows.sort(
            key=lambda r: (
                r["last_updated_ts"] if r["last_updated_ts"] is not None else 0,
                r["last_updated"] if r["last_updated"] is not None else "",
            ),
            reverse=True,
        )

        return rows

    def get_state_context(
        self,
        entity_id: str,
        state_id: int,
        *,
        before: int = 2,
        after: int = 2,
    ) -> tuple[list[sqlite3.Row], sqlite3.Row | None, list[sqlite3.Row]]:
        """Return rows surrounding the provided ``state_id`` for an entity."""

        before = max(0, before)
        after = max(0, after)

        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return ([], None, [])

        anchor = self.conn.execute(
            """
            SELECT state_id, state, last_updated, last_updated_ts
            FROM states
            WHERE metadata_id = ? AND state_id = ?
            """,
            (metadata_id, state_id),
        ).fetchone()

        if anchor is None:
            return ([], None, [])

        before_rows = self.conn.execute(
            """
            SELECT state_id, state, last_updated, last_updated_ts
            FROM states
            WHERE metadata_id = ? AND state_id < ?
            ORDER BY state_id DESC
            LIMIT ?
            """,
            (metadata_id, state_id, before),
        ).fetchall()
        before_rows.reverse()

        after_rows = self.conn.execute(
            """
            SELECT state_id, state, last_updated, last_updated_ts
            FROM states
            WHERE metadata_id = ? AND state_id > ?
            ORDER BY state_id ASC
            LIMIT ?
            """,
            (metadata_id, state_id, after),
        ).fetchall()

        return (before_rows, anchor, after_rows)

    def close(self) -> None:
        self.conn.close()
