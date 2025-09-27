# Home Assistant Recorder DB Editor (CLI)

🔧 **A command-line tool for direct editing of Home Assistant's `home-assistant_v2.db` SQLite database.**
Primarily used to clean up unwanted sensor values — including all traces from `states`, `statistics`, and `statistics_short_term` — so they disappear even from mini-graphs.

> ℹ️ **Fork notice:** This project is a fork of
> [`mamontuka/ha-recorder-db-editor`](https://github.com/mamontuka/ha-recorder-db-editor).
> The goal of this fork is to keep the code accessible for experimentation with Codex tooling.

---

## ⚠️ WARNING
Before using this tool, **make sure you have a backup of your database**.  
This add-on **does NOT provide backup or restore functionality**, and is **not responsible** for any data loss.


## 🔧 Installation

1. Add this repository to the **Home Assistant Add-on Store** using `https://github.com/Duelion/ha-recorder-db-editor`.
2. Install the **Home Assistant Recorder DB Editor**

### ✅ Enable Shell Access

1. Go to **Home Assistant > Settings > Add-ons > Home Assistant Recorder DB Editor**.
2. Open the **Configuration** tab.
3. Enable the following option (if disabled) **and set a strong password**:

```yaml
enable_debug_shell: true
debug_password: "<CHOOSE_A_STRONG_PASSWORD>"
```

4. Save and restart the add-on.
5. Change the password regularly from inside the CLI using the `password` command.

### 🔐 Connect via SSH Client

Use any SSH client (e.g. `ssh`, PuTTY, MobaXterm) and connect to your Home Assistant host:

```bash
ssh debug@<HOME_ASSISTANT_IP> -p <EXPOSED_PORT>
```

- **Username:** `debug`
- **Password:** value from `debug_password` in the add-on configuration
- **Port:** must be mapped in your add-on or container settings

> ℹ️ **Docker Compose users:** copy `options.example.json` to `options.json`, set `enable_debug_shell` and `debug_password`, and mount it to `/data/options.json` (read-only) as shown in `docker-compose.yaml`.

---

## 🚀 Quick Start

When launched, you'll see a warning message:

```
===  IMPORTANT NOTICE ===
BEFORE YOU USE THIS TOOL:
MAKE SURE TO BACKUP YOUR HOME ASSISTANT DATABASE USING STANDARD BACKUP METHODS!
THIS TOOL DOES NOT PROVIDE BACKUP OR RESTORE FUNCTIONALITY AND IS NOT RESPONSIBLE FOR DATA LOSS.

Type 'agree' and press Enter to continue, or 'exit' to quit.
```

Type `agree` to proceed to CLI mode.  
Enter path to HA database or press ENTER key for confirm default `/config/home-assistant_v2.db`.

---

## 💻 Available Commands

### Sensor Commands

| Command                                   | Description |
|------------------------------------------|-------------|
| `sensor list_all`                        | List all sensors and their `metadata_id`. |
| `sensor find <entity_id>`                | Show `metadata_id` and recent state records. |
| `sensor values <entity_id>`              | List all unique values stored for the sensor. |
| `sensor raw <entity_id>`                 | Show 200 recent raw `states` records. |
| `sensor delete <entity_id> <value>`      | Completely delete value from `states`, `statistics`, and `statistics_short_term`. |

---

### System Commands

| Command        | Description |
|----------------|-------------|
| `password`     | Change password for `debug` user. |
| `clear`        | Clear the screen. |
| `help`         | Show command help. |
| `exit`         | Exit the CLI. |

---

## 🐳 Details

- Written in Python 3.9
- Uses `sqlite3` for direct database access
- CLI powered by `prompt_toolkit` with autocompletion and history support
- Can be extended or embedded in larger add-ons

---

## 📂 Example Usage

```bash
fixer> sensor find sensor.outdoor_temperature
metadata_id for 'sensor.outdoor_temperature' is 42

fixer> sensor values sensor.outdoor_temperature
Found 3 unique values:
  21.2
  21.3
  -72.4

fixer> sensor delete sensor.outdoor_temperature -72.4
Deleted 3 entries from states.
Deleted 1 entry from statistics.
Deleted 2 entries from statistics_short_term.
```

---

## 🧠 Notes

- The SSH debug shell is disabled by default. You must explicitly enable it and set `debug_password` in the add-on configuration before remote access is allowed.
- If values still show up on mini-graphs after deletion, check `statistics_short_term` entries — especially `min`, `max`, `mean`.
- Restart Home Assistant after modifications to ensure the frontend reflects the changes.

---

## 🛠️ Development

Install the development dependencies and run the linters/tests before opening a pull request:

```bash
pip install -r requirements-dev.txt
ruff check
pytest
```

---

## 🧪 Tested On

- Home Assistant Core 2024.6+
- SQLite database schema version 43+
- Container uses `python:3.9-slim` and Dropbear for optional SSH

---

**Built for Home Assistant power users. Use with care.**
