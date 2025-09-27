"""Interactive CLI for the Home Assistant recorder database fixer."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterable
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

HELP_TEXT = textwrap.dedent(
    """
    Available commands:

      sensor list_all                    - List all sensors with their metadata_id
      sensor find <entity_id>            - Show metadata_id + quick state preview
      sensor values <entity_id>          - Show all unique state values of a sensor
      sensor raw <entity_id>             - Show last 200 raw records for a sensor
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
            print(f"  {state['last_updated']} → {state['state']} (id: {state['state_id']})")

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
            print(f"  {row['last_updated']} → {row['state']} (id: {row['state_id']})")

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
