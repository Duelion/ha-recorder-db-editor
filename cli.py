"""Interactive CLI for the Home Assistant recorder database fixer."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter

from fixer import DeletionSummary, RecorderFixer

DEFAULT_DB_PATH = Path("/config/home-assistant_v2.db")

WARNING_TEXT = textwrap.dedent(
    """
    ===  IMPORTANT NOTICE ===
    BEFORE YOU USE THIS TOOL:
    MAKE SURE TO BACKUP YOUR HOME ASSISTANT DATABASE USING STANDARD BACKUP METHODS!
    THIS TOOL DOES NOT PROVIDE BACKUP OR RESTORE FUNCTIONALITY AND IS NOT RESPONSIBLE FOR DATA LOSS.

    Type 'agree' and press Enter to continue, or 'exit' to quit.
    """
)

PLACEHOLDER_STATES = {
    "unknown",
    "unavailable",
    "undefined",
    "none",
    "null",
    "nan",
}

HELP_TEXT = textwrap.dedent(
    """
    Available commands:

      sensor list_all                    - List all sensors with their metadata_id
      sensor find <entity_id>            - Show metadata_id + quick state preview
      sensor values <entity_id>          - Show all unique state values of a sensor
      sensor raw <entity_id>             - Show last 200 raw records for a sensor
      sensor find_value <entity_id> <value> [tolerance]
                                        - Show records close to a value
      sensor around <entity_id> <value> [tolerance] [window]
                                        - Show nearby records for candidate values
      sensor delete <entity_id> <value>  - Delete entries with specific state value

      password                           - Change password for user 'debug'
      clear                              - Clear the screen
      help                               - Show this help message
      exit                               - Exit the shell
    """
)


def build_completer(entity_ids: Iterable[str]) -> NestedCompleter:
    """Create a :class:`NestedCompleter` for the supported commands."""

    entity_completer = {entity_id: None for entity_id in entity_ids}
    sensor_completer = {
        "delete": entity_completer,
        "values": entity_completer,
        "raw": entity_completer,
        "around": entity_completer,
        "find_value": entity_completer,
        "find": entity_completer,
        "list_all": None,
    }

    return NestedCompleter.from_nested_dict(
        {
            "sensor": sensor_completer,
            "clear": None,
            "help": None,
            "exit": None,
            "password": None,
        }
    )


def change_debug_password() -> None:
    """Invoke the system password change utility for the ``debug`` user."""

    print("Change password for user 'debug':")
    print("You will be prompted by the system 'passwd' tool.")
    try:
        subprocess.run(["passwd"], check=True)
        print("Password successfully changed for user 'debug'.")
    except subprocess.CalledProcessError:
        print(
            "Failed to change password. Please review the messages above and try again."
        )


class RecorderCli:
    """Interactive prompt for manipulating recorder data."""

    def __init__(self, fixer: RecorderFixer) -> None:
        self._fixer = fixer
        self._session = PromptSession()
        self._entity_ids: list[str] = []

    # ------------------------------------------------------------------
    # lifecycle helpers
    def run(self) -> None:
        """Start the interactive CLI loop."""

        self._refresh_entity_ids()
        self._print_help()

        while True:
            try:
                line = self._session.prompt(
                    "fixer> ", completer=build_completer(self._entity_ids)
                )
            except KeyboardInterrupt:
                print("\nType 'exit' to quit.")
                continue
            except EOFError:
                print("\nExit.")
                break

            if not line.strip():
                continue

            self._dispatch(line)

    def _refresh_entity_ids(self) -> None:
        self._entity_ids = sorted(row["entity_id"] for row in self._fixer.list_all_sensors())

    # ------------------------------------------------------------------
    # command handling
    def _dispatch(self, line: str) -> None:
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            print(f"Unable to parse command: {exc}")
            return

        if not parts:
            return

        command = parts[0]

        if command == "exit":
            raise SystemExit

        handlers: dict[str, Callable[[list[str]], None]] = {
            "help": lambda args: self._print_help(),
            "clear": lambda args: self._clear_screen(),
            "sensor": self._handle_sensor_command,
            "password": lambda args: change_debug_password(),
        }

        handler = handlers.get(command)
        if handler is None:
            print(f"Unknown command: {command}. Type 'help' for commands.")
            return

        try:
            handler(parts[1:])
        except SystemExit:
            raise
        except Exception as exc:  # pragma: no cover - defensive fallback
            print(f"Error during command execution: {exc}")

    def _print_help(self) -> None:
        print(HELP_TEXT)

    def _clear_screen(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")
        self._print_help()

    @staticmethod
    def _is_placeholder_state(state: object) -> bool:
        if state is None:
            return True

        text = str(state).strip()
        if not text:
            return True

        return text.lower() in PLACEHOLDER_STATES

    # ------------------------------------------------------------------
    # sensor commands
    def _handle_sensor_command(self, args: list[str]) -> None:
        if not args:
            print("Sensor command requires subcommand. Type 'help' for usage.")
            return

        subcommand = args[0]
        dispatch: dict[str, Callable[[], None]] = {
            "list_all": lambda: self._sensor_list_all(),
            "find": lambda: self._sensor_find(args),
            "values": lambda: self._sensor_values(args),
            "raw": lambda: self._sensor_raw(args),
            "around": lambda: self._sensor_around(args),
            "find_value": lambda: self._sensor_find_value(args),
            "delete": lambda: self._sensor_delete(args),
        }

        handler = dispatch.get(subcommand)
        if handler is None:
            print(f"Unknown sensor command: {subcommand}")
            return

        handler()

    def _sensor_list_all(self) -> None:
        sensors = self._fixer.list_all_sensors()
        if not sensors:
            print("No sensors found.")
            return

        for row in sensors:
            print(f"  {row['entity_id']} → {row['metadata_id']}")

    def _sensor_find(self, args: list[str]) -> None:
        entity_id = self._require_entity_id(args, usage="sensor find <entity_id>")
        if entity_id is None:
            return

        metadata_id = self._fixer.get_metadata_id(entity_id)
        if metadata_id is None:
            print(f"Sensor '{entity_id}' not found.")
            return

        print(f"metadata_id for '{entity_id}' is {metadata_id}")
        states = self._fixer.list_states_by_id(metadata_id)
        for state in states[:5]:
            print(
                "  "
                f"{self._format_timestamp(state)} → {state['state']} "
                f"(id: {state['state_id']})"
            )

    def _sensor_values(self, args: list[str]) -> None:
        entity_id = self._require_entity_id(args, usage="sensor values <entity_id>")
        if entity_id is None:
            return

        values = self._fixer.get_unique_values(entity_id)
        if not values:
            print(f"No values found for sensor '{entity_id}'.")
            return

        for value in values:
            print(f"  {value}")

    def _sensor_raw(self, args: list[str]) -> None:
        entity_id = self._require_entity_id(args, usage="sensor raw <entity_id>")
        if entity_id is None:
            return

        rows = self._fixer.get_raw_states(entity_id)
        if not rows:
            print(f"No data for sensor '{entity_id}'.")
            return

        for row in rows:
            print(
                "  "
                f"{self._format_timestamp(row)} → {row['state']} "
                f"(id: {row['state_id']})"
            )

    def _sensor_find_value(self, args: list[str]) -> None:
        if len(args) < 3:
            print("Usage: sensor find_value <entity_id> <value> [tolerance]")
            return

        entity_id = args[1]
        value = args[2]

        tolerance: float | None = None
        if len(args) >= 4:
            try:
                tolerance = float(args[3])
            except ValueError:
                print("Tolerance must be a numeric value.")
                return

        matches = self._fixer.find_states_for_value(
            entity_id,
            value,
            tolerance=tolerance if tolerance is not None else 0.01,
        )

        if not matches:
            print(
                f"No states close to '{value}' found for sensor '{entity_id}'."
            )
            return

        numeric_target: float | None = None
        try:
            numeric_target = float(value)
        except (TypeError, ValueError):
            numeric_target = None

        effective_tolerance = (
            tolerance if tolerance is not None else (0.01 if numeric_target is not None else 0.0)
        )

        if numeric_target is not None:
            print(f"Matches for '{value}' (±{effective_tolerance:.6g})")
        else:
            print(f"Matches for '{value}'")

        displayed = 0
        skipped = 0

        for row in matches:
            if self._is_placeholder_state(row["state"]):
                skipped += 1
                continue

            timestamp = self._format_timestamp(row)
            base = f"  {timestamp} → {row['state']} (id: {row['state_id']})"

            if numeric_target is not None:
                try:
                    diff = abs(float(row["state"]) - numeric_target)
                except (TypeError, ValueError):
                    diff = None
                if diff is not None:
                    base += f" [Δ={diff:.6g}]"

            print(base)
            displayed += 1

        if displayed == 0:
            if skipped:
                print("No non-placeholder states matched the criteria.")
            return

        if skipped:
            print(f"  (Skipped {skipped} placeholder state(s))")

    def _sensor_around(self, args: list[str]) -> None:
        if len(args) < 3:
            print(
                "Usage: sensor around <entity_id> <value> [tolerance] [window]"
            )
            return

        entity_id = args[1]
        value = args[2]

        tolerance: float | None = None
        window = 5

        if len(args) >= 4:
            try:
                tolerance = float(args[3])
            except ValueError:
                print("Tolerance must be a numeric value.")
                return

        if len(args) >= 5:
            try:
                window = int(args[4])
            except ValueError:
                print("Window must be an integer value.")
                return

            if window < 0:
                print("Window must be zero or greater.")
                return

        matches = self._fixer.find_states_for_value(
            entity_id,
            value,
            tolerance=tolerance if tolerance is not None else 0.01,
        )

        if not matches:
            print(
                f"No states close to '{value}' found for sensor '{entity_id}'."
            )
            return

        numeric_target: float | None = None
        try:
            numeric_target = float(value)
        except (TypeError, ValueError):
            numeric_target = None

        effective_tolerance = (
            tolerance if tolerance is not None else (0.01 if numeric_target is not None else 0.0)
        )

        header = (
            f"Exploring matches for '{value}' (±{effective_tolerance:.6g})"
            if numeric_target is not None
            else f"Exploring matches for '{value}'"
        )
        print(header)
        print(f"Window size: {window} before/after")

        display_index = 0
        skipped_candidates = 0
        skipped_neighbors = 0

        for row in matches:
            if self._is_placeholder_state(row["state"]):
                skipped_candidates += 1
                continue

            before_rows, anchor, after_rows = self._fixer.get_state_context(
                entity_id,
                row["state_id"],
                before=window,
                after=window,
            )

            if anchor is None:
                continue

            if self._is_placeholder_state(anchor["state"]):
                skipped_candidates += 1
                continue

            filtered_before = [
                record for record in before_rows if not self._is_placeholder_state(record["state"])
            ]
            filtered_after = [
                record for record in after_rows if not self._is_placeholder_state(record["state"])
            ]
            skipped_neighbors += (len(before_rows) - len(filtered_before)) + (
                len(after_rows) - len(filtered_after)
            )

            print(
                f"[{display_index + 1}] Candidate at {self._format_timestamp(anchor)}"
                f" → {anchor['state']} (id: {anchor['state_id']})"
            )
            display_index += 1

            def _format_row(prefix: str, record) -> str:
                line = (
                    f"    {prefix} {self._format_timestamp(record)} → {record['state']}"
                    f" (id: {record['state_id']})"
                )
                if numeric_target is not None:
                    try:
                        diff = abs(float(record["state"]) - numeric_target)
                    except (TypeError, ValueError):
                        diff = None
                    if diff is not None:
                        line += f" [Δ={diff:.6g}]"
                return line

            for before_row in filtered_before:
                print(_format_row("↑", before_row))

            print(_format_row("•", anchor))

            for after_row in filtered_after:
                print(_format_row("↓", after_row))

        if display_index == 0:
            if skipped_candidates:
                print("No non-placeholder states available within the selected window.")
            return

        notes: list[str] = []
        if skipped_candidates:
            notes.append(f"{skipped_candidates} candidate(s)")
        if skipped_neighbors:
            notes.append(f"{skipped_neighbors} neighbor state(s)")

        if notes:
            joined = " and ".join(notes)
            print(f"  (Skipped {joined} lacking meaningful data)")

    def _sensor_delete(self, args: list[str]) -> None:
        if len(args) != 3:
            print("Usage: sensor delete <entity_id> <value>")
            return

        entity_id = args[1]
        value = args[2]

        if self._fixer.get_metadata_id(entity_id) is None:
            print(f"Sensor '{entity_id}' not found.")
            return

        summary: DeletionSummary = self._fixer.delete_state_everywhere(entity_id, value)
        if summary.total == 0:
            print(
                f"No records matched entity '{entity_id}' with state '{value}'."
            )
        else:
            print(
                "Deleted "
                f"{summary.states} from states, "
                f"{summary.statistics} from statistics, "
                f"{summary.statistics_short_term} from statistics_short_term."
            )

        self._refresh_entity_ids()

    # ------------------------------------------------------------------
    # helpers
    @staticmethod
    def _require_entity_id(args: list[str], *, usage: str) -> str | None:
        if len(args) < 2:
            print(f"Usage: {usage}")
            return None
        return args[1]

    @staticmethod
    def _format_timestamp(row) -> str:
        value = None
        try:
            value = row["last_updated"]
        except (KeyError, TypeError):
            pass

        if value:
            return str(value)

        timestamp = None
        try:
            timestamp = row["last_updated_ts"]
        except (KeyError, TypeError):
            pass

        if timestamp is None:
            return "unknown"

        try:
            return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return str(timestamp)


def prompt_for_database_path(default_path: Path = DEFAULT_DB_PATH) -> Path | None:
    """Prompt the user for the path to the Home Assistant database."""

    prompt = (
        "Enter path to HA database or press ENTER key for confirm default "
        f"[{default_path}]: "
    )
    raw_value = input(prompt).strip()
    if not raw_value:
        return default_path

    path = Path(raw_value)
    if not path.is_file():
        print(f"Database file not found: {path}")
        return None

    return path


def ensure_user_consent() -> bool:
    """Display the safety warning and require explicit consent."""

    while True:
        print(WARNING_TEXT)
        choice = input("Your choice: ").strip().lower()
        if choice == "agree":
            return True
        if choice == "exit":
            print("Exit requested by user.")
            return False
        print("Invalid input. Please type 'agree' to continue or 'exit' to quit.\n")


def main() -> None:
    if not ensure_user_consent():
        return

    print("\nEntering CLI mode. Type 'help' to see commands.\n")
    db_path = prompt_for_database_path()
    if db_path is None:
        return

    try:
        fixer = RecorderFixer(str(db_path))
    except FileNotFoundError as exc:
        print(exc)
        return

    cli = RecorderCli(fixer)
    try:
        cli.run()
    except SystemExit:
        pass
    finally:
        fixer.close()


if __name__ == "__main__":
    sys.exit(main())
