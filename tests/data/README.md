# Test Data Overview

This directory can host Home Assistant recorder databases that you want to inspect manually while working on the editor CLI. No datasets are committed to the repository so you can bring your own sample without bloating the history with large binaries.

## Using the automated test dataset

The pytest suite downloads a fresh copy of [`home-assistant_v2.db`](https://github.com/pia2209/config/raw/refs/heads/main/home-assistant_v2.db) for every test. Nothing needs to be checked into the repository and each test starts from a pristine database.

If you want to override the dataset source, set the `RECORDER_FIXER_TEST_DB_URL` environment variable to a custom URL or an absolute path to a local recorder database before invoking pytest.
