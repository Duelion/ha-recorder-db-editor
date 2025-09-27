#!/bin/bash
set -euo pipefail

umask 077

echo "Homeassistant Recorder Database Editor"

mkdir -p /etc/dropbear

for keytype in rsa ecdsa ed25519; do
  keyfile="/etc/dropbear/dropbear_${keytype}_host_key"
  if [ ! -f "$keyfile" ]; then
    echo "[INFO] Generating $keytype key..."
    dropbearkey -t "$keytype" -f "$keyfile"
  fi
done

if [ ! -e /home/debug/config ]; then
  ln -s /config /home/debug/config
fi
chown -h debug:debug /home/debug/config 2>/dev/null || true

CONFIG_PATH="/data/options.json"
SSH_PORT="${HASSIO_HOST_NETWORK_2233_TCP_PORT:-2233}"

SSH_ENABLED="false"
CONFIGURED_PASSWORD=""

if [ -f "$CONFIG_PATH" ]; then
  SSH_ENABLED=$(jq -r '(.enable_debug_shell // false) | tostring' "$CONFIG_PATH" 2>/dev/null || echo "false")
  CONFIGURED_PASSWORD=$(jq -r '.debug_password // ""' "$CONFIG_PATH" 2>/dev/null || echo "")
fi

if [ -z "$CONFIGURED_PASSWORD" ] && [ -n "${DEBUG_PASSWORD:-}" ]; then
  CONFIGURED_PASSWORD="$DEBUG_PASSWORD"
fi

if [ "$SSH_ENABLED" = "true" ]; then
    if [ -z "$CONFIGURED_PASSWORD" ]; then
        echo "[ERROR] enable_debug_shell is true but no debug_password provided. SSH access will remain disabled."
    else
        echo "[INFO] SSH debug shell enabled"
        echo "debug:${CONFIGURED_PASSWORD}" | chpasswd
        unset CONFIGURED_PASSWORD DEBUG_PASSWORD
        # The debug user intentionally runs with UID 0 so it can manage
        # recorder files owned by root.  Dropbear's "-w" flag forbids any
        # UID 0 password logins, which would also block the debug account.
        # Avoid that flag so the debug shell remains accessible while the
        # root account itself stays locked.
        /usr/sbin/dropbear -E -p "$SSH_PORT" &
    fi
else
    echo "[INFO] SSH debug shell is disabled"
fi

# Wait forever for the container not to end
while true; do
    sleep 3600
done
