import os
import shutil
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from fixer import RecorderFixer

DEFAULT_DATASET_URL = (
    "https://github.com/pia2209/config/raw/refs/heads/main/home-assistant_v2.db"
)


def _download_dataset(destination: Path) -> None:
    url_or_path = os.environ.get("RECORDER_FIXER_TEST_DB_URL", DEFAULT_DATASET_URL)
    candidate_path = Path(url_or_path)

    if candidate_path.exists():
        shutil.copy(candidate_path, destination)
        return

    try:
        with urllib.request.urlopen(url_or_path) as response, destination.open("wb") as target:
            shutil.copyfileobj(response, target)
    except (urllib.error.URLError, TimeoutError) as exc:
        pytest.skip(f"Unable to download recorder dataset from {url_or_path}: {exc}")



@pytest.fixture
def fresh_db_path(tmp_path):
    """Download a fresh recorder DB for every test run."""
    db_path = tmp_path / "home-assistant_v2.db"
    _download_dataset(db_path)
    return db_path


@pytest.fixture
def fixer(fresh_db_path):
    instance = RecorderFixer(str(fresh_db_path))
    try:
        yield instance
    finally:
        instance.close()


def test_get_metadata_id_returns_expected_value(fixer):
    assert fixer.get_metadata_id("zone.home") == 1


@pytest.mark.parametrize(
    ("entity_id", "expected_subset"),
    [
        (
            "binary_sensor.fritzbox_pia_verbindung",
            {"on", "unavailable"},
        ),
        (
            "sensor.heizung_wohnzimmer_batterie",
            {"72.0", "unavailable"},
        ),
        (
            "sensor.fritzbox_pia_gb_empfangen",
            {"29.4", "33.6", "39.4", "unavailable"},
        ),
    ],
)
def test_get_unique_values_lists_known_states(fixer, entity_id, expected_subset):
    values = fixer.get_unique_values(entity_id)
    assert values, "unique values should not be empty"
    assert expected_subset.issubset(set(values))


def test_get_value_statistics_returns_counts_and_ordering(fixer):
    stats = fixer.get_value_statistics("binary_sensor.fritzbox_pia_verbindung")

    assert stats, "expected aggregated statistics for sensor"
    assert stats[0].state in {"on", "unavailable"}
    # Ensure counts sum to the same length as unique values
    total_rows = sum(item.count for item in stats)
    assert total_rows > 0
    assert all(item.count >= stats[index + 1].count for index, item in enumerate(stats[:-1]))
    assert any(item.last_seen_ts is not None or item.last_seen for item in stats)


def test_find_states_for_value_returns_exact_matches(fixer):
    rows = fixer.find_states_for_value(
        "binary_sensor.fritzbox_pia_verbindung",
        "unavailable",
    )

    assert rows, "expected to find at least one unavailable state"
    assert all(row["state"] == "unavailable" for row in rows)
    assert "last_updated_ts" in rows[0].keys()


def test_find_states_for_value_accepts_float_tolerance(fixer):
    rows = fixer.find_states_for_value(
        "sensor.fritzbox_pia_gb_empfangen",
        "30.3004",
        tolerance=0.01,
    )

    assert rows, "expected to find states close to 30.3004"
    assert any(row["state"] == "30.3" for row in rows)


def test_get_state_context_returns_neighbors(fixer):
    rows = fixer.find_states_for_value(
        "sensor.fritzbox_pia_gb_empfangen",
        "30.3004",
        tolerance=0.02,
    )

    assert rows, "expected candidate states for context inspection"

    state_id = rows[0]["state_id"]
    before_rows, anchor, after_rows = fixer.get_state_context(
        "sensor.fritzbox_pia_gb_empfangen",
        state_id,
        before=2,
        after=2,
    )

    assert anchor is not None
    assert anchor["state_id"] == state_id

    previous_ids = [row["state_id"] for row in before_rows]
    assert previous_ids == sorted(previous_ids)
    assert all(row["state_id"] < state_id for row in before_rows)

    following_ids = [row["state_id"] for row in after_rows]
    assert following_ids == sorted(following_ids)
    assert all(row["state_id"] > state_id for row in after_rows)


def test_delete_state_everywhere_removes_matching_states(fixer, fresh_db_path):
    entity_id = "binary_sensor.fritzbox_pia_verbindung"
    state_value = "on"

    metadata_id = fixer.get_metadata_id(entity_id)
    assert metadata_id is not None

    with sqlite3.connect(fresh_db_path) as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM states WHERE metadata_id = ? AND state = ?",
            (metadata_id, state_value),
        ).fetchone()[0]
        assert before > 0

    deleted = fixer.delete_state_everywhere(entity_id, state_value)
    assert deleted.total >= before

    with sqlite3.connect(fresh_db_path) as conn:
        after = conn.execute(
            "SELECT COUNT(*) FROM states WHERE metadata_id = ? AND state = ?",
            (metadata_id, state_value),
        ).fetchone()[0]
        assert after == 0

        remaining = conn.execute(
            "SELECT COUNT(*) FROM states WHERE metadata_id = ? AND state = ?",
            (metadata_id, "unavailable"),
        ).fetchone()[0]
    assert remaining > 0


def _count_statistics(conn, table, meta_id, numeric_value):
    query = f"""
        SELECT COUNT(*) FROM {table}
        WHERE metadata_id = ? AND (
            state = ? OR min = ? OR max = ? OR mean = ?
        )
    """
    return conn.execute(
        query,
        (meta_id, numeric_value, numeric_value, numeric_value, numeric_value),
    ).fetchone()[0]


@pytest.mark.parametrize(
    ("entity_id", "state_value", "control_entity_id"),
    [
        (
            "sensor.heizung_wohnzimmer_batterie",
            "72.0",
            "sensor.heizung_schlafzimmer_batterie",
        ),
        (
            "sensor.heizung_schlafzimmer_batterie",
            "66.0",
            "sensor.heizung_buro1_batterie",
        ),
    ],
)
def test_delete_state_everywhere_removes_statistics_rows(
    fixer, fresh_db_path, entity_id, state_value, control_entity_id
):
    metadata_id = fixer.get_metadata_id(entity_id)
    statistics_metadata_id = fixer.get_statistic_id(entity_id)
    control_statistics_metadata_id = fixer.get_statistic_id(control_entity_id)
    numeric_value = float(state_value)

    assert metadata_id is not None
    assert statistics_metadata_id is not None
    assert control_statistics_metadata_id is not None

    with sqlite3.connect(fresh_db_path) as conn:
        before_states = conn.execute(
            "SELECT COUNT(*) FROM states WHERE metadata_id = ? AND state = ?",
            (metadata_id, state_value),
        ).fetchone()[0]
        before_stats = _count_statistics(
            conn, "statistics", statistics_metadata_id, numeric_value
        )
        before_short = _count_statistics(
            conn, "statistics_short_term", statistics_metadata_id, numeric_value
        )
        control_stats_before = _count_statistics(
            conn, "statistics", control_statistics_metadata_id, numeric_value
        )
        control_short_before = _count_statistics(
            conn,
            "statistics_short_term",
            control_statistics_metadata_id,
            numeric_value,
        )

    assert before_states > 0
    assert before_stats > 0
    assert before_short > 0
    assert control_stats_before > 0
    assert control_short_before > 0

    summary = fixer.delete_state_everywhere(entity_id, state_value)

    with sqlite3.connect(fresh_db_path) as conn:
        after_states = conn.execute(
            "SELECT COUNT(*) FROM states WHERE metadata_id = ? AND state = ?",
            (metadata_id, state_value),
        ).fetchone()[0]
        after_stats = _count_statistics(
            conn, "statistics", statistics_metadata_id, numeric_value
        )
        after_short = _count_statistics(
            conn, "statistics_short_term", statistics_metadata_id, numeric_value
        )
        control_stats_after = _count_statistics(
            conn, "statistics", control_statistics_metadata_id, numeric_value
        )
        control_short_after = _count_statistics(
            conn,
            "statistics_short_term",
            control_statistics_metadata_id,
            numeric_value,
        )

    assert after_states == 0
    assert after_stats == 0
    assert after_short == 0
    assert summary.states == before_states
    assert summary.statistics == before_stats
    assert summary.statistics_short_term == before_short
    assert control_stats_after == control_stats_before
    assert control_short_after == control_short_before


def test_delete_state_everywhere_skips_statistics_for_non_numeric_state(
    fixer, fresh_db_path
):
    entity_id = "sensor.fritzbox_pia_download_geschwindigkeit"
    state_value = "unknown"

    metadata_id = fixer.get_metadata_id(entity_id)
    statistics_metadata_id = fixer.get_statistic_id(entity_id)

    assert metadata_id is not None
    assert statistics_metadata_id is not None

    with sqlite3.connect(fresh_db_path) as conn:
        before_states = conn.execute(
            "SELECT COUNT(*) FROM states WHERE metadata_id = ? AND state = ?",
            (metadata_id, state_value),
        ).fetchone()[0]
        before_stats = conn.execute(
            "SELECT COUNT(*) FROM statistics WHERE metadata_id = ?",
            (statistics_metadata_id,),
        ).fetchone()[0]
        before_short = conn.execute(
            "SELECT COUNT(*) FROM statistics_short_term WHERE metadata_id = ?",
            (statistics_metadata_id,),
        ).fetchone()[0]

    assert before_states > 0
    assert before_stats > 0
    assert before_short > 0

    deleted = fixer.delete_state_everywhere(entity_id, state_value)

    with sqlite3.connect(fresh_db_path) as conn:
        after_states = conn.execute(
            "SELECT COUNT(*) FROM states WHERE metadata_id = ? AND state = ?",
            (metadata_id, state_value),
        ).fetchone()[0]
        after_stats = conn.execute(
            "SELECT COUNT(*) FROM statistics WHERE metadata_id = ?",
            (statistics_metadata_id,),
        ).fetchone()[0]
        after_short = conn.execute(
            "SELECT COUNT(*) FROM statistics_short_term WHERE metadata_id = ?",
            (statistics_metadata_id,),
        ).fetchone()[0]

    assert deleted.states == before_states
    assert deleted.statistics == 0
    assert deleted.statistics_short_term == 0
    assert after_states == 0
    assert after_stats == before_stats
    assert after_short == before_short


def test_delete_state_by_id_removes_single_row(fixer, fresh_db_path):
    entity_id = "sensor.fritzbox_pia_gb_empfangen"
    rows = fixer.get_raw_states(entity_id, limit=10)

    assert rows, "expected raw states for the sensor"

    target = rows[0]
    target_state_id = target["state_id"]
    target_state_value = target["state"]

    metadata_id = fixer.get_metadata_id(entity_id)
    assert metadata_id is not None

    with sqlite3.connect(fresh_db_path) as conn:
        before_exact = conn.execute(
            "SELECT COUNT(*) FROM states WHERE state_id = ?",
            (target_state_id,),
        ).fetchone()[0]
        before_value = conn.execute(
            "SELECT COUNT(*) FROM states WHERE metadata_id = ? AND state = ?",
            (metadata_id, target_state_value),
        ).fetchone()[0]

    assert before_exact == 1
    assert before_value >= 1

    assert fixer.delete_state_by_id(entity_id, target_state_id) is True

    with sqlite3.connect(fresh_db_path) as conn:
        after_exact = conn.execute(
            "SELECT COUNT(*) FROM states WHERE state_id = ?",
            (target_state_id,),
        ).fetchone()[0]
        after_value = conn.execute(
            "SELECT COUNT(*) FROM states WHERE metadata_id = ? AND state = ?",
            (metadata_id, target_state_value),
        ).fetchone()[0]

    assert after_exact == 0
    assert after_value == before_value - 1

    assert fixer.delete_state_by_id(entity_id, target_state_id) is False
