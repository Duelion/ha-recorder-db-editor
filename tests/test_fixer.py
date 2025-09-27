import os
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
