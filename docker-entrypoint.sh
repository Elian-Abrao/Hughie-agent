#!/bin/sh
# Copy SSH files from mounted volume (owned by host user) to /root/.ssh with correct ownership
if [ -d /ssh-host ]; then
    mkdir -p /root/.ssh
    chmod 700 /root/.ssh
    cp -r /ssh-host/. /root/.ssh/
    chmod 600 /root/.ssh/* 2>/dev/null || true
    chmod 644 /root/.ssh/*.pub 2>/dev/null || true
    chmod 644 /root/.ssh/known_hosts 2>/dev/null || true
fi

exec "$@"
