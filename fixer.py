"""Utilities for cleaning up Home Assistant recorder databases."""

from __future__ import annotations

import math
import os
import sqlite3
from typing import Iterable, List, Optional


class RecorderFixer:
    """Convenience wrapper around the Home Assistant recorder database."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path}")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def __enter__(self) -> "RecorderFixer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.close()

    def get_metadata_id(self, entity_id: str) -> Optional[int]:
        """Return the ``states_meta.metadata_id`` for the given entity."""

        cur = self.conn.execute(
            "SELECT metadata_id FROM states_meta WHERE entity_id = ?",
            (entity_id,),
        )
        row = cur.fetchone()
        return row["metadata_id"] if row else None

    def get_statistic_id(self, entity_id: str) -> Optional[int]:
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
    def _coerce_state_to_float(state_value: str) -> Optional[float]:
        """Convert a state value to ``float`` if possible."""

        try:
            value = float(state_value)
        except (TypeError, ValueError):
            return None

        return value if math.isfinite(value) else None

    def delete_state_everywhere(self, entity_id: str, state_value: str) -> int:
        """Remove matching state rows from recorder tables.

        The method deletes rows from ``states``, ``statistics`` and
        ``statistics_short_term`` that belong to ``entity_id`` and match the
        provided ``state_value``. The statistics tables only store numeric
        values, therefore they are only touched if ``state_value`` can be
        converted to a finite floating point number.
        """

        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            print(f"Sensor '{entity_id}' not found in states_meta.")
            return 0

        statistics_metadata_id = self.get_statistic_id(entity_id)
        total_deleted = 0

        try:
            deleted_states = self._execute_delete(
                "DELETE FROM states WHERE metadata_id = ? AND state = ?",
                (metadata_id, state_value),
            )
            total_deleted += deleted_states

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
                total_deleted += deleted_stats

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
                total_deleted += deleted_short

            self.conn.commit()

            print(f"Deleted {deleted_states} records from 'states'")
            print(f"Deleted {deleted_stats} records from 'statistics'")
            print(f"Deleted {deleted_short} records from 'statistics_short_term'")
            print(f"Total deleted records: {total_deleted}")

            return total_deleted

        except sqlite3.DatabaseError as exc:
            print(f"Database error during deletion: {exc}")
            self.conn.rollback()
            return 0

    def list_all_sensors(self):
        cur = self.conn.execute(
            "SELECT entity_id, metadata_id FROM states_meta ORDER BY entity_id"
        )
        return cur.fetchall()

    def get_unique_values(self, entity_id: str) -> List[str]:
        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return []
        cur = self.conn.execute(
            "SELECT DISTINCT state FROM states WHERE metadata_id = ? ORDER BY state",
            (metadata_id,),
        )
        return [row["state"] for row in cur.fetchall()]

    def get_raw_states(self, entity_id: str, limit: int = 200):
        metadata_id = self.get_metadata_id(entity_id)
        if metadata_id is None:
            return []
        cur = self.conn.execute(
            """
            SELECT state_id, state, last_updated
            FROM states
            WHERE metadata_id = ?
            ORDER BY last_updated DESC
            LIMIT ?
            """,
            (metadata_id, limit),
        )
        return cur.fetchall()

    def list_states_by_id(self, metadata_id: int, limit: int = 200):
        cur = self.conn.execute(
            """
            SELECT state_id, state, last_updated
            FROM states
            WHERE metadata_id = ?
            ORDER BY last_updated DESC
            LIMIT ?
            """,
            (metadata_id, limit),
        )
        return cur.fetchall()

    def close(self) -> None:
        self.conn.close()
