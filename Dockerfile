FROM python:3.9-slim

ENV HASSIO_DATA_PATH=/data

# Install the required packages
RUN apt-get update && apt-get install -y --no-install-recommends apt-utils

RUN apt-get update && apt-get install -y --no-install-recommends \
    dropbear \
    jq \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# === Disable Debian MOTD ===
RUN rm -f /etc/motd /etc/motd.dynamic /run/motd.dynamic && \
    rm -rf /etc/update-motd.d
# ============================

# Create a directory for dropbear keys
RUN mkdir -p /etc/dropbear

# Remove existing debug user if exists
RUN userdel debug || true

# Create dedicated non-root debug user
RUN useradd -m -d /home/debug -s /bin/bash debug && \
    passwd -l debug

# Copy the shell autostart script for debug
COPY start_recorder_shell.sh /usr/local/bin/start_recorder_shell.sh
RUN chmod +x /usr/local/bin/start_recorder_shell.sh

# Add shell autostart to debug user's .bashrc
RUN grep -qxF 'if [ "$USER" = "debug" ]; then exec /usr/local/bin/start_recorder_shell.sh; fi' /home/debug/.bashrc || \
    echo 'if [ "$USER" = "debug" ]; then exec /usr/local/bin/start_recorder_shell.sh; fi' >> /home/debug/.bashrc
RUN chown -R debug:debug /home/debug && \
    chmod 750 /home/debug

# Copy the program scripts into the container
COPY fixer.py cli.py /recorder_fixer/
COPY run.sh /

RUN chmod a+x /run.sh
RUN chown -R debug:debug /home/debug /recorder_fixer

# Install python dependencies
RUN pip3 install --no-cache-dir pyyaml prompt_toolkit

# Open SSH and Web UI ports
EXPOSE 2233

CMD [ "sh", "/run.sh" ]
