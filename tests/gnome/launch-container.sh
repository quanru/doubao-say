#!/usr/bin/env bash
set -euo pipefail
# GNOME Shell needs a system bus even with a headless, unprivileged compositor.
# Only this disposable container gets the bus; the test itself runs as uid 1000.
mkdir -p /run/dbus
dbus-daemon --system --fork --nopidfile
exec runuser -u gnome-ci -- dbus-run-session -- bash tests/gnome/run-session.sh
