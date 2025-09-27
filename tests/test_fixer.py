import os
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fixer import RecorderFixer

_DEFAULT_DB = Path(__file__).resolve().parent / "data" / "home-assistant_v2.db"
TEST_DB = Path(os.environ.get("RECORDER_FIXER_TEST_DB", _DEFAULT_DB))

if not TEST_DB.exists():
    pytest.skip(
        "Recorder test database not found. Download the dataset into tests/data/ "
        "or set RECORDER_FIXER_TEST_DB to an existing recorder DB file.",
        allow_module_level=True,
    )


@pytest.fixture
def fresh_db_path(tmp_path):
    """Copy the recorder DB so every test starts from a clean slate."""
    db_copy = tmp_path / "home-assistant_v2.db"
    shutil.copy(TEST_DB, db_copy)
    return db_copy


@pytest.fixture
def fixer(fresh_db_path):
    instance = RecorderFixer(str(fresh_db_path))
    try:
        yield instance
    finally:
        instance.close()


def test_get_metadata_id_returns_expected_value(fixer):
    assert fixer.get_metadata_id("zone.home") == 1


def test_get_unique_values_lists_known_binary_sensor_states(fixer):
    assert fixer.get_unique_values("binary_sensor.fritzbox_pia_verbindung") == [
        "on",
        "unavailable",
    ]


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
    assert deleted == before

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
