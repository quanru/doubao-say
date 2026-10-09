#!/usr/bin/env bash
set -euo pipefail
# GNOME Shell needs a system bus even with a headless, unprivileged compositor.
# Only this disposable container gets the bus; the test itself runs as uid 1000.
# Package installation can leave an empty seats directory even though systemd
# is not PID 1. Let GNOME use its supported non-systemd session implementation.
rmdir /run/systemd/seats 2>/dev/null || true
mkdir -p /run/dbus
dbus-daemon --system --fork --nopidfile
exec runuser -u gnome-ci -- dbus-run-session -- bash tests/gnome/run-session.sh
