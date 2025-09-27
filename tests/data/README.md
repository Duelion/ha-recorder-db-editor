# Test Data Overview

This directory contains Home Assistant recorder databases that can be used to manually test the editor CLI. No datasets are committed to the repository so you can bring your own sample without bloating the history with large binaries.

## Adding `home-assistant_v2.db`

1. Download the recorder database from [`pia2209/config`](https://github.com/pia2209/config/raw/refs/heads/main/home-assistant_v2.db).
2. Place the file in this directory so it sits alongside this README (`tests/data/home-assistant_v2.db`).
3. Re-run the test suite. The pytest module automatically copies the database into a temporary directory for each test to keep the original pristine.

If you prefer to keep the dataset elsewhere, set the `RECORDER_FIXER_TEST_DB` environment variable to an absolute path before invoking pytest.
